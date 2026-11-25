from functools import lru_cache
from typing import Any

from appwrite.client import Client
from appwrite.services.tables_db import TablesDB

from app.core.config import get_settings
from app.core.usage import instrument


@lru_cache
def get_tables_db() -> TablesDB:
    s = get_settings()
    client = Client()
    client.set_endpoint(s.APPWRITE_ENDPOINT)
    client.set_project(s.APPWRITE_PROJECT_ID)
    client.set_key(s.APPWRITE_API_KEY)
    return instrument(TablesDB(client))


def row_to_dict(row: Any) -> dict[str, Any]:
    """Flatten an SDK Row model (or plain dict) into {'id': ..., **columns}."""
    if isinstance(row, dict):
        data = dict(row)
        data.setdefault("id", data.get("$id"))
        return data
    return {"id": row.id, "updated_at": getattr(row, "updatedat", None), **dict(row.data)}