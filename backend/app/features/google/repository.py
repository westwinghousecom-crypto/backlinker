"""Appwrite storage for the Google integration. Every read of customer data is filtered by user id."""
import asyncio
import hashlib
from typing import Any

from appwrite.id import ID
from appwrite.query import Query

from app.core.appwrite_client import get_tables_db, row_to_dict
from app.core.bulk import bulk_create, owner_permissions
from app.core.config import get_settings
from app.features.google.quota import counter_id

PAGE = 100


def _db() -> str:
    return get_settings().APPWRITE_DATABASE_ID


def _t(name: str) -> str:
    return getattr(get_settings(), name)


CONNECTIONS = "APPWRITE_GOOGLE_CONNECTIONS_TABLE_ID"
TARGETS = "APPWRITE_GSC_TARGETS_TABLE_ID"
HISTORY = "APPWRITE_GSC_HISTORY_TABLE_ID"
QUOTA = "APPWRITE_GOOGLE_QUOTA_TABLE_ID"


def _is_404(e: Exception) -> bool:
    return getattr(e, "code", None) == 404


def _get_sync(table: str, row_id: str) -> dict[str, Any] | None:
    try:
        return row_to_dict(get_tables_db().get_row(database_id=_db(), table_id=_t(table), row_id=row_id))
    except Exception as e:
        if _is_404(e):
            return None
        raise


