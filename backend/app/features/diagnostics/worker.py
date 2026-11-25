"""Background workers for the backlink checker. Same Appwrite-polling pattern as the indexing workers."""
import asyncio
import logging
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit

import aiohttp

from app.core.config import Settings, get_settings
from app.core.wakeup import heartbeats, wakeups
from app.features.diagnostics import repository
from app.features.diagnostics.scanner import UrlCheck, check_url, evaluate, fetch_problem, make_session

log = logging.getLogger(__name__)

MIN_SLEEP = 1.0
MAX_SLEEP = 15.0
RECOVERY_INTERVAL = 60.0

_host_slots: dict[str, asyncio.Semaphore] = defaultdict(lambda: asyncio.Semaphore(get_settings().CHECK_PER_HOST_CONCURRENCY))


def result_json(check: UrlCheck) -> str:
    return check.model_dump_json()


async def _claim(row: dict[str, Any], worker_id: str) -> dict[str, Any] | None:
    """Optimistic lock: write our id, re-read, keep the row only if it is still ours."""
    attempts = int(row.get("attempts") or 0) + 1
    try:
        await repository.update_check(row["id"], {"status": "processing", "attempts": attempts, "locked_by": worker_id})
        fresh = await repository.get_check(row["id"])
    except Exception as e:
        log.debug("Claim failed for %s: %s", row.get("id"), e)
        return None
    if fresh.get("locked_by") != worker_id or fresh.get("status") != "processing":
        return None
    return fresh


async def _run_check(session: aiohttp.ClientSession, row: dict[str, Any], settings: Settings) -> None:
    host = urlsplit(row["url"]).netloc
    try:
        async with _host_slots[host]:  # do not hammer a single site
            check = await check_url(session, row["url"], row.get("target") or None)
    except asyncio.CancelledError:
        try:
            await asyncio.shield(repository.update_check(row["id"], {"status": "pending", "locked_by": None}))
        finally:
            raise
    except Exception:
        log.exception("Unexpected error checking %s", row.get("url"))
        if int(row.get("attempts") or 0) < settings.CHECK_MAX_ATTEMPTS:
            await repository.update_check(row["id"], {"status": "pending", "locked_by": None})
            return
        check = UrlCheck(url=row["url"])
        check.problems.append(fetch_problem("fetch_failed", "internal error"))
        evaluate(check)
    try:
        await repository.update_check(
            row["id"], {"status": "done", "locked_by": None, "verdict": check.verdict, "result": result_json(check)}
        )
    except Exception:
        log.exception("Failed to save check result for %s", row["id"])


async def recover_stale(settings: Settings) -> int:
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=settings.STALE_LOCK_SECONDS)).isoformat()
    n = 0
    for row in await repository.list_stale(cutoff):
        try:
            await repository.update_check(row["id"], {"status": "pending", "locked_by": None})
            n += 1
        except Exception:
            log.exception("Failed to recover stale check %s", row.get("id"))
    return n


async def check_worker(worker_id: str) -> None:
    settings = get_settings()
    error_sleep = MIN_SLEEP
    next_recovery = 0.0
    fallback = max(settings.WORKER_FALLBACK_POLL_SECONDS, 60)
    log.info("%s started", worker_id)
    loop = asyncio.get_running_loop()
    async with make_session() as session:
        try:
            while True:
                try:
                    if worker_id.endswith("-1") and loop.time() >= next_recovery:
                        next_recovery = loop.time() + RECOVERY_INTERVAL
                        if n := await recover_stale(settings):
                            log.info("Recovered %d stale check(s)", n)
                    heartbeats.beat(worker_id, "polling", stale_after=900)
                    rows = await repository.list_pending(settings.CHECK_WORKER_BATCH_SIZE)
                    claimed = [c for c in [await _claim(r, worker_id) for r in rows] if c]
                    if claimed:
                        error_sleep = MIN_SLEEP
                        heartbeats.beat(worker_id, "busy", stale_after=900)
                        await asyncio.gather(*(_run_check(session, c, settings) for c in claimed))
                        heartbeats.beat(worker_id, "polling", stale_after=900, processed=len(claimed))
                        continue
                    if rows:  # another worker won every claim: look again shortly
                        await asyncio.sleep(2 + random.uniform(0, 1))
                        continue
                    heartbeats.beat(worker_id, "idle", stale_after=fallback * 2 + 60)
                    await wakeups.wait("checks", fallback)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("%s loop error", worker_id)
                    await asyncio.sleep(error_sleep)
                    error_sleep = min(error_sleep * 2, MAX_SLEEP)
        except asyncio.CancelledError:
            heartbeats.remove(worker_id)
            log.info("%s stopping", worker_id)
            raise
