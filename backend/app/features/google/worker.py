"""Background worker: runs due URL inspections (initially, then at 1, 3, 7 and 14 days), within Google's quota.

Same Appwrite-polling pattern as the other workers (no Redis): due rows are claimed with optimistic locking, processed,
and rescheduled. Failure handling:
  * connection revoked / refresh token rejected -> targets are paused (resumed automatically when the customer reconnects)
  * quota (ours or Google's 429)               -> rescheduled for when the window reopens; nothing recorded
  * transient (5xx, network)                   -> retried with 15 min, 30 min, 1 h ... back-off; recorded as failed after 4 tries
  * permission / bad request / not found       -> recorded as an Inspection Failed history entry, schedule moves on
"""
import asyncio
import json
import logging
import random
from datetime import timedelta
from typing import Any

from app.core.config import get_settings
from app.core.wakeup import heartbeats, wakeups
from app.features.google import api, mapping, oauth, repository as repo, service
from app.features.google.schedule import (
    MAX_ATTEMPTS, backoff, due_at, iso, next_after_manual, next_after_scheduled, parse, utcnow,
)

log = logging.getLogger(__name__)
MIN_SLEEP, MAX_SLEEP = 2.0, 30.0
BATCH = 10
CONCURRENCY = 3
RECOVERY_INTERVAL = 60.0
STALE_SECONDS = 600


async def _claim(row: dict[str, Any], worker_id: str) -> dict[str, Any] | None:
    attempts = int(row.get("attempts") or 0) + 1
    try:
        await repo.update_target(row["id"], {"status": "processing", "attempts": attempts, "locked_by": worker_id})
        fresh = await repo.get_target(row["id"])
    except Exception as e:
        log.debug("claim failed: %s", type(e).__name__)
        return None
    if not fresh or fresh.get("locked_by") != worker_id or fresh.get("status") != "processing":
        return None
    return fresh


async def _reschedule(row: dict[str, Any], when, *, undo_attempt: bool) -> None:
    data: dict[str, Any] = {"status": "pending", "locked_by": None, "next_check_at": iso(when)}
    if undo_attempt:
        data["attempts"] = max(int(row.get("attempts") or 1) - 1, 0)
    await repo.update_target(row["id"], data)


async def _pause(row: dict[str, Any]) -> None:
    await repo.update_target(row["id"], {"status": "paused", "locked_by": None})


async def _finish(row: dict[str, Any], *, outcome: str, status: str, error_code: str | None, inspection: dict | None) -> None:
    """Record the attempt (history + target) and schedule the next check."""
    now = utcnow()
    manual = bool(row.get("manual"))
    started = parse(row.get("started_at")) or now
    steps = int(row.get("step") or 0)
    result_json = json.dumps(inspection) if inspection else None

    previous_error = row.get("last_error")
    # History records every successful inspection and each NEW failure, so a flapping outage does not flood it.
    if outcome == "success" or error_code != previous_error or row.get("latest_outcome") != "failed":
        await repo.add_history(row["user_id"], {
            "target_id": row["id"], "url": row["url"], "property": row["property"], "inspected_at": iso(now),
            "outcome": outcome, "status": status, "error_code": error_code,
            "trigger": "manual" if manual else ("initial" if steps == 0 else "scheduled"), "result": result_json,
        })

    indexed = outcome == "success" and status == mapping.INDEXED
    if manual:
        nxt = next_after_manual(started, steps, now, indexed)
    else:
        steps, nxt = next_after_scheduled(started, steps, now, indexed)
    data: dict[str, Any] = {
        "step": steps, "manual": False, "attempts": 0, "locked_by": None, "latest_outcome": outcome,
        "latest_at": iso(now), "next_check_at": iso(nxt) if nxt else None,
        "status": "pending" if nxt else "done", "last_error": error_code,
    }
    if outcome == "success":
        data.update(latest_status=status, latest_result=result_json)
    await repo.update_target(row["id"], data)


