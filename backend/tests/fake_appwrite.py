"""An in-memory stand-in for Appwrite's TablesDB, shared by the data-lifecycle tests.

It understands the query operators this code base uses (equal, lessThan, limit, offset) on both columns and the
`$id` / `$createdAt` / `$updatedAt` system fields, and, like the real service, it knows nothing about WHO is asking: it
returns whatever the query matches. That is what makes isolation tests meaningful.
"""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from appwrite.exception import AppwriteException

SYSTEM = {"$id": "id", "$createdAt": "createdat", "$updatedAt": "updatedat"}


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse(q: str) -> dict:
    return json.loads(q)


class FakeTablesDB:
    def __init__(self) -> None:
        self.tables: dict[str, dict[str, SimpleNamespace]] = {}

    # ---- helpers
    def seed(self, table: str, row_id: str, data: dict, created: datetime | None = None, permissions=None) -> None:
        stamp = iso(created or datetime.now(timezone.utc))
        self.tables.setdefault(table, {})[row_id] = SimpleNamespace(
            id=row_id, data=dict(data), createdat=stamp, updatedat=stamp, permissions=permissions or [])

    def count(self, table: str) -> int:
        return len(self.tables.get(table, {}))

    def _value(self, row, attr):
        return getattr(row, SYSTEM[attr]) if attr in SYSTEM else row.data.get(attr)

    def _matches(self, row, queries) -> bool:
        for raw in queries or []:
            q = _parse(raw)
            m, attr, vals = q["method"], q.get("attribute"), q.get("values", [])
            if m == "equal" and self._value(row, attr) not in vals:
                return False
            if m == "lessThan":
                v = self._value(row, attr)
                if v is None or datetime.fromisoformat(v) >= datetime.fromisoformat(vals[0]):
                    return False
        return True

    def _select(self, table, queries):
        rows = [r for r in self.tables.get(table, {}).values() if self._matches(r, queries)]
        rows.sort(key=lambda r: (r.createdat, r.id))
        limit, offset = 25, 0
        for raw in queries or []:
            q = _parse(raw)
            if q["method"] == "limit":
                limit = q["values"][0]
            if q["method"] == "offset":
                offset = q["values"][0]
        return rows, rows[offset: offset + limit]

    # ---- the TablesDB surface
    def list_rows(self, database_id, table_id, queries=None, **kw):
        all_rows, page = self._select(table_id, queries)
        return SimpleNamespace(rows=page, total=len(all_rows))

    def get_row(self, database_id, table_id, row_id, **kw):
        try:
            return self.tables[table_id][row_id]
        except KeyError:
            raise AppwriteException("Row not found", 404)

    def create_row(self, database_id, table_id, row_id, data, permissions=None, **kw):
        if row_id in self.tables.setdefault(table_id, {}):
            raise AppwriteException("exists", 409)
        self.seed(table_id, row_id, data, permissions=permissions)
        return self.tables[table_id][row_id]

    def create_rows(self, database_id, table_id, rows, **kw):
        for r in rows:
            r = dict(r)
            rid = r.pop("$id")
            perms = r.pop("$permissions", None)
            self.create_row(database_id, table_id, rid, r, perms)

    def update_row(self, database_id, table_id, row_id, data=None, **kw):
        row = self.get_row(database_id, table_id, row_id)
        row.data.update(data or {})
        row.updatedat = iso(datetime.now(timezone.utc))
        return row

    def delete_row(self, database_id, table_id, row_id, **kw):
        self.get_row(database_id, table_id, row_id)
        del self.tables[table_id][row_id]

    def delete_rows(self, database_id, table_id, queries=None, **kw):
        _, page = self._select(table_id, queries)
        for r in page:
            del self.tables[table_id][r.id]
        return SimpleNamespace(total=len(page), rows=page)
