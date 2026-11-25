"""Per-batch feeds are private by default; the owner can opt in to a public feed. Tested over real HTTP with in-memory fakes."""
import pytest
from fastapi.testclient import TestClient

from app.core import auth, security
from app.core.auth import AuthUser
from app.core.config import get_settings
from app.features.discovery import repository as feed_repo
from app.features.discovery import sharing
from app.features.submissions import repository as srepo

A = {"Authorization": "Bearer token-A"}
B = {"Authorization": "Bearer token-B"}
USERS = {"token-A": AuthUser("user-A", "a@example.com"), "token-B": AuthUser("user-B", "b@example.com")}
AMP_URL = "https://a-site.example/page?x=1&y=2"
B_SECRET_URL = "https://b-secret.example/private-page"


class FakeDb:
    def __init__(self):
        self.urls: dict[str, dict] = {}
        self.public: dict[str, bool] = {}


@pytest.fixture
def db(monkeypatch):
    d = FakeDb()

    async def create_url_rows(rows):
        for r in rows:
            r = dict(r)
            rid = r.pop("$id")
            r.pop("$permissions", None)
            d.urls[rid] = {"id": rid, **r}
        return len(rows), []

    async def list_batch(batch_id, user_id, max_rows=1000):
        return [dict(u) for u in d.urls.values() if u["batch_id"] == batch_id and u["user_id"] == user_id]

    async def count_queued(user_id):
        return 0

    async def batch_exists(batch_id, user_id):
        return any(u["batch_id"] == batch_id and u["user_id"] == user_id for u in d.urls.values())

    async def is_public(batch_id):
        return d.public.get(batch_id, False)

    async def set_public(batch_id, user_id, public):
        d.public[batch_id] = public

    async def list_published(max_rows, batch_id=None):
        rows = [u for u in d.urls.values() if u["status"] != "failed"] if batch_id else \
            [u for u in d.urls.values() if u["status"] in ("completed", "submitted")]
        if batch_id:
            rows = [u for u in rows if u["batch_id"] == batch_id]
        return [{"url": u["url"], "updated_at": "2026-01-01T00:00:00Z"} for u in rows][:max_rows]

    monkeypatch.setattr(srepo, "create_url_rows", create_url_rows)
    monkeypatch.setattr(srepo, "list_batch", list_batch)
    monkeypatch.setattr(srepo, "count_queued", count_queued)
    monkeypatch.setattr(srepo, "batch_exists", batch_exists)
    monkeypatch.setattr(sharing, "is_public", is_public)
    monkeypatch.setattr(sharing, "set_public", set_public)
    monkeypatch.setattr(feed_repo, "list_published", list_published)
    return d


@pytest.fixture
def client(monkeypatch, db):
    for k, v in dict(WORKER_COUNT=0, CHECK_WORKER_COUNT=0, GSC_WORKER_COUNT=0, RATE_LIMIT_PER_MINUTE=0).items():
        monkeypatch.setenv(k, str(v))
    get_settings.cache_clear()
    monkeypatch.setattr(auth, "_verify_sync", lambda token: USERS.get(token))
    auth._cache.clear()
    security._hits.clear()
    from app.main import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def make_batch(client, db, headers, url=AMP_URL):
    r = client.post("/api/v1/submit", json={"urls": [url]}, headers=headers)
    assert r.status_code == 200, r.text
    bid = r.json()["batch_id"]
    for row in db.urls.values():
        if row["batch_id"] == bid:
            row["status"] = "completed"
    return bid


# ------------------------------------------------------------------------------ private by default

def test_public_feed_and_sitemap_are_404_by_default(client, db):
    bid = make_batch(client, db, A)
    for path in ("feed.xml", "sitemap.xml"):
        r = client.get(f"/batches/{bid}/{path}")
        assert r.status_code == 404
        assert AMP_URL not in r.text
        # identical to a batch that does not exist: private batches cannot be told apart
        missing = client.get(f"/batches/does-not-exist/{path}")
        assert (missing.status_code, missing.text) == (r.status_code, r.text)


def test_owner_can_read_own_feed_and_sitemap_when_signed_in(client, db):
    bid = make_batch(client, db, A)
    feed = client.get(f"/api/v1/batches/{bid}/feed.xml", headers=A)
    assert feed.status_code == 200 and "rss" in feed.headers["content-type"]
    assert feed.headers["cache-control"] == "private, no-store"
    assert "https://a-site.example/page?x=1&amp;y=2" in feed.text and "&y=2" not in feed.text.replace("&amp;", "")
    sitemap = client.get(f"/api/v1/batches/{bid}/sitemap.xml", headers=A)
    assert sitemap.status_code == 200 and "xml" in sitemap.headers["content-type"]
    assert sitemap.headers["cache-control"] == "private, no-store"
    assert "https://a-site.example/page?x=1&amp;y=2" in sitemap.text


def test_sharing_state_defaults_to_private(client, db):
    bid = make_batch(client, db, A)
    r = client.get(f"/api/v1/batches/{bid}/sharing", headers=A)
    assert r.status_code == 200 and r.json() == {"public_feed": False, "public_url": None}


# ------------------------------------------------------------------------------ cross-customer isolation

