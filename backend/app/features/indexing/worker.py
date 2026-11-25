import asyncio
import logging
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import aiohttp

from app.core.config import Settings, get_settings
from app.core.wakeup import heartbeats, wakeups
from app.features.indexing import repository
from app.features.indexing.indexer import submit_urls
from app.features.proxy.rotator import FreeProxyRotator

log = logging.getLogger(__name__)

MIN_SLEEP = 1.0
MAX_SLEEP = 30.0
RECOVERY_INTERVAL = 60.0


async def recover_stale(settings: Settings, max_attempts: int | None = None) -> int:
    """Return rows abandoned in 'processing' (e.g. after a crash) to the queue."""
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=settings.STALE_LOCK_SECONDS)).isoformat()
    recovered = 0
    for row in await repository.list_stale(cutoff):
        exhausted = int(row.get("attempts") or 0) >= (max_attempts or settings.MAX_ATTEMPTS)
        try:
            await repository.update_row(
                row["id"], {"status": "failed" if exhausted else "pending", "locked_by": None}
            )
            recovered += 1
        except Exception:
            log.exception("Failed to recover stale row %s", row.get("id"))
    return recovered


async def _claim(row: dict[str, Any], worker_id: str) -> dict[str, Any] | None:
    """Optimistic lock: write our id, re-read, and keep the row only if it is still ours."""
    attempts = int(row.get("attempts") or 0) + 1
    try:
        await repository.update_row(
            row["id"],
            {"status": "processing", "attempts": attempts, "locked_by": worker_id},
        )
        fresh = await repository.get_row(row["id"])
    except Exception as e:
        log.debug("Claim failed for %s: %s", row.get("id"), e)
        return None
    if fresh.get("locked_by") != worker_id or fresh.get("status") != "processing":
        return None
    return fresh


async def _process_batch(
    rows: list[dict[str, Any]],
    session: aiohttp.ClientSession,
    settings: Settings,
    rotator: FreeProxyRotator | None,
) -> None:
    results: dict[str, str | None] = {}
    try:
        results = await submit_urls(session, settings, [r["url"] for r in rows], rotator)
    except asyncio.CancelledError:
        # Release the rows so they are not stuck in 'processing', then propagate.
        try:
            await asyncio.shield(
                asyncio.gather(
                    *(repository.update_row(r["id"], {"status": "pending", "locked_by": None}) for r in rows),
                    return_exceptions=True,
                )
            )
        finally:
            raise
    except Exception:
        log.exception("Unexpected error submitting %d URL(s)", len(rows))

    async def finalize(row: dict[str, Any]) -> None:
        outcome = results.get(row["url"])
        if outcome:
            status = outcome  # "completed" (confirmed) or "submitted" (accepted, validation pending)
        elif int(row.get("attempts") or 0) >= settings.MAX_ATTEMPTS:
            status = "failed"
        else:
            status = "pending"
        try:
            await repository.update_row(row["id"], {"status": status, "locked_by": None})
        except Exception:
            log.exception("Failed to finalize row %s as %s", row["id"], status)

    await asyncio.gather(*(finalize(r) for r in rows))


async def background_worker(worker_id: str | None = None, rotator: FreeProxyRotator | None = None) -> None:
    settings = get_settings()
    worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
    error_sleep = MIN_SLEEP
    next_recovery = 0.0
    fallback = max(settings.WORKER_FALLBACK_POLL_SECONDS, 60)
    log.info("%s started", worker_id)
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            while True:
                try:
                    if worker_id.endswith("-1") and asyncio.get_running_loop().time() >= next_recovery:
                        next_recovery = asyncio.get_running_loop().time() + RECOVERY_INTERVAL
                        if n := await recover_stale(settings):
                            log.info("Recovered %d stale row(s)", n)
                    heartbeats.beat(worker_id, "polling", stale_after=900)
                    rows = await repository.list_pending(settings.WORKER_BATCH_SIZE)
                    claimed = [c for c in [await _claim(r, worker_id) for r in rows] if c]
                    if claimed:
                        error_sleep = MIN_SLEEP
                        heartbeats.beat(worker_id, "busy", stale_after=900)
                        await _process_batch(claimed, session, settings, rotator)
                        heartbeats.beat(worker_id, "polling", stale_after=900, processed=len(claimed))
                        continue
                    if rows:  # work exists but another worker won every claim: look again shortly
                        await asyncio.sleep(2 + random.uniform(0, 1))
                        continue
                    # Nothing to do: sleep until new work is announced (or the slow safety-net poll).
                    heartbeats.beat(worker_id, "idle", stale_after=fallback * 2 + 60)
                    await wakeups.wait("indexing", fallback)
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