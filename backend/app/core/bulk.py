"""Bulk row creation for Appwrite TablesDB, with per-row recovery.

Appwrite limits rows per bulk request by plan (Free: 100, Pro: 1,000), so rows go in chunks of
``APPWRITE_BULK_CHUNK_SIZE``. Each row gets a deterministic id, so a failed bulk call can be retried row by
row without creating duplicates: a 409 ("already exists") just means the earlier attempt got that row in.
Every row is readable only by its owner (Appwrite row security), in addition to the checks the API makes.
"""
import asyncio
import logging
from typing import Any

from appwrite.exception import AppwriteException
from appwrite.permission import Permission
from appwrite.role import Role

from app.core.appwrite_client import get_tables_db
from app.core.config import get_settings

log = logging.getLogger(__name__)

PARALLEL_CHUNKS = 3


def row_id(batch_id: str, index: int) -> str:
    """Deterministic id (max 36 chars, starts alphanumeric): the batch uuid prefix plus the position."""
    return f"{batch_id.replace('-', '')[:28]}{index:07d}"


def owner_permissions(owner_id: str) -> list[str]:
    return [Permission.read(Role.user(owner_id))]


def chunk_size() -> int:
    return min(max(get_settings().APPWRITE_BULK_CHUNK_SIZE, 1), 1000)


def _create_chunk_sync(table_id: str, chunk: list[dict[str, Any]]) -> tuple[int, list[str]]:
    s = get_settings()
    db = get_tables_db()
    try:
        db.create_rows(database_id=s.APPWRITE_DATABASE_ID, table_id=table_id, rows=chunk)
        return len(chunk), []
    except AppwriteException as e:
        log.warning("Bulk insert of %d rows failed (%s); retrying row by row", len(chunk), e)
    created, errors = 0, []
    for row in chunk:
        data = dict(row)
        rid = data.pop("$id")
        perms = data.pop("$permissions", None)
        try:
            db.create_row(database_id=s.APPWRITE_DATABASE_ID, table_id=table_id, row_id=rid, data=data, permissions=perms)
            created += 1
        except AppwriteException as e:
            if e.code == 409:  # the failed bulk call had already stored this row
                created += 1
            else:
                errors.append(str(e))
    return created, errors


async def bulk_create(
    table_id: str, rows: list[dict[str, Any]], size: int | None = None
) -> tuple[int, list[str]]:
    """Insert rows (each with ``$id`` and ``$permissions``) in chunks. Returns (created_count, errors)."""
    size = size or chunk_size()
    sem = asyncio.Semaphore(PARALLEL_CHUNKS)

    async def one(chunk: list[dict[str, Any]]) -> tuple[int, list[str]]:
        async with sem:
            return await asyncio.to_thread(_create_chunk_sync, table_id, chunk)

    results = await asyncio.gather(*(one(rows[i : i + size]) for i in range(0, len(rows), size)))
    return sum(c for c, _ in results), [e for _, errs in results for e in errs]