def test_user_b_cannot_use_user_a_feed_or_sharing(client, db):
    bid = make_batch(client, db, A)
    assert client.get(f"/api/v1/batches/{bid}/feed.xml", headers=B).status_code == 404
    assert client.get(f"/api/v1/batches/{bid}/sitemap.xml", headers=B).status_code == 404
    assert client.get(f"/api/v1/batches/{bid}/sharing", headers=B).status_code == 404
    attempt = client.put(f"/api/v1/batches/{bid}/sharing", json={"public_feed": True}, headers=B)
    assert attempt.status_code == 404
    assert db.public.get(bid, False) is False  # B's attempt changed nothing
    assert client.get(f"/batches/{bid}/feed.xml").status_code == 404
    for r in (client.get(f"/api/v1/batches/{bid}/feed.xml", headers=B), attempt):
        assert AMP_URL not in r.text
    # a nonexistent batch looks the same to B
    assert client.get("/api/v1/batches/nope/feed.xml", headers=B).json() == \
        client.get(f"/api/v1/batches/{bid}/feed.xml", headers=B).json()


def test_owner_endpoints_require_sign_in(client, db):
    bid = make_batch(client, db, A)
    assert client.get(f"/api/v1/batches/{bid}/feed.xml").status_code == 401
    assert client.get(f"/api/v1/batches/{bid}/sitemap.xml").status_code == 401
    assert client.get(f"/api/v1/batches/{bid}/sharing").status_code == 401
    assert client.put(f"/api/v1/batches/{bid}/sharing", json={"public_feed": True}).status_code == 401
    assert client.get(f"/api/v1/batches/{bid}/feed.xml", headers={"Authorization": "Bearer bogus"}).status_code == 401
    assert db.public.get(bid, False) is False


# ------------------------------------------------------------------------------ explicit opt-in

def test_opt_in_makes_the_public_feed_available_and_opt_out_removes_it(client, db):
    bid = make_batch(client, db, A)
    on = client.put(f"/api/v1/batches/{bid}/sharing", json={"public_feed": True}, headers=A)
    assert on.status_code == 200
    base = get_settings().PUBLIC_BASE_URL.rstrip("/")
    assert on.json() == {"public_feed": True, "public_url": f"{base}/batches/{bid}/feed.xml"}
    assert client.get(f"/api/v1/batches/{bid}/sharing", headers=A).json()["public_feed"] is True

    feed = client.get(f"/batches/{bid}/feed.xml")  # no credentials
    assert feed.status_code == 200 and "rss" in feed.headers["content-type"]
    assert 'rel="hub"' in feed.text and 'rel="self"' in feed.text and f"{base}/batches/{bid}/feed.xml" in feed.text
    assert "https://a-site.example/page?x=1&amp;y=2" in feed.text
    sitemap = client.get(f"/batches/{bid}/sitemap.xml")
    assert sitemap.status_code == 200 and "https://a-site.example/page?x=1&amp;y=2" in sitemap.text

    off = client.put(f"/api/v1/batches/{bid}/sharing", json={"public_feed": False}, headers=A)
    assert off.status_code == 200 and off.json() == {"public_feed": False, "public_url": None}
    assert client.get(f"/batches/{bid}/feed.xml").status_code == 404
    assert client.get(f"/batches/{bid}/sitemap.xml").status_code == 404
    assert client.get(f"/api/v1/batches/{bid}/feed.xml", headers=A).status_code == 200  # owner still has it


@pytest.mark.parametrize("body", [{"public_feed": "maybe"}, {"public_feed": None}, {"public_feed": [1]}, {"public_feed": 5},
                                  {}, {"other": True}])
def test_non_boolean_sharing_body_is_rejected(client, db, body):
    bid = make_batch(client, db, A)
    assert client.put(f"/api/v1/batches/{bid}/sharing", json=body, headers=A).status_code == 422
    assert db.public.get(bid, False) is False


def test_public_feed_leaks_nothing_about_other_batches(client, db):
    a_batch = make_batch(client, db, A)
    b_batch = make_batch(client, db, B, url=B_SECRET_URL)
    client.put(f"/api/v1/batches/{a_batch}/sharing", json={"public_feed": True}, headers=A)

    public = client.get(f"/batches/{a_batch}/feed.xml")
    assert public.status_code == 200
    assert AMP_URL.replace("&", "&amp;") in public.text
    assert "b-secret.example" not in public.text and "b-secret" not in client.get(f"/batches/{a_batch}/sitemap.xml").text
    assert client.get(f"/batches/{b_batch}/feed.xml").status_code == 404  # B never opted in
    assert client.get(f"/batches/{b_batch}/sitemap.xml").status_code == 404


def test_global_feeds_stay_disabled_even_when_a_batch_is_public(client, db):
    bid = make_batch(client, db, A)
    client.put(f"/api/v1/batches/{bid}/sharing", json={"public_feed": True}, headers=A)
    assert get_settings().PUBLIC_GLOBAL_FEED is False
    assert client.get("/sitemap.xml").status_code == 404
    assert client.get("/feed.xml").status_code == 404
    robots = client.get("/robots.txt").text
    assert "Sitemap:" not in robots and "/sitemap.xml" not in robots
    assert client.get(f"/batches/{bid}/feed.xml").status_code == 200  # the per-batch opt-in still works


def test_sharing_lookup_failure_counts_as_private(monkeypatch):
    """If the opt-in lookup errors out, the feed must stay hidden (fail closed)."""
    import asyncio

    def boom(batch_id):
        raise RuntimeError("database down")

    monkeypatch.setattr(sharing, "_is_public_sync", boom)
    # undo the fixture-free state: call the real is_public (db fixture not used in this test)
    assert asyncio.run(sharing.is_public("any-batch")) is False