async def process(row: dict[str, Any]) -> None:
    user_id, prop = row["user_id"], row["property"]
    conn = await repo.get_connection(user_id)
    if conn is None or conn.get("status") != "active":
        await _pause(row)
        return
    try:
        token = await service.access_token_for(user_id, conn)
    except service.GoogleError:
        await _pause(row)  # access_token_for already marked the connection revoked
        return

    gate = service.quota_gate()
    res = await gate.reserve(prop, manual=bool(row.get("manual")))
    if not res.ok:
        await _reschedule(row, res.retry_at or utcnow() + timedelta(minutes=1), undo_attempt=True)
        return

    attempts = int(row.get("attempts") or 1)
    try:
        response = await api.inspect_url(token, row["url"], prop)
    except api.GoogleApiError as e:
        if e.kind == "quota":
            # Google's own 429 always wins over our counters, with an escalating pause (2 min, 10 min, 1 h, 6 h, 24 h).
            await _reschedule(row, gate.throttled(prop, e.retry_after), undo_attempt=True)
        elif e.kind == "auth":
            oauth.forget_access_token(user_id)
            if attempts >= 2:  # a fresh token was refused too: the grant is no longer valid
                await repo.upsert_connection(user_id, {"status": "revoked", "error_code": "google_auth_error"})
                await _pause(row)
            else:
                await _reschedule(row, utcnow() + timedelta(minutes=2), undo_attempt=False)
        elif e.kind == "transient":
            if attempts < MAX_ATTEMPTS:
                await _reschedule(row, utcnow() + backoff(attempts), undo_attempt=False)
            else:
                await _finish(row, outcome="failed", status=mapping.UNKNOWN, error_code="google_unavailable", inspection=None)
        else:
            code = {"permission": "permission_denied", "not_found": "property_not_found"}.get(e.kind, "bad_request")
            await _finish(row, outcome="failed", status=mapping.UNKNOWN, error_code=code, inspection=None)
        return

    gate.succeeded(prop)
    insp = mapping.map_inspection(response)
    await _finish(row, outcome="success", status=insp.status, error_code=None, inspection=insp.to_dict())


async def recover_stale() -> int:
    cutoff = iso(utcnow() - timedelta(seconds=STALE_SECONDS))
    n = 0
    for row in await repo.list_stale(cutoff):
        try:
            await repo.update_target(row["id"], {"status": "pending", "locked_by": None})
            n += 1
        except Exception:
            log.warning("could not recover a stale inspection")
    return n


async def gsc_worker(worker_id: str) -> None:
    error_sleep = MIN_SLEEP
    next_recovery = 0.0
    fallback = max(get_settings().WORKER_FALLBACK_POLL_SECONDS, 60)
    loop = asyncio.get_running_loop()
    log.info("%s started", worker_id)
    try:
        while True:
            try:
                if worker_id.endswith("-1") and loop.time() >= next_recovery:
                    next_recovery = loop.time() + RECOVERY_INTERVAL
                    await recover_stale()
                heartbeats.beat(worker_id, "polling", stale_after=900)
                due = await repo.list_due(iso(utcnow()), BATCH)
                claimed = [c for c in [await _claim(r, worker_id) for r in due] if c]
                if claimed:
                    error_sleep = MIN_SLEEP
                    heartbeats.beat(worker_id, "busy", stale_after=900)
                    sem = asyncio.Semaphore(CONCURRENCY)

                    async def one(r: dict[str, Any]) -> None:
                        async with sem:
                            try:
                                await process(r)
                            except Exception:
                                log.exception("inspection crashed")  # row is recovered as stale
                    await asyncio.gather(*(one(c) for c in claimed))
                    heartbeats.beat(worker_id, "polling", stale_after=900, processed=len(claimed))
                    continue
                if due:  # another worker won every claim: look again shortly
                    await asyncio.sleep(2 + random.uniform(0, 1))
                    continue
                # Nothing due: sleep until new targets are announced. Scheduled rechecks (days away) and retry times are
                # found by the slow fallback poll, which is plenty for day-scale schedules.
                heartbeats.beat(worker_id, "idle", stale_after=fallback * 2 + 60)
                await wakeups.wait("gsc", fallback)
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