def _list_sync(table: str, queries: list[str], max_rows: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    offset = 0
    while len(out) < max_rows:
        res = get_tables_db().list_rows(
            database_id=_db(), table_id=_t(table), queries=[*queries, Query.limit(PAGE), Query.offset(offset)]
        )
        rows = [row_to_dict(r) for r in res.rows]
        out.extend(rows)
        if len(rows) < PAGE:
            break
        offset += PAGE
    return out[:max_rows]


# ---------------------------------------------------------------------------- connections (row id = customer id)

async def get_connection(user_id: str) -> dict[str, Any] | None:
    return await asyncio.to_thread(_get_sync, CONNECTIONS, user_id)


def _upsert_connection_sync(user_id: str, data: dict[str, Any]) -> None:
    t = get_tables_db()
    try:
        t.update_row(database_id=_db(), table_id=_t(CONNECTIONS), row_id=user_id, data=data)
    except Exception as e:
        if not _is_404(e):
            raise
        t.create_row(database_id=_db(), table_id=_t(CONNECTIONS), row_id=user_id,
                     data={"user_id": user_id, **data}, permissions=owner_permissions(user_id))


async def upsert_connection(user_id: str, data: dict[str, Any]) -> None:
    await asyncio.to_thread(_upsert_connection_sync, user_id, data)


async def delete_connection(user_id: str) -> None:
    def run() -> None:
        try:
            get_tables_db().delete_row(database_id=_db(), table_id=_t(CONNECTIONS), row_id=user_id)
        except Exception as e:
            if not _is_404(e):
                raise

    await asyncio.to_thread(run)


# ---------------------------------------------------------------------------- tracked URLs

def target_id(user_id: str, property_url: str, url: str) -> str:
    """Deterministic id: tracking the same URL twice is a no-op, and ids never collide across customers."""
    return hashlib.sha1(f"{user_id}\n{property_url}\n{url}".encode()).hexdigest()[:32]


async def existing_target_ids(ids: list[str]) -> set[str]:
    def run() -> set[str]:
        found: set[str] = set()
        for i in range(0, len(ids), PAGE):
            res = get_tables_db().list_rows(
                database_id=_db(), table_id=_t(TARGETS), queries=[Query.equal("$id", ids[i : i + PAGE]), Query.limit(PAGE)]
            )
            found.update(r.id for r in res.rows)
        return found

    return await asyncio.to_thread(run)


async def create_targets(user_id: str, rows: list[dict[str, Any]]) -> tuple[int, list[str]]:
    perms = owner_permissions(user_id)
    return await bulk_create(_t(TARGETS), [{**r, "$permissions": perms} for r in rows])


async def list_targets(user_id: str, max_rows: int = 2000) -> list[dict[str, Any]]:
    return await asyncio.to_thread(_list_sync, TARGETS, [Query.equal("user_id", user_id)], max_rows)


async def count_targets(user_id: str) -> int:
    def run() -> int:
        res = get_tables_db().list_rows(
            database_id=_db(), table_id=_t(TARGETS), queries=[Query.equal("user_id", user_id), Query.limit(1)]
        )
        return int(res.total)

    return await asyncio.to_thread(run)


async def get_target(tid: str) -> dict[str, Any] | None:
    return await asyncio.to_thread(_get_sync, TARGETS, tid)


async def update_target(tid: str, data: dict[str, Any]) -> dict[str, Any]:
    return row_to_dict(await asyncio.to_thread(
        get_tables_db().update_row, database_id=_db(), table_id=_t(TARGETS), row_id=tid, data=data))


async def delete_target(tid: str) -> None:
    def run() -> None:
        try:
            get_tables_db().delete_row(database_id=_db(), table_id=_t(TARGETS), row_id=tid)
        except Exception as e:
            if not _is_404(e):
                raise

    await asyncio.to_thread(run)


async def list_due(now_iso: str, limit: int) -> list[dict[str, Any]]:
    return await asyncio.to_thread(
        _list_sync, TARGETS,
        [Query.equal("status", "pending"), Query.less_than_equal("next_check_at", now_iso), Query.order_asc("next_check_at")],
        limit,
    )


async def list_stale(cutoff_iso: str, limit: int = 50) -> list[dict[str, Any]]:
    return await asyncio.to_thread(
        _list_sync, TARGETS, [Query.equal("status", "processing"), Query.less_than("$updatedAt", cutoff_iso)], limit
    )


async def list_paused(user_id: str) -> list[dict[str, Any]]:
    return await asyncio.to_thread(
        _list_sync, TARGETS, [Query.equal("user_id", user_id), Query.equal("status", "paused")], 2000
    )


# ---------------------------------------------------------------------------- history (append-only)

async def add_history(user_id: str, row: dict[str, Any]) -> None:
    def run() -> None:
        get_tables_db().create_row(
            database_id=_db(), table_id=_t(HISTORY), row_id=ID.unique(),
            data={"user_id": user_id, **row}, permissions=owner_permissions(user_id),
        )

    await asyncio.to_thread(run)


async def list_history(user_id: str, tid: str, limit: int = 100) -> list[dict[str, Any]]:
    rows = await asyncio.to_thread(
        _list_sync, HISTORY, [Query.equal("target_id", tid), Query.equal("user_id", user_id), Query.order_asc("inspected_at")], limit
    )
    return rows


async def delete_history(tid: str) -> None:
    def run() -> None:
        db = get_tables_db()
        for _ in range(50):
            try:
                res = db.delete_rows(database_id=_db(), table_id=_t(HISTORY), queries=[Query.equal("target_id", tid), Query.limit(PAGE)])
                if int(res.total) == 0:
                    return
            except Exception:
                return

    await asyncio.to_thread(run)


# ---------------------------------------------------------------------------- quota counters

class AppwriteCounterStore:
    """Daily inspection counters. Increments are atomic and capped by Appwrite itself (no read-modify-write race)."""

    async def get(self, property_url: str, day: str) -> int:
        row = await asyncio.to_thread(_get_sync, QUOTA, counter_id(property_url, day))
        return int((row or {}).get("count", 0))

    async def incr(self, property_url: str, day: str, limit: int) -> int | None:
        rid = counter_id(property_url, day)

        def run() -> int | None:
            t = get_tables_db()
            if limit <= 0:
                return None
            try:
                t.create_row(database_id=_db(), table_id=_t(QUOTA), row_id=rid,
                             data={"property": property_url, "day": day, "count": 0})
            except Exception as e:
                if getattr(e, "code", None) != 409:  # already exists is the normal case
                    raise
            try:
                row = t.increment_row_column(database_id=_db(), table_id=_t(QUOTA), row_id=rid,
                                             column="count", value=1, max=limit)
                return int(row.data["count"])
            except Exception as e:
                if getattr(e, "code", None) == 400 and "maximum" in str(e).lower():
                    return None  # the cap was reached: nothing was added
                raise

        return await asyncio.to_thread(run)


# ---------------------------------------------------------------------------- single-use OAuth state

OAUTH_STATES = "APPWRITE_GOOGLE_OAUTH_STATES_TABLE_ID"


def state_row_id(nonce: str) -> str:
    return hashlib.sha256(nonce.encode()).hexdigest()[:32]


async def claim_oauth_state(nonce: str, user_id: str) -> bool:
    """Consume a state nonce. True the first time; False if it was already used (a replay). Creating a row with a
    fixed id is atomic in Appwrite, so two simultaneous callbacks cannot both succeed."""

    def run() -> bool:
        try:
            get_tables_db().create_row(database_id=_db(), table_id=_t(OAUTH_STATES), row_id=state_row_id(nonce),
                                       data={"user_id": user_id}, permissions=owner_permissions(user_id))
            return True
        except Exception as e:
            if getattr(e, "code", None) == 409:
                return False
            raise

    return await asyncio.to_thread(run)


async def purge_oauth_states(cutoff_iso: str) -> None:
    """Delete nonces older than the state's own lifetime (they can no longer be presented anyway)."""

    def run() -> None:
        try:
            get_tables_db().delete_rows(database_id=_db(), table_id=_t(OAUTH_STATES),
                                        queries=[Query.less_than("$createdAt", cutoff_iso), Query.limit(PAGE)])
        except Exception:
            pass

    await asyncio.to_thread(run)


async def delete_user_data(user_id: str) -> None:
    """Delete every tracked URL and its inspection history for one customer."""

    def run() -> None:
        db = get_tables_db()
        for table in (HISTORY, TARGETS):
            for _ in range(100):
                try:
                    res = db.delete_rows(database_id=_db(), table_id=_t(table),
                                         queries=[Query.equal("user_id", user_id), Query.limit(PAGE)])
                except Exception:
                    break
                if int(res.total) == 0:
                    break

    await asyncio.to_thread(run)
