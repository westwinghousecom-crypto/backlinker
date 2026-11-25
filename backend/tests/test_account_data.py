"""Account export and deletion, through real HTTP requests against an in-memory Appwrite."""
import json
from datetime import datetime, timezone

import pytest
from appwrite.exception import AppwriteException
from fastapi.testclient import TestClient

from app.core import auth, security
from app.core.auth import AuthUser
from app.core.config import get_settings
from app.features.account import data as account_data
from app.features.google import service as google_service
from fake_appwrite import FakeTablesDB

A = {"Authorization": "Bearer token-A"}
B = {"Authorization": "Bearer token-B"}
USERS = {"token-A": AuthUser("user-A", "a@example.com", token="token-A"), "token-B": AuthUser("user-B", "b@example.com", token="token-B")}
SECRET_BLOB = "gAAAAA-encrypted-refresh-token-DO-NOT-EXPORT"


@pytest.fixture
def db(monkeypatch):
    fake = FakeTablesDB()
    monkeypatch.setattr(account_data, "get_tables_db", lambda: fake)
    for uid in ("user-A", "user-B"):
        t = uid[-1].lower()
        fake.seed("urls", f"u-{t}1", {"user_id": uid, "url": f"https://{t}.example/1", "status": "completed", "batch_id": f"b{t}"}, permissions=[f'read("user:{uid}")'])
        fake.seed("urls", f"u-{t}2", {"user_id": uid, "url": f"https://{t}.example/2", "status": "pending", "batch_id": f"b{t}"})
        fake.seed("check_batches", f"cb-{t}", {"user_id": uid, "target": f"https://{t}-site.com", "total": 1})
        fake.seed("checks", f"c-{t}", {"user_id": uid, "batch_id": f"cb-{t}", "url": f"https://{t}.example/p", "result": '{"verdict":"eligible"}'})
        fake.seed("batch_sharing", f"bs-{t}", {"user_id": uid, "public_feed": True})
        fake.seed("google_connections", uid, {"user_id": uid, "google_email": f"{t}@gmail.com", "scopes": "webmasters.readonly",
                                              "status": "active", "selected_property": "sc-domain:example.com",
                                              "refresh_token_enc": SECRET_BLOB, "error_code": None})
        fake.seed("gsc_targets", f"t-{t}", {"user_id": uid, "url": f"https://{t}.example/g", "property": "sc-domain:example.com", "status": "pending"})
        fake.seed("gsc_history", f"h-{t}", {"user_id": uid, "target_id": f"t-{t}", "outcome": "success", "status": "indexed"})
        fake.seed("google_oauth_states", f"s-{t}", {"user_id": uid})
    return fake


@pytest.fixture
def removed(monkeypatch):
    calls = []

    async def fake_remove(user):
        calls.append(user.id)
        return "deleted"

    async def fake_disconnect(user_id):
        calls.append(f"disconnect:{user_id}")

    monkeypatch.setattr(account_data, "remove_user", fake_remove)
    monkeypatch.setattr(google_service, "disconnect", fake_disconnect)
    return calls


@pytest.fixture
def client(monkeypatch, db, removed):
    for k, v in {"WORKER_COUNT": "0", "CHECK_WORKER_COUNT": "0", "GSC_WORKER_COUNT": "0", "RATE_LIMIT_PER_MINUTE": "0",
                 "RETENTION_ENABLED": "false"}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    monkeypatch.setattr(auth, "_verify_sync", lambda token: USERS.get(token))
    auth._cache.clear()
    security._hits.clear()
    from app.main import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


# ------------------------------------------------------------------------------------------------ export

def test_export_contains_everything_the_customer_owns_and_nothing_else(client):
    r = client.get("/api/v1/account/export", headers=A)
    assert r.status_code == 200 and r.headers["content-type"] == "application/json"
    assert r.headers["content-disposition"].startswith('attachment; filename="quickindex-export-') and r.headers["cache-control"] == "no-store"
    body = r.json()
    assert body["account"] == {"id": "user-A", "email": "a@example.com"}
    assert {u["url"] for u in body["urls"]} == {"https://a.example/1", "https://a.example/2"}
    assert [c["id"] for c in body["check_batches"]] == ["cb-a"] and [c["id"] for c in body["checks"]] == ["c-a"]
    assert body["batch_sharing"][0]["public_feed"] is True
    assert body["google_tracked_urls"][0]["url"] == "https://a.example/g" and body["google_inspection_history"][0]["status"] == "indexed"
    assert body["_truncated"] is False
    assert "b.example" not in r.text and "b@gmail" not in r.text and "user-B" not in r.text  # never another customer's data


