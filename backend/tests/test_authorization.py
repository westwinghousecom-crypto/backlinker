"""Authentication and cross-customer isolation, tested through real HTTP requests.

Only two things are faked: the Appwrite database (an in-memory dict that, like Appwrite, knows nothing about
who is asking) and Appwrite's "who owns this token" lookup. Everything else (token parsing, the auth
dependency, routers, services) is the real code, so these tests prove the API itself keeps customers apart.
"""
import pytest
from fastapi.testclient import TestClient

from app.core import auth
from app.core.auth import AuthUser, UpstreamError
from app.core.config import get_settings
from app.features.diagnostics import repository as drepo
from app.features.diagnostics.scanner import UrlCheck
from app.features.submissions import repository as srepo

A = {"Authorization": "Bearer token-A"}
B = {"Authorization": "Bearer token-B"}
USERS = {"token-A": AuthUser("user-A", "a@example.com"), "token-B": AuthUser("user-B", "b@example.com")}


class FakeDb:
    def __init__(self):
        self.batches: dict[str, dict] = {}
        self.checks: dict[str, dict] = {}
        self.urls: dict[str, dict] = {}
        self.permissions: dict[str, list] = {}


@pytest.fixture
def db(monkeypatch):
    d = FakeDb()

    # ---- check batches
    async def create_batch(batch_id, user_id, target, total):
        d.batches[batch_id] = {"id": batch_id, "user_id": user_id, "target": target, "total": total, "created_at": "2026-01-01T00:00:00Z"}

    async def get_batch(batch_id):
        return dict(d.batches[batch_id]) if batch_id in d.batches else None

    async def create_checks(rows):
        for r in rows:
            r = dict(r)
            cid = r.pop("$id")
            d.permissions[cid] = r.pop("$permissions")
            d.checks[cid] = {"id": cid, **r}
        return len(rows)

    async def list_checks(batch_id, max_rows=1000):
        return sorted((dict(c) for c in d.checks.values() if c["batch_id"] == batch_id), key=lambda c: c["position"])

    async def count_checks(batch_id, status=None):
        return sum(c["batch_id"] == batch_id and (status is None or c["status"] == status) for c in d.checks.values())

    async def count_queued(user_id):
        return sum(c["user_id"] == user_id and c["status"] in ("pending", "processing") for c in d.checks.values())

    async def get_check(cid):
        return dict(d.checks[cid])

    async def update_check(cid, data):
        d.checks[cid].update(data)
        return dict(d.checks[cid])

    async def delete_checks(batch_id):
        for cid in [k for k, c in d.checks.items() if c["batch_id"] == batch_id]:
            del d.checks[cid]

    async def delete_batch(batch_id):
        d.batches.pop(batch_id, None)

    async def list_batches(user_id, limit):
        return [dict(b) for b in d.batches.values() if b["user_id"] == user_id][:limit]

    async def set_public_report(batch_id, public):
        d.batches[batch_id]["public_report"] = public

    for name, fn in dict(create_batch=create_batch, get_batch=get_batch, create_checks=create_checks, list_checks=list_checks,
                         count_checks=count_checks, count_queued=count_queued, get_check=get_check, update_check=update_check,
                         delete_checks=delete_checks, delete_batch=delete_batch, list_batches=list_batches,
                         set_public_report=set_public_report).items():
        monkeypatch.setattr(drepo, name, fn)

    # ---- submissions
    async def create_url_rows(rows):
        for r in rows:
            r = dict(r)
            rid = r.pop("$id")
            d.permissions[rid] = r.pop("$permissions")
            d.urls[rid] = {"id": rid, **r}
        return len(rows), []

    async def s_list_batch(batch_id, user_id, max_rows=1000):
        return [dict(u) for u in d.urls.values() if u["batch_id"] == batch_id and u["user_id"] == user_id]

    async def s_count_queued(user_id):
        return sum(u["user_id"] == user_id and u["status"] in ("pending", "processing") for u in d.urls.values())

    monkeypatch.setattr(srepo, "create_url_rows", create_url_rows)
    monkeypatch.setattr(srepo, "list_batch", s_list_batch)
    monkeypatch.setattr(srepo, "count_queued", s_count_queued)
    return d


