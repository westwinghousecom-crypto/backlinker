"""Appwrite access for the backlink checker (tables: check_batches, checks)."""
import asyncio
from typing import Any

from appwrite.query import Query

from app.core.appwrite_client import get_tables_db, row_to_dict
from app.core.bulk import bulk_create, owner_permissions
from app.core.config import get_settings

PAGE = 100


def _db() -> str:
    return get_settings().APPWRITE_DATABASE_ID


def _checks() -> str:
    return get_settings().APPWRITE_CHECKS_TABLE_ID


def _batches() -> str:
    return get_settings().APPWRITE_CHECK_BATCHES_TABLE_ID


# ---- sync primitives (the Appwrite SDK is blocking; callers wrap these in to_thread)

def _list_sync(table: str, queries: list[str], max_rows: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    offset = 0
    while len(out) < max_rows:
        res = get_tables_db().list_rows(
            database_id=_db(), table_id=table, queries=[*queries, Query.limit(PAGE), Query.offset(offset)]
        )
        rows = [row_to_dict(r) for r in res.rows]
        out.extend(rows)
        if len(rows) < PAGE:
            break
        offset += PAGE
    return out[:max_rows]


def _count_sync(table: str, queries: list[str]) -> int:
    res = get_tables_db().list_rows(database_id=_db(), table_id=table, queries=[*queries, Query.limit(1)])
    return int(res.total)


# ---- batches

async def create_batch(batch_id: str, user_id: str, target: str | None, total: int) -> None:
    await asyncio.to_thread(
        get_tables_db().create_row,
        database_id=_db(), table_id=_batches(), row_id=batch_id,
        data={"user_id": user_id, "target": target, "total": total},
        permissions=owner_permissions(user_id),
    )


async def get_batch(batch_id: str) -> dict[str, Any] | None:
    try:
        row = await asyncio.to_thread(
            get_tables_db().get_row, database_id=_db(), table_id=_batches(), row_id=batch_id
        )
    except Exception as e:  # Appwrite raises AppwriteException(404) for missing rows
        if getattr(e, "code", None) == 404:
            return None
        raise
    d = row_to_dict(row)
    d["created_at"] = getattr(row, "createdat", None)
    return d


async def update_batch_total(batch_id: str, total: int) -> None:
    await asyncio.to_thread(
        get_tables_db().update_row, database_id=_db(), table_id=_batches(), row_id=batch_id, data={"total": total}
    )


async def set_public_report(batch_id: str, public: bool) -> None:
    await asyncio.to_thread(
        get_tables_db().update_row,
        database_id=_db(), table_id=_batches(), row_id=batch_id, data={"public_report": public},
    )


async def delete_batch(batch_id: str) -> None:
    await asyncio.to_thread(get_tables_db().delete_row, database_id=_db(), table_id=_batches(), row_id=batch_id)


async def list_batches(user_id: str, limit: int) -> list[dict[str, Any]]:
    def run() -> list[dict[str, Any]]:
        res = get_tables_db().list_rows(
            database_id=_db(), table_id=_batches(),
            queries=[Query.equal("user_id", user_id), Query.order_desc("$createdAt"), Query.limit(limit)],
        )
        return [{**row_to_dict(r), "created_at": r.createdat} for r in res.rows]

    return await asyncio.to_thread(run)


# ---- checks

async def create_checks(rows: list[dict[str, Any]]) -> int:
    """Bulk-insert check rows (each with ``$id``/``$permissions``). Raises if any row could not be stored."""
    created, errors = await bulk_create(_checks(), rows)
    if errors:
        raise RuntimeError(errors[0])
    return created


async def count_queued(user_id: str) -> int:
    return await asyncio.to_thread(
        _count_sync, _checks(), [Query.equal("user_id", user_id), Query.equal("status", ["pending", "processing"])]
    )


async def delete_checks(batch_id: str) -> None:
    """Delete every check row of a batch, using Appwrite bulk delete (falls back to one by one)."""

    def run() -> None:
        db = get_tables_db()
        for _ in range(200):  # at most 200 * PAGE rows; a batch holds at most 1000
            q = [Query.equal("batch_id", batch_id), Query.limit(PAGE)]
            try:
                res = db.delete_rows(database_id=_db(), table_id=_checks(), queries=q)
                if int(res.total) == 0:
                    return
                continue
            except Exception:
                pass  # bulk delete unavailable: delete this page row by row
            rows = db.list_rows(database_id=_db(), table_id=_checks(), queries=q).rows
            if not rows:
                return
            for r in rows:
                try:
                    db.delete_row(database_id=_db(), table_id=_checks(), row_id=r.id)
                except Exception:
                    pass  # already gone (e.g. concurrent delete)

    await asyncio.to_thread(run)


async def list_checks(batch_id: str, max_rows: int = 1000) -> list[dict[str, Any]]:
    rows = await asyncio.to_thread(_list_sync, _checks(), [Query.equal("batch_id", batch_id)], max_rows)
    return sorted(rows, key=lambda r: r.get("position", 0))


async def count_checks(batch_id: str, status: str | None = None) -> int:
    q = [Query.equal("batch_id", batch_id)]
    if status:
        q.append(Query.equal("status", status))
    return await asyncio.to_thread(_count_sync, _checks(), q)


async def get_check(check_id: str) -> dict[str, Any]:
    row = await asyncio.to_thread(get_tables_db().get_row, database_id=_db(), table_id=_checks(), row_id=check_id)
    return row_to_dict(row)


async def update_check(check_id: str, data: dict[str, Any]) -> dict[str, Any]:
    row = await asyncio.to_thread(
        get_tables_db().update_row, database_id=_db(), table_id=_checks(), row_id=check_id, data=data
    )
    return row_to_dict(row)


async def list_pending(limit: int) -> list[dict[str, Any]]:
    return await asyncio.to_thread(
        _list_sync, _checks(), [Query.equal("status", "pending"), Query.order_asc("$createdAt")], limit
    )


async def list_stale(cutoff_iso: str, limit: int = 50) -> list[dict[str, Any]]:
    return await asyncio.to_thread(
        _list_sync, _checks(), [Query.equal("status", "processing"), Query.less_than("$updatedAt", cutoff_iso)], limit
    )
