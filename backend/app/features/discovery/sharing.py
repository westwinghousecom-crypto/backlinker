"""Customer opt-in for public per-batch feeds. A batch's feed is private unless its owner turns sharing on."""
import asyncio

from app.core.appwrite_client import get_tables_db
from app.core.bulk import owner_permissions
from app.core.config import get_settings


def _ids() -> tuple[str, str]:
    s = get_settings()
    return s.APPWRITE_DATABASE_ID, s.APPWRITE_BATCH_SHARING_TABLE_ID


def _is_public_sync(batch_id: str) -> bool:
    db, tbl = _ids()
    try:
        row = get_tables_db().get_row(database_id=db, table_id=tbl, row_id=batch_id)
    except Exception as e:
        if getattr(e, "code", None) == 404:
            return False
        raise
    return bool(row.data.get("public_feed"))


async def is_public(batch_id: str) -> bool:
    """True only if the owner explicitly opted in. Any lookup failure counts as 'not public'."""
    try:
        return await asyncio.to_thread(_is_public_sync, batch_id)
    except Exception:
        return False


def _set_sync(batch_id: str, user_id: str, public: bool) -> None:
    db, tbl = _ids()
    t = get_tables_db()
    try:
        t.update_row(database_id=db, table_id=tbl, row_id=batch_id, data={"public_feed": public})
    except Exception as e:
        if getattr(e, "code", None) != 404:
            raise
        t.create_row(
            database_id=db, table_id=tbl, row_id=batch_id,
            data={"user_id": user_id, "public_feed": public}, permissions=owner_permissions(user_id),
        )


async def set_public(batch_id: str, user_id: str, public: bool) -> None:
    """Callers must already have verified that `user_id` owns `batch_id`."""
    await asyncio.to_thread(_set_sync, batch_id, user_id, public)
