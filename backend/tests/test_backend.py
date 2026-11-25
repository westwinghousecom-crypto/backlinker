import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core import security
from app.core.config import get_settings
from app.features.discovery import render
from app.features.submissions.schemas import SubmitRequest


def test_submit_request_dedupes_and_validates():
    r = SubmitRequest(urls=[" https://a.com/x ", "https://a.com/x", ""])
    assert r.urls == ["https://a.com/x"]
    with pytest.raises(ValidationError):
        SubmitRequest(urls=["not a url"])
    with pytest.raises(ValidationError):
        SubmitRequest(urls=[" "])


def test_rate_limiter_window():
    key = "t-window"
    assert all(security.check_rate_limit(key, 3, now=0.0 + i) for i in range(3))
    assert not security.check_rate_limit(key, 3, now=3.0)
    assert security.check_rate_limit(key, 3, now=61.0)


def test_render_escapes_xml():
    rows = [{"url": "https://a.com/?x=1&y=2", "updated_at": "2026-01-01T00:00:00Z"}]
    assert "&amp;y=2" in render.sitemap_xml(rows)
    assert "<rss" in render.rss_xml(rows, "t", "http://x")


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("INDEXNOW_KEY", "abc123")
    monkeypatch.setenv("WORKER_COUNT", "0")
    monkeypatch.setenv("CHECK_WORKER_COUNT", "0")
    get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()


def test_indexnow_key_and_robots(client):
    assert client.get("/abc123.txt").text == "abc123"
    assert client.get("/wrong.txt").status_code == 404
    robots = client.get("/robots.txt").text
    assert "Disallow: /api/" in robots and "Sitemap:" not in robots  # global feed is off by default
    assert client.get("/health").json() == {"status": "ok"}


def test_global_feed_is_private_by_default_and_opt_in(client, monkeypatch):
    # By default no public page lists every customer's URLs together.
    assert client.get("/sitemap.xml").status_code == 404
    assert client.get("/feed.xml").status_code == 404
    monkeypatch.setenv("PUBLIC_GLOBAL_FEED", "true")
    get_settings.cache_clear()
    assert "Sitemap:" in client.get("/robots.txt").text


def test_write_endpoints_require_sign_in(client):
    for method, path, body in [
        ("post", "/api/v1/submit", {"urls": ["https://a.com"]}),
        ("post", "/api/v1/submit-one", {"url": "https://a.com"}),
        ("post", "/api/v1/check", {"urls": ["https://a.com"]}),
        ("post", "/api/v1/check-batches", {"urls": ["https://a.com"]}),
        ("get", "/api/v1/check-batches", None),
        ("get", "/api/v1/check-batches/abc", None),
        ("get", "/api/v1/batches/abc", None),
        ("post", "/api/v1/check-batches/abc/checks/def/recheck", None),
        ("delete", "/api/v1/check-batches/abc", None),
    ]:
        r = getattr(client, method)(path, **({"json": body} if body is not None else {}))
        assert r.status_code == 401, (method, path, r.status_code)
        assert r.headers["www-authenticate"] == "Bearer"


def test_ping_payload_and_response_parsing():
    from app.features.discovery import pinger

    body = pinger.build_ping_payload("QuickIndex", "https://x.com/feed.xml").decode()
    assert "weblogUpdates.ping" in body and "https://x.com/feed.xml" in body
    ok = "<struct><member><name>flerror</name><value><boolean>0</boolean></value></member></struct>"
    bad = ok.replace("<boolean>0", "<boolean>1")
    assert pinger.ping_succeeded(200, ok)
    assert not pinger.ping_succeeded(200, bad)
    assert not pinger.ping_succeeded(500, ok)
    assert not pinger.ping_succeeded(200, "<fault></fault>")


@pytest.mark.asyncio
async def test_submit_urls_groups_by_host(monkeypatch):
    from app.features.indexing import indexer

    calls = []

    async def fake_submit_host(session, settings, host, urls, rotator):
        calls.append((host, sorted(urls)))
        return "completed" if host == "a.com" else None

    monkeypatch.setattr(indexer, "_submit_host", fake_submit_host)
    settings = get_settings()
    res = await indexer.submit_urls(
        None, settings.model_copy(update={"WAYBACK_SAVE": False}),
        ["https://a.com/1", "https://b.com/x", "https://a.com/2"],
    )
    assert sorted(calls) == [("a.com", ["https://a.com/1", "https://a.com/2"]), ("b.com", ["https://b.com/x"])]
    assert res == {"https://a.com/1": "completed", "https://a.com/2": "completed", "https://b.com/x": None}


def test_indexnow_status_mapping():
    from app.features.indexing.indexer import _outcome

    assert _outcome(200) == "completed"
    assert _outcome(202) == "submitted"
    assert _outcome(429) is None and _outcome(403) is None and _outcome(422) is None


def test_feed_advertises_websub_hub_and_self():
    rows = [{"url": "https://a.com/1", "updated_at": "2026-01-01T00:00:00Z"}]
    xml = render.rss_xml(rows, "t", "http://x", "http://x/feed.xml", "https://hub.example/")
    assert 'rel="hub" href="https://hub.example/"' in xml
    assert 'rel="self"' in xml and 'xmlns:atom="http://www.w3.org/2005/Atom"' in xml
    assert "rel=\"hub\"" not in render.rss_xml(rows, "t", "http://x")
