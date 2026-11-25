import asyncio
from typing import Any

from appwrite.query import Query

from app.core.appwrite_client import get_tables_db, row_to_dict
from app.core.bulk import bulk_create
from app.core.config import get_settings

PAGE = 100


async def create_url_rows(rows: list[dict[str, Any]]) -> tuple[int, list[str]]:
    """Bulk-create submission rows (each carries ``$id`` and ``$permissions``). Returns (created, errors)."""
    return await bulk_create(get_settings().APPWRITE_URLS_TABLE_ID, rows)


def _count_queued_sync(user_id: str) -> int:
    s = get_settings()
    res = get_tables_db().list_rows(
        database_id=s.APPWRITE_DATABASE_ID,
        table_id=s.APPWRITE_URLS_TABLE_ID,
        queries=[Query.equal("user_id", user_id), Query.equal("status", ["pending", "processing"]), Query.limit(1)],
    )
    return int(res.total)


async def count_queued(user_id: str) -> int:
    return await asyncio.to_thread(_count_queued_sync, user_id)


def _list_batch_sync(batch_id: str, user_id: str, max_rows: int) -> list[dict[str, Any]]:
    s = get_settings()
    out: list[dict[str, Any]] = []
    offset = 0
    while len(out) < max_rows:
        res = get_tables_db().list_rows(
            database_id=s.APPWRITE_DATABASE_ID,
            table_id=s.APPWRITE_URLS_TABLE_ID,
            # Both filters, always: a batch id alone never returns another customer's rows.
            queries=[
                Query.equal("batch_id", batch_id),
                Query.equal("user_id", user_id),
                Query.limit(PAGE),
                Query.offset(offset),
            ],
        )
        rows = [row_to_dict(r) for r in res.rows]
        out.extend(rows)
        if len(rows) < PAGE:
            break
        offset += PAGE
    return out[:max_rows]


async def list_batch(batch_id: str, user_id: str, max_rows: int = 1000) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_list_batch_sync, batch_id, user_id, max_rows)


def _batch_exists_sync(batch_id: str, user_id: str) -> bool:
    s = get_settings()
    res = get_tables_db().list_rows(
        database_id=s.APPWRITE_DATABASE_ID,
        table_id=s.APPWRITE_URLS_TABLE_ID,
        queries=[Query.equal("batch_id", batch_id), Query.equal("user_id", user_id), Query.limit(1)],
    )
    return len(res.rows) > 0


async def batch_exists(batch_id: str, user_id: str) -> bool:
    """True only if `user_id` owns at least one row of this batch."""
    return await asyncio.to_thread(_batch_exists_sync, batch_id, user_id)


RECENT_SAMPLE = 100


def _recent_batches_sync(user_id: str, limit: int) -> list[dict[str, Any]]:
    """The customer's most recent batches, newest first, from ONE query (plus one cheap count per batch only for heavy users).

    Rows are grouped by batch id. If the customer has no more rows than the sample, totals are exact from the sample. Otherwise
    each listed batch gets its own count query so a big batch cannot hide the older ones or show a wrong total."""
    s = get_settings()
    db = get_tables_db()
    res = db.list_rows(
        database_id=s.APPWRITE_DATABASE_ID,
        table_id=s.APPWRITE_URLS_TABLE_ID,
        queries=[Query.equal("user_id", user_id), Query.order_desc("$createdAt"), Query.limit(RECENT_SAMPLE)],
    )
    batches: dict[str, dict[str, Any]] = {}
    for r in res.rows:
        d = row_to_dict(r)
        b = batches.setdefault(d["batch_id"], {"batch_id": d["batch_id"], "total": 0, "created_at": getattr(r, "createdat", None)})
        b["total"] += 1
        b["created_at"] = getattr(r, "createdat", None) or b["created_at"]  # rows are newest first: ends as the oldest row
    out = list(batches.values())[:limit]
    if int(res.total) > RECENT_SAMPLE:
        for b in out:
            b["total"] = int(
                db.list_rows(
                    database_id=s.APPWRITE_DATABASE_ID,
                    table_id=s.APPWRITE_URLS_TABLE_ID,
                    queries=[Query.equal("batch_id", b["batch_id"]), Query.equal("user_id", user_id), Query.limit(1)],
                ).total
            )
    return out


async def recent_batches(user_id: str, limit: int = 8) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_recent_batches_sync, user_id, limit)