def test_export_never_includes_the_google_refresh_token_or_permissions(client):
    r = client.get("/api/v1/account/export", headers=A)
    conn = r.json()["google_connection"]
    assert conn["google_email"] == "a@gmail.com" and conn["scopes"] == "webmasters.readonly" and conn["selected_property"] == "sc-domain:example.com"
    assert "refresh_token_enc" not in conn and SECRET_BLOB not in r.text and "refresh_token" not in r.text
    assert "$permissions" not in r.text and "permissions" not in r.text


def test_each_customer_gets_only_their_own_export(client):
    a, b = client.get("/api/v1/account/export", headers=A).json(), client.get("/api/v1/account/export", headers=B).json()
    assert {u["url"] for u in b["urls"]} == {"https://b.example/1", "https://b.example/2"} and b["account"]["id"] == "user-B"
    assert not ({u["id"] for u in a["urls"]} & {u["id"] for u in b["urls"]})


def test_export_defends_in_depth_if_the_database_returns_another_customers_row(client, db, monkeypatch):
    original = db.list_rows

    def leaky(database_id, table_id, queries=None, **kw):
        res = original(database_id, table_id, queries=None)  # ignores the user filter, like a buggy query
        res.rows = res.rows[:100]
        return res

    monkeypatch.setattr(db, "list_rows", leaky)
    text = client.get("/api/v1/account/export", headers=A).text
    assert "b.example" not in text and "user-B" not in text and "a.example/1" in text


def test_export_requires_sign_in_and_is_limited_to_three_per_hour(client):
    assert client.get("/api/v1/account/export").status_code == 401
    assert [client.get("/api/v1/account/export", headers=A).status_code for _ in range(4)] == [200, 200, 200, 429]
    assert client.get("/api/v1/account/export", headers=B).status_code == 200  # the limit is per customer


def test_export_is_size_capped_and_says_so(client, db, monkeypatch):
    monkeypatch.setattr(account_data, "MAX_EXPORT_ROWS", 5)
    body = client.get("/api/v1/account/export", headers=A).json()
    assert body["_truncated"] is True
    assert sum(len(v) for k, v in body.items() if isinstance(v, list)) <= 5


def test_export_paginates_large_tables(client, db):
    for i in range(230):
        db.seed("urls", f"many-{i}", {"user_id": "user-A", "url": f"https://a.example/m{i}", "status": "completed"})
    assert len(client.get("/api/v1/account/export", headers=A).json()["urls"]) == 232


# ------------------------------------------------------------------------------------------------ deletion

def test_deletion_requires_typing_delete_exactly(client, db, removed):
    for body in ({}, {"confirm": ""}, {"confirm": "delete"}, {"confirm": "yes"}):
        assert client.request("DELETE", "/api/v1/account", json=body, headers=A).status_code in (400, 422), body
    assert db.count("urls") == 4 and removed == []  # nothing was touched


def test_deletion_requires_sign_in(client, db):
    assert client.request("DELETE", "/api/v1/account", json={"confirm": "DELETE"}).status_code == 401
    assert db.count("urls") == 4


def test_deletion_erases_every_row_the_customer_owns_and_only_theirs(client, db, removed):
    r = client.request("DELETE", "/api/v1/account", json={"confirm": "DELETE"}, headers=A)
    assert r.status_code == 204 and r.content == b""
    for table in ("urls", "check_batches", "checks", "batch_sharing", "google_connections", "gsc_targets", "gsc_history", "google_oauth_states"):
        assert db.tables[table] and {row.data["user_id"] for row in db.tables[table].values()} == {"user-B"}, table  # Bob untouched
    assert removed == ["disconnect:user-A", "user-A"]  # Google revoked first, the Appwrite user removed last


