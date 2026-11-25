"""GET /api/v1/batches: a customer's own recent submission batches, from the database, newest first."""
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core import auth
from app.core.auth import AuthUser
from app.core.config import get_settings
from app.features.submissions import repository as srepo

A = {"Authorization": "Bearer token-A"}
B = {"Authorization": "Bearer token-B"}
USERS = {"token-A": AuthUser("user-A", "a@example.com"), "token-B": AuthUser("user-B", "b@example.com")}


class FakeUrls:
    """Just enough of TablesDB.list_rows to run the real repository code: equal(), orderDesc($createdAt) and limit()."""

    def __init__(self):
        self.rows: list[SimpleNamespace] = []
        self.calls = 0

    def add(self, user, batch, n, created):
        for i in range(n):
            self.rows.append(SimpleNamespace(id=f"{batch}-{i}", createdat=f"{created}.{i:03d}+00:00",
                                             data={"user_id": user, "batch_id": batch, "url": f"https://x.example/{batch}/{i}", "status": "pending", "attempts": 0}))

    def list_rows(self, database_id, table_id, queries):
        self.calls += 1
        rows, limit, desc = list(self.rows), 25, False
        for raw in queries:
            q = json.loads(raw)  # the SDK builds queries as JSON strings
            if q["method"] == "equal":
                rows = [r for r in rows if r.data.get(q["attribute"]) in q["values"]]
            elif q["method"] == "limit":
                limit = int(q["values"][0])
            elif q["method"] == "orderDesc":
                desc = True
        if desc:
            rows.sort(key=lambda r: r.createdat, reverse=True)
        return SimpleNamespace(rows=rows[:limit], total=len(rows))


@pytest.fixture
def fake(monkeypatch):
    f = FakeUrls()
    monkeypatch.setattr(srepo, "get_tables_db", lambda: SimpleNamespace(list_rows=f.list_rows))
    return f


@pytest.fixture
def client(monkeypatch, fake):
    for k, v in {"WORKER_COUNT": "0", "CHECK_WORKER_COUNT": "0", "GSC_WORKER_COUNT": "0", "RATE_LIMIT_PER_MINUTE": "0"}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    monkeypatch.setattr(auth, "_verify_sync", lambda token: USERS.get(token))
    auth._cache.clear()
    from app.main import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def test_lists_my_batches_newest_first_with_exact_totals(client, fake):
    fake.add("user-A", "old", 2, "2026-11-09T10:00:00")
    fake.add("user-A", "mid", 5, "2026-11-10T10:00:00")
    fake.add("user-A", "new", 3, "2026-11-11T10:00:00")
    body = client.get("/api/v1/batches", headers=A).json()
    assert [(b["batch_id"], b["total"]) for b in body] == [("new", 3), ("mid", 5), ("old", 2)]
    assert body[0]["created_at"].startswith("2026-11-11")
    assert fake.calls == 1  # one database request for a normal customer


def test_a_customer_never_sees_another_customers_batches(client, fake):
    fake.add("user-A", "alice-1", 2, "2026-11-11T10:00:00")
    fake.add("user-B", "bob-1", 4, "2026-11-11T11:00:00")
    assert [b["batch_id"] for b in client.get("/api/v1/batches", headers=A).json()] == ["alice-1"]
    assert [b["batch_id"] for b in client.get("/api/v1/batches", headers=B).json()] == ["bob-1"]
    # a user_id in the query string changes nothing: the owner is the verified sign-in
    assert [b["batch_id"] for b in client.get("/api/v1/batches?user_id=user-A", headers=B).json()] == ["bob-1"]


def test_requires_sign_in(client):
    assert client.get("/api/v1/batches").status_code == 401


def test_empty_for_a_new_customer(client, fake):
    fake.add("user-B", "bob-1", 1, "2026-11-11T11:00:00")
    assert client.get("/api/v1/batches", headers=A).json() == []


def test_a_huge_batch_does_not_hide_older_batches_or_show_a_wrong_total(client, fake):
    fake.add("user-A", "older", 4, "2026-11-10T10:00:00")
    fake.add("user-A", "huge", 250, "2026-11-11T10:00:00")  # more rows than the 100-row sample
    body = client.get("/api/v1/batches", headers=A).json()
    totals = {b["batch_id"]: b["total"] for b in body}
    assert totals["huge"] == 250  # exact, via a per-batch count (the sample alone would say 100)
    assert [b["batch_id"] for b in body][0] == "huge"


def test_only_the_eight_newest_batches_are_returned(client, fake):
    for i in range(12):
        fake.add("user-A", f"b{i:02d}", 1, f"2026-11-{i + 1:02d}T10:00:00")
    body = client.get("/api/v1/batches", headers=A).json()
    assert len(body) == 8 and body[0]["batch_id"] == "b11" and body[-1]["batch_id"] == "b04"


def test_the_batch_status_route_still_works_next_to_the_list_route(client, fake, monkeypatch):
    from app.features.submissions import service

    async def status(user_id, batch_id):
        raise service.BatchNotFound(batch_id)

    monkeypatch.setattr(service, "get_batch_status", status)
    assert client.get("/api/v1/batches/some-id", headers=A).status_code == 404
