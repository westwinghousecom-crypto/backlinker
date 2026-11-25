"""Customer data export and account deletion.

Every query is filtered by the VERIFIED user id (never a value from the request). Export returns metadata for the Google
connection only: the encrypted refresh token is never included. Deletion is idempotent and resumable: each step removes
whatever is left, the Appwrite user is removed last, so a failure part-way simply means the customer can press delete again.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from appwrite.client import Client
from appwrite.exception import AppwriteException
from appwrite.query import Query
from appwrite.services.account import Account
from appwrite.services.users import Users

from app.core.appwrite_client import get_tables_db
from app.core.auth import AuthUser
from app.core.config import get_settings

log = logging.getLogger(__name__)

PAGE = 100
MAX_EXPORT_ROWS = 50_000  # across all tables; the export says so if it was cut off

# (table setting name, export key). All of these tables carry a user_id column.
OWNED_TABLES = [
    ("APPWRITE_URLS_TABLE_ID", "urls"),
    ("APPWRITE_CHECK_BATCHES_TABLE_ID", "check_batches"),
    ("APPWRITE_CHECKS_TABLE_ID", "checks"),
    ("APPWRITE_BATCH_SHARING_TABLE_ID", "batch_sharing"),
    ("APPWRITE_GOOGLE_CONNECTIONS_TABLE_ID", "google_connection"),
    ("APPWRITE_GSC_TARGETS_TABLE_ID", "google_tracked_urls"),
    ("APPWRITE_GSC_HISTORY_TABLE_ID", "google_inspection_history"),
]
# Deletion order: children first, then parents; the OAuth-state table is included so nothing keyed to the user stays behind.
DELETE_ORDER = [
    "APPWRITE_GSC_HISTORY_TABLE_ID", "APPWRITE_GSC_TARGETS_TABLE_ID", "APPWRITE_GOOGLE_CONNECTIONS_TABLE_ID",
    "APPWRITE_GOOGLE_OAUTH_STATES_TABLE_ID", "APPWRITE_CHECKS_TABLE_ID", "APPWRITE_CHECK_BATCHES_TABLE_ID",
    "APPWRITE_BATCH_SHARING_TABLE_ID", "APPWRITE_URLS_TABLE_ID",
]
# The ONLY fields of the Google connection that may leave the server. refresh_token_enc is deliberately absent.
CONNECTION_FIELDS = ("google_email", "scopes", "status", "selected_property", "error_code")


def _clean(row: Any, key: str) -> dict[str, Any]:
    data = dict(row.data)
    if key == "google_connection":
        data = {k: data.get(k) for k in CONNECTION_FIELDS}
    return {"id": row.id, "created_at": getattr(row, "createdat", None), "updated_at": getattr(row, "updatedat", None), **data}


def _export_sync(user_id: str) -> dict[str, Any]:
    s = get_settings()
    db = get_tables_db()
    out: dict[str, Any] = {}
    budget = MAX_EXPORT_ROWS
    truncated = False
    for setting, key in OWNED_TABLES:
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            if budget <= 0:
                truncated = True
                break
            res = db.list_rows(
                database_id=s.APPWRITE_DATABASE_ID, table_id=getattr(s, setting),
                queries=[Query.equal("user_id", user_id), Query.limit(PAGE), Query.offset(offset)],
            )
            page = [r for r in res.rows if r.data.get("user_id") == user_id]  # belt and braces: never another customer's row
            rows.extend(_clean(r, key) for r in page)
            budget -= len(page)
            if len(res.rows) < PAGE:
                break
            offset += PAGE
        out[key] = rows[0] if key == "google_connection" and rows else (None if key == "google_connection" else rows)
    out["_truncated"] = truncated
    return out


async def export_data(user: AuthUser) -> bytes:
    body = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "account": {"id": user.id, "email": user.email},
        "note": "Everything QuickIndex stores about this account. The Google refresh token is never exported.",
        **await asyncio.to_thread(_export_sync, user.id),
    }
    return json.dumps(body, indent=2, default=str).encode("utf-8")


# ---------------------------------------------------------------------------------------------- deletion

def _purge_rows_sync(user_id: str) -> dict[str, int]:
    s = get_settings()
    db = get_tables_db()
    counts: dict[str, int] = {}
    for setting in DELETE_ORDER:
        total = 0
        for _ in range(200):
            res = db.delete_rows(
                database_id=s.APPWRITE_DATABASE_ID, table_id=getattr(s, setting),
                queries=[Query.equal("user_id", user_id), Query.limit(PAGE)],
            )
            if int(res.total) == 0:
                break
            total += int(res.total)
        counts[setting.removeprefix("APPWRITE_").removesuffix("_TABLE_ID").lower()] = total
    return counts


def _server_client() -> Client:
    s = get_settings()
    c = Client()
    c.set_endpoint(s.APPWRITE_ENDPOINT)
    c.set_project(s.APPWRITE_PROJECT_ID)
    c.set_key(s.APPWRITE_API_KEY)
    return c


def _remove_user_sync(user_id: str, token: str) -> str:
    """Delete the Appwrite user. Returns "deleted", or "blocked" when the server key may not delete users.

    Deleting needs the `users.write` scope on the API key. Without it the customer's own session is used to BLOCK the
    account (Appwrite keeps the record but permanently denies access); a console action or the scope is then needed to
    remove the record itself."""
    try:
        Users(_server_client()).delete(user_id=user_id)
        return "deleted"
    except AppwriteException as e:
        if e.code == 404:
            return "deleted"  # already gone: deleting twice is fine
        if e.code not in (401, 403):
            raise
    s = get_settings()
    c = Client()
    c.set_endpoint(s.APPWRITE_ENDPOINT)
    c.set_project(s.APPWRITE_PROJECT_ID)
    c.set_jwt(token)
    Account(c).update_status()
    return "blocked"


async def remove_user(user: AuthUser) -> str:
    return await asyncio.to_thread(_remove_user_sync, user.id, user.token)


async def delete_account(user: AuthUser) -> dict[str, Any]:
    # 1. Revoke Google (best effort) and drop the connection.
    try:
        from app.features.google import service as google

        await google.disconnect(user.id)
    except Exception as e:
        log.warning("google revoke during account deletion failed (%s); continuing", type(e).__name__)
    # 2. Every row the customer owns.
    counts = await asyncio.to_thread(_purge_rows_sync, user.id)
    # 3. The Appwrite user last, so a failure above can simply be retried.
    outcome = await remove_user(user)
    return {"rows": counts, "user": outcome}