def test_the_account_removed_is_the_one_in_the_token_never_one_named_in_the_request(client, db, removed):
    r = client.request("DELETE", "/api/v1/account?user_id=user-B", json={"confirm": "DELETE", "user_id": "user-B", "id": "user-B"}, headers=A)
    assert r.status_code == 204
    assert "user-B" not in removed and db.count("urls") == 2 and all(u.data["user_id"] == "user-B" for u in db.tables["urls"].values())


def test_deleting_twice_is_fine_and_the_session_stops_working(client, db, removed):
    assert client.request("DELETE", "/api/v1/account", json={"confirm": "DELETE"}, headers=A).status_code == 204
    again = client.request("DELETE", "/api/v1/account", json={"confirm": "DELETE"}, headers=A)
    assert again.status_code == 204  # nothing left to delete, still succeeds (a real deleted user would get 401 from Appwrite)


def test_a_failure_part_way_can_simply_be_retried(client, db, removed, monkeypatch):
    calls = {"n": 0}
    original = account_data.remove_user

    async def flaky(user):
        calls["n"] += 1
        if calls["n"] == 1:
            raise AppwriteException("appwrite hiccup", 500)
        return await original(user)

    monkeypatch.setattr(account_data, "remove_user", flaky)
    monkeypatch.setattr(account_data, "_remove_user_sync", lambda uid, token: "deleted")
    first = client.request("DELETE", "/api/v1/account", json={"confirm": "DELETE"}, headers=A)
    assert first.status_code == 502 and "try again" in first.json()["detail"].lower()
    assert not any(r.data["user_id"] == "user-A" for r in db.tables["urls"].values())  # rows were already erased
    assert client.request("DELETE", "/api/v1/account", json={"confirm": "DELETE"}, headers=A).status_code == 204


def test_google_revocation_failure_does_not_block_deletion(client, db, monkeypatch):
    async def boom(user_id):
        raise RuntimeError("google unreachable")

    monkeypatch.setattr(google_service, "disconnect", boom)
    assert client.request("DELETE", "/api/v1/account", json={"confirm": "DELETE"}, headers=A).status_code == 204
    assert db.count("google_connections") == 1  # only Bob's remains


def test_deletion_is_rate_limited_per_customer(client, db):
    codes = [client.request("DELETE", "/api/v1/account", json={"confirm": "DELETE"}, headers=A).status_code for _ in range(6)]
    assert codes[:5] == [204] * 5 and codes[5] == 429


# ------------------------------------------------------------------------------------------------ removing the Appwrite user

def test_user_is_deleted_with_the_server_key_when_it_has_users_write(monkeypatch):
    seen = []

    class FakeUsers:
        def __init__(self, c): pass
        def delete(self, user_id): seen.append(("delete", user_id))

    monkeypatch.setattr(account_data, "Users", FakeUsers)
    assert account_data._remove_user_sync("user-A", "jwt") == "deleted" and seen == [("delete", "user-A")]


def test_already_deleted_user_counts_as_deleted(monkeypatch):
    class FakeUsers:
        def __init__(self, c): pass
        def delete(self, user_id): raise AppwriteException("not found", 404)

    monkeypatch.setattr(account_data, "Users", FakeUsers)
    assert account_data._remove_user_sync("user-A", "jwt") == "deleted"


@pytest.mark.parametrize("code", [401, 403])
def test_without_users_write_the_account_is_blocked_with_the_customers_own_session(monkeypatch, code):
    seen = {}

    class FakeUsers:
        def __init__(self, c): pass
        def delete(self, user_id): raise AppwriteException("missing scope: users.write", code)

    class FakeAccount:
        def __init__(self, c): seen["jwt"] = c._global_headers.get("x-appwrite-jwt")
        def update_status(self): seen["blocked"] = True

    monkeypatch.setattr(account_data, "Users", FakeUsers)
    monkeypatch.setattr(account_data, "Account", FakeAccount)
    assert account_data._remove_user_sync("user-A", "the-customers-jwt") == "blocked"
    assert seen == {"jwt": "the-customers-jwt", "blocked": True}


def test_other_appwrite_errors_are_not_swallowed(monkeypatch):
    class FakeUsers:
        def __init__(self, c): pass
        def delete(self, user_id): raise AppwriteException("server error", 500)

    monkeypatch.setattr(account_data, "Users", FakeUsers)
    with pytest.raises(AppwriteException):
        account_data._remove_user_sync("user-A", "jwt")