@pytest.fixture
def verify_calls(monkeypatch):
    calls: list[str] = []

    def fake_verify(token):
        calls.append(token)
        return USERS.get(token)

    monkeypatch.setattr(auth, "_verify_sync", fake_verify)
    auth._cache.clear()
    return calls


@pytest.fixture
def client(monkeypatch, db, verify_calls):
    monkeypatch.setenv("WORKER_COUNT", "0")
    monkeypatch.setenv("CHECK_WORKER_COUNT", "0")
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "0")
    get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def make_check_batch(client, headers, urls=("https://one.example/", "https://two.example/")):
    r = client.post("/api/v1/check-batches", json={"urls": list(urls), "target": "https://mysite.com"}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["batch_id"]


# ------------------------------------------------------------------------------ authentication

def test_missing_malformed_and_invalid_tokens_are_rejected(client):
    assert client.get("/api/v1/check-batches").status_code == 401
    for header in ["", "Bearer", "Bearer ", "Basic abc", "token-A", "Bearer " + "x" * 5000, "Bearer not-a-real-token"]:
        r = client.get("/api/v1/check-batches", headers={"Authorization": header})
        assert r.status_code == 401, header
        assert r.headers["www-authenticate"] == "Bearer"


def test_valid_token_is_accepted_and_verification_is_cached(client, verify_calls):
    for _ in range(5):
        assert client.get("/api/v1/check-batches", headers=A).status_code == 200
    assert verify_calls == ["token-A"]  # polling does not hit Appwrite on every request


def test_unavailable_sign_in_service_is_503_not_401(client, monkeypatch):
    def boom(token):
        raise UpstreamError("appwrite down")

    monkeypatch.setattr(auth, "_verify_sync", boom)
    assert client.get("/api/v1/check-batches", headers=A).status_code == 503


def test_a_user_id_sent_by_the_browser_is_ignored(client, db):
    """B claims to be A in the body and the query string. Rows are still owned by B."""
    r = client.post(
        "/api/v1/check-batches?user_id=user-A",
        json={"urls": ["https://x.example/"], "user_id": "user-A", "owner": "user-A"},
        headers=B,
    )
    assert r.status_code == 200
    batch = db.batches[r.json()["batch_id"]]
    assert batch["user_id"] == "user-B"
    assert all(c["user_id"] == "user-B" for c in db.checks.values())

    r = client.post("/api/v1/submit", json={"urls": ["https://y.example/"], "user_id": "user-A"}, headers=B)
    assert r.status_code == 200
    assert all(u["user_id"] == "user-B" for u in db.urls.values())

    assert client.get("/api/v1/check-batches?user_id=user-A", headers=B).json()[0]["batch_id"] in db.batches
    assert all(db.batches[h["batch_id"]]["user_id"] == "user-B" for h in client.get("/api/v1/check-batches?user_id=user-A", headers=B).json())


def test_rows_are_readable_only_by_their_owner_in_appwrite(client, db):
    bid = make_check_batch(client, A)
    assert {tuple(p) for p in db.permissions.values()} == {('read("user:user-A")',)}
    client.post("/api/v1/submit", json={"urls": ["https://z.example/"]}, headers=B)
    assert ('read("user:user-B")',) in {tuple(p) for p in db.permissions.values()}
    assert bid in db.batches


# ------------------------------------------------------------------------------ User A vs User B

def test_user_b_cannot_read_user_a_batch_or_results(client):
    bid = make_check_batch(client, A)
    assert client.get(f"/api/v1/check-batches/{bid}", headers=A).status_code == 200
    r = client.get(f"/api/v1/check-batches/{bid}", headers=B)
    assert r.status_code == 404 and r.json() == {"detail": "Batch not found"}  # indistinguishable from "does not exist"
    assert client.get("/api/v1/check-batches/does-not-exist", headers=B).json() == r.json()


def test_history_lists_only_your_own_batches(client):
    a1 = make_check_batch(client, A)
    a2 = make_check_batch(client, A)
    b1 = make_check_batch(client, B)
    assert {h["batch_id"] for h in client.get("/api/v1/check-batches", headers=A).json()} == {a1, a2}
    assert {h["batch_id"] for h in client.get("/api/v1/check-batches", headers=B).json()} == {b1}


def test_user_b_cannot_export_user_a_data(client):
    """CSV export is built in the browser from the batch endpoint's response, so B has nothing to export."""
    bid = make_check_batch(client, A)
    assert client.get(f"/api/v1/check-batches/{bid}", headers=B).status_code == 404
    assert "one.example" in client.get(f"/api/v1/check-batches/{bid}", headers=A).text
    assert "one.example" not in client.get(f"/api/v1/check-batches/{bid}", headers=B).text


def test_user_b_cannot_recheck_user_a_url(client, db):
    bid = make_check_batch(client, A)
    check_id = client.get(f"/api/v1/check-batches/{bid}", headers=A).json()["items"][0]["id"]
    db.checks[check_id].update(status="done", verdict="eligible", result="{}")

    assert client.post(f"/api/v1/check-batches/{bid}/checks/{check_id}/recheck", headers=B).status_code == 404
    assert db.checks[check_id]["status"] == "done" and db.checks[check_id]["verdict"] == "eligible"  # untouched
    assert client.post(f"/api/v1/check-batches/{bid}/checks/{check_id}/recheck", headers=A).status_code == 202
    assert db.checks[check_id]["status"] == "pending"


def test_forged_check_id_from_another_batch_is_refused(client, db):
    """B owns a batch, but passes A's check id inside B's own batch path."""
    a_batch = make_check_batch(client, A)
    b_batch = make_check_batch(client, B)
    a_check = client.get(f"/api/v1/check-batches/{a_batch}", headers=A).json()["items"][0]["id"]
    db.checks[a_check].update(status="done", verdict="eligible")
    r = client.post(f"/api/v1/check-batches/{b_batch}/checks/{a_check}/recheck", headers=B)
    assert r.status_code == 404 and db.checks[a_check]["status"] == "done"


def test_user_b_cannot_delete_user_a_batch(client, db):
    bid = make_check_batch(client, A)
    assert client.delete(f"/api/v1/check-batches/{bid}", headers=B).status_code == 404
    assert bid in db.batches and sum(c["batch_id"] == bid for c in db.checks.values()) == 2
    assert client.delete(f"/api/v1/check-batches/{bid}", headers=A).status_code == 204
    assert bid not in db.batches and not any(c["batch_id"] == bid for c in db.checks.values())
    assert client.get(f"/api/v1/check-batches/{bid}", headers=A).status_code == 404


def test_user_b_cannot_see_user_a_submission_status(client):
    r = client.post("/api/v1/submit", json={"urls": ["https://secret.example/page"]}, headers=A)
    bid = r.json()["batch_id"]
    ok = client.get(f"/api/v1/batches/{bid}", headers=A)
    assert ok.status_code == 200 and ok.json()["urls"][0]["url"] == "https://secret.example/page"
    denied = client.get(f"/api/v1/batches/{bid}", headers=B)
    assert denied.status_code == 404 and "secret.example" not in denied.text


def test_other_customers_rows_are_dropped_even_if_the_database_layer_returned_them(client, db, monkeypatch):
    """Defence in depth: simulate a buggy/bypassed repository filter."""
    b_batch = make_check_batch(client, B, urls=("https://b.example/",))
    a_batch = make_check_batch(client, A, urls=("https://a-secret.example/",))
    original = drepo.list_checks

    async def leaky(batch_id, max_rows=1000):
        return await original(b_batch) + await original(a_batch)  # includes A's rows

    monkeypatch.setattr(drepo, "list_checks", leaky)
    body = client.get(f"/api/v1/check-batches/{b_batch}", headers=B).text
    assert "b.example" in body and "a-secret.example" not in body

    from app.features.submissions import service as ssvc

    r = client.post("/api/v1/submit", json={"urls": ["https://q.example/"]}, headers=A)
    sbid = r.json()["batch_id"]

    async def leaky_status(batch_id, user_id, max_rows=1000):
        return [dict(u) for u in db.urls.values()]  # every customer's rows

    monkeypatch.setattr(srepo, "list_batch", leaky_status)
    status = await_status(ssvc, "user-B", sbid)
    assert status == "not-found"


def await_status(ssvc, user_id, batch_id):
    import asyncio

    try:
        asyncio.run(ssvc.get_batch_status(user_id, batch_id))
    except ssvc.BatchNotFound:
        return "not-found"
    return "found"


# ------------------------------------------------------------------------------ limits

def test_queue_limit_is_per_customer(client, monkeypatch):
    monkeypatch.setenv("MAX_QUEUED_PER_USER", "3")
    get_settings.cache_clear()
    assert client.post("/api/v1/submit", json={"urls": [f"https://a.example/{i}" for i in range(3)]}, headers=A).status_code == 200
    r = client.post("/api/v1/submit", json={"urls": ["https://a.example/more"]}, headers=A)
    assert r.status_code == 429 and "at most 3" in r.json()["detail"]
    assert client.post("/api/v1/check-batches", json={"urls": ["https://a.example/1"] * 1}, headers=A).status_code == 200
    # B's queue is independent of A's
    assert client.post("/api/v1/submit", json={"urls": ["https://b.example/1"]}, headers=B).status_code == 200


def test_rate_limit_is_per_customer(client, monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "2")
    get_settings.cache_clear()
    from app.core import security

    security._hits.clear()
    codes_a = [client.post("/api/v1/submit-one", json={"url": "https://a.example/"}, headers=A).status_code for _ in range(3)]
    assert codes_a == [200, 200, 429]
    assert client.post("/api/v1/submit-one", json={"url": "https://b.example/"}, headers=B).status_code == 200


# ------------------------------------------------------------ "I searched Google myself" note (customer-reported only)

def _first_check(client, headers=A):
    bid = make_check_batch(client, headers)
    return bid, client.get(f"/api/v1/check-batches/{bid}", headers=headers).json()["items"][0]["id"]


def _mark(client, bid, cid, result, headers=A):
    return client.put(f"/api/v1/check-batches/{bid}/checks/{cid}/manual-google", json={"result": result}, headers=headers)


def test_owner_can_record_what_they_saw_on_google_and_it_comes_back_labelled(client, db):
    bid, cid = _first_check(client)
    r = _mark(client, bid, cid, "appears")
    assert r.status_code == 200 and r.json()["manual_google"] == "appears" and r.json()["manual_google_at"]
    item = client.get(f"/api/v1/check-batches/{bid}", headers=A).json()["items"][0]
    assert item["manual_google"] == "appears" and item["manual_google_at"]
    assert _mark(client, bid, cid, "not_found").json()["manual_google"] == "not_found"  # latest note wins
    assert _mark(client, bid, cid, "clear").json() == {"manual_google": None, "manual_google_at": None}
    assert client.get(f"/api/v1/check-batches/{bid}", headers=A).json()["items"][0]["manual_google"] is None


def test_the_note_never_changes_a_verdict_or_the_google_index_status(client, db):
    bid, cid = _first_check(client)
    db.checks[cid].update(status="done", verdict="eligible", result=UrlCheck(url="https://one.example/", status=200, robots_allowed=True).model_dump_json())
    before = client.get(f"/api/v1/check-batches/{bid}", headers=A).json()
    _mark(client, bid, cid, "appears")
    after = client.get(f"/api/v1/check-batches/{bid}", headers=A).json()
    assert after["summary"] == before["summary"]
    assert after["items"][0]["result"] == before["items"][0]["result"]
    assert after["items"][0]["result"]["google_index_status"] == "unknown"


def test_user_b_cannot_write_user_a_google_note(client, db):
    bid, cid = _first_check(client)
    assert _mark(client, bid, cid, "appears", headers=B).status_code == 404
    assert not db.checks[cid].get("manual_google")  # untouched
    b_batch = make_check_batch(client, B)
    assert _mark(client, b_batch, cid, "appears", headers=B).status_code == 404  # forged id inside B's own batch
    assert not db.checks[cid].get("manual_google")


def test_google_note_rejects_other_values_and_needs_sign_in(client, db):
    bid, cid = _first_check(client)
    for bad in ("indexed", "Confirmed Indexed", "", None, 1):
        assert client.put(f"/api/v1/check-batches/{bid}/checks/{cid}/manual-google", json={"result": bad}, headers=A).status_code == 422
    assert client.put(f"/api/v1/check-batches/{bid}/checks/{cid}/manual-google", json={"result": "appears"}).status_code == 401
    assert not db.checks[cid].get("manual_google")


def test_google_note_survives_a_recheck(client, db):
    bid, cid = _first_check(client)
    db.checks[cid].update(status="done", verdict="eligible", result="{}")
    _mark(client, bid, cid, "not_found")
    assert client.post(f"/api/v1/check-batches/{bid}/checks/{cid}/recheck", headers=A).status_code == 202
    assert db.checks[cid]["manual_google"] == "not_found"


# ------------------------------------------------------------ shareable client report (opt-in, no sign-in to view)

def _sharing(client, bid, headers=A):
    return client.get(f"/api/v1/check-batches/{bid}/sharing", headers=headers)


def _set_sharing(client, bid, public, headers=A):
    return client.put(f"/api/v1/check-batches/{bid}/sharing", json={"public_report": public}, headers=headers)


def test_owner_can_turn_sharing_on_and_off_and_gets_a_link_back(client, db):
    bid = make_check_batch(client, A)
    off = _sharing(client, bid).json()
    assert off == {"public_report": False, "public_url": None}

    on = _set_sharing(client, bid, True)
    assert on.status_code == 200
    body = on.json()
    assert body["public_report"] is True and body["public_url"] is not None and bid in body["public_url"]
    assert _sharing(client, bid).json() == body  # GET agrees with the PUT that just ran

    off_again = _set_sharing(client, bid, False).json()
    assert off_again == {"public_report": False, "public_url": None}


def test_user_b_cannot_read_or_write_user_a_sharing_state(client, db):
    bid = make_check_batch(client, A)
    assert _sharing(client, bid, headers=B).status_code == 404
    assert _set_sharing(client, bid, True, headers=B).status_code == 404
    assert db.batches[bid].get("public_report") is not True  # untouched
    assert _sharing(client, bid, headers=A).json()["public_report"] is False


def test_the_public_report_works_with_no_sign_in_at_all_once_shared(client, db):
    bid = make_check_batch(client, A)
    assert client.get(f"/api/v1/check-batches/{bid}/public").status_code == 404  # not shared yet, and no auth sent
    _set_sharing(client, bid, True)
    r = client.get(f"/api/v1/check-batches/{bid}/public")  # no Authorization header at all
    assert r.status_code == 200
    body = r.json()
    assert body["batch_id"] == bid and len(body["items"]) == 2


def test_a_private_batch_and_a_nonexistent_one_give_the_identical_404(client, db):
    bid = make_check_batch(client, A)  # never shared
    private = client.get(f"/api/v1/check-batches/{bid}/public")
    missing = client.get("/api/v1/check-batches/does-not-exist/public")
    assert private.status_code == missing.status_code == 404
    assert private.json() == missing.json()  # a private batch must be indistinguishable from one that never existed


def test_the_public_report_strips_the_owners_private_google_search_note(client, db):
    bid, cid = _first_check(client)
    db.checks[cid].update(status="done", verdict="eligible", result="{}")
    _mark(client, bid, cid, "appears")
    assert client.get(f"/api/v1/check-batches/{bid}", headers=A).json()["items"][0]["manual_google"] == "appears"
    _set_sharing(client, bid, True)
    public_item = client.get(f"/api/v1/check-batches/{bid}/public").json()["items"][0]
    assert public_item["manual_google"] is None and public_item["manual_google_at"] is None


def test_the_public_report_never_contains_a_user_id_anywhere_in_the_raw_json(client, db):
    bid = make_check_batch(client, A)
    _set_sharing(client, bid, True)
    raw = client.get(f"/api/v1/check-batches/{bid}/public").text
    assert "user-A" not in raw and "user_id" not in raw
