"""Data retention: delete old rows so storage, backups and privacy exposure stay bounded.

Budget rule: this must be nearly free when idle. It runs at most once every 24 hours (plus once shortly after start), and
every step is ONE bulk ``delete_rows`` keyed by a ``$createdAt`` / status filter, repeated only while rows were actually
deleted. A run with nothing to delete therefore costs about 7 write requests and no reads.

What is NOT deleted: tracked Google URLs (``gsc_targets``), which are the customer's live schedule, and any submission that
is still pending or processing. Account deletion (account/data.py) is how a customer erases everything on demand.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

from appwrite.query import Query

from app.core.appwrite_client import get_tables_db
from app.core.config import get_settings

log = logging.getLogger(__name__)

FIRST_RUN_DELAY = 300.0  # seconds after start
INTERVAL = 86400.0  # 24 hours
PAGE = 100
MAX_PAGES = 200  # safety cap per table per run (20,000 rows); the next run continues


def _cutoff(**delta) -> str:
    return (datetime.now(timezone.utc) - timedelta(**delta)).isoformat()


def _purge_sync(table_id: str, queries: list[str]) -> int:
    """Bulk-delete matching rows, a page at a time, until none are left. Returns how many were deleted."""
    s = get_settings()
    db = get_tables_db()
    total = 0
    for _ in range(MAX_PAGES):
        res = db.delete_rows(database_id=s.APPWRITE_DATABASE_ID, table_id=table_id, queries=[*queries, Query.limit(PAGE)])
        n = int(res.total)
        if n == 0:
            break
        total += n
    return total


async def _purge(table_id: str, queries: list[str]) -> int:
    return await asyncio.to_thread(_purge_sync, table_id, queries)


async def run_once() -> dict[str, int]:
    """Delete everything past its retention period. Returns the number of rows removed per table."""
    s = get_settings()
    out: dict[str, int] = {}

    batch_cutoff = _cutoff(days=s.RETENTION_CHECK_BATCH_DAYS)
    # Results first, then the batch rows that own them (they were created seconds apart, so one cutoff fits both).
    out["checks"] = await _purge(s.APPWRITE_CHECKS_TABLE_ID, [Query.less_than("$createdAt", batch_cutoff)])
    out["check_batches"] = await _purge(s.APPWRITE_CHECK_BATCHES_TABLE_ID, [Query.less_than("$createdAt", batch_cutoff)])

    sub_cutoff = _cutoff(days=s.RETENTION_SUBMISSION_DAYS)
    out["urls"] = await _purge(s.APPWRITE_URLS_TABLE_ID, [
        Query.equal("status", ["completed", "submitted", "failed"]),  # never pending / processing work
        Query.less_than("$createdAt", sub_cutoff),
    ])
    out["batch_sharing"] = await _purge(s.APPWRITE_BATCH_SHARING_TABLE_ID, [Query.less_than("$createdAt", sub_cutoff)])

    out["gsc_history"] = await _purge(s.APPWRITE_GSC_HISTORY_TABLE_ID,
                                      [Query.less_than("$createdAt", _cutoff(days=s.RETENTION_GSC_HISTORY_DAYS))])
    out["google_oauth_states"] = await _purge(s.APPWRITE_GOOGLE_OAUTH_STATES_TABLE_ID,
                                              [Query.less_than("$createdAt", _cutoff(hours=s.RETENTION_OAUTH_STATE_HOURS))])
    out["google_quota"] = await _purge(s.APPWRITE_GOOGLE_QUOTA_TABLE_ID,
                                       [Query.less_than("$createdAt", _cutoff(days=s.RETENTION_QUOTA_DAYS))])
    return out


async def retention_loop(first_delay: float | None = None, interval: float | None = None) -> None:
    """Run retention 5 minutes after start, then every 24 hours. Errors are logged, never raised; cancellable."""
    if not get_settings().RETENTION_ENABLED:
        log.info("retention disabled (RETENTION_ENABLED=false)")
        return
    await asyncio.sleep(FIRST_RUN_DELAY if first_delay is None else first_delay)
    while True:
        try:
            counts = await run_once()
            log.info("retention removed %s", {k: v for k, v in counts.items() if v} or "nothing")
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("retention run failed; will try again next interval")
        await asyncio.sleep(INTERVAL if interval is None else interval)
