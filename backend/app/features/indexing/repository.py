import asyncio
from typing import Any

from appwrite.query import Query

from app.core.appwrite_client import get_tables_db, row_to_dict
from app.core.config import get_settings


def _ids() -> tuple[str, str]:
    s = get_settings()
    return s.APPWRITE_DATABASE_ID, s.APPWRITE_URLS_TABLE_ID


def _list_pending_sync(limit: int) -> list[dict[str, Any]]:
    db, tbl = _ids()
    res = get_tables_db().list_rows(
        database_id=db,
        table_id=tbl,
        queries=[Query.equal("status", "pending"), Query.limit(limit)],
    )
    return [row_to_dict(r) for r in res.rows]


def _update_sync(row_id: str, data: dict[str, Any]) -> dict[str, Any]:
    db, tbl = _ids()
    return row_to_dict(get_tables_db().update_row(database_id=db, table_id=tbl, row_id=row_id, data=data))


def _get_sync(row_id: str) -> dict[str, Any]:
    db, tbl = _ids()
    return row_to_dict(get_tables_db().get_row(database_id=db, table_id=tbl, row_id=row_id))


async def list_pending(limit: int) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_list_pending_sync, limit)


async def update_row(row_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_update_sync, row_id, data)


async def get_row(row_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(_get_sync, row_id)

def _list_stale_sync(cutoff_iso: str, limit: int) -> list[dict[str, Any]]:
    db, tbl = _ids()
    res = get_tables_db().list_rows(
        database_id=db,
        table_id=tbl,
        queries=[
            Query.equal("status", "processing"),
            Query.less_than("$updatedAt", cutoff_iso),
            Query.limit(limit),
        ],
    )
    return [row_to_dict(r) for r in res.rows]


async def list_stale(cutoff_iso: str, limit: int = 50) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_list_stale_sync, cutoff_iso, limit)
