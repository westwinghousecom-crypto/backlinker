import asyncio
from typing import Any

from appwrite.query import Query

from app.core.appwrite_client import get_tables_db, row_to_dict
from app.core.config import get_settings

PAGE = 100


def _list_sync(filters: list[str], max_rows: int) -> list[dict[str, Any]]:
    s = get_settings()
    out: list[dict[str, Any]] = []
    offset = 0
    while len(out) < max_rows:
        res = get_tables_db().list_rows(
            database_id=s.APPWRITE_DATABASE_ID,
            table_id=s.APPWRITE_URLS_TABLE_ID,
            queries=[*filters, Query.order_desc("$updatedAt"), Query.limit(PAGE), Query.offset(offset)],
        )
        rows = [row_to_dict(r) for r in res.rows]
        out.extend(rows)
        if len(rows) < PAGE:
            break
        offset += PAGE
    return out[:max_rows]


async def list_published(max_rows: int, batch_id: str | None = None) -> list[dict[str, Any]]:
    """URLs that are not failed: all of a batch, or completed/submitted ones globally."""
    filters = [Query.equal("batch_id", batch_id), Query.not_equal("status", "failed")] if batch_id else [
        Query.equal("status", ["completed", "submitted"])
    ]
    return await asyncio.to_thread(_list_sync, filters, max_rows)
