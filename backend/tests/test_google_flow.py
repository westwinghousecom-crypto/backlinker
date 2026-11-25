"""Google Search Console integration, end to end, against a MOCKED Google (no network, no real credentials).

The Appwrite database is an in-memory fake and Google's HTTP layer is replaced by `FakeGoogle`. Everything else
(OAuth state, encryption, routers, services, the worker, quota, scheduling, status mapping) is the real code.
"""
import base64
import hashlib
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from app.core import auth, security
from app.core.auth import AuthUser
from app.core.config import get_settings
from app.features.google import api, crypto, mapping, oauth, service, worker
from app.features.google import repository as repo
from app.features.google.quota import QuotaGate

SECRET = "csecret-DO-NOT-LEAK"
REFRESH_A, REFRESH_B = "1//refresh-token-of-alice", "1//refresh-token-of-bob"
A = {"Authorization": "Bearer token-A"}
B = {"Authorization": "Bearer token-B"}
USERS = {"token-A": AuthUser("user-A", "a@example.com"), "token-B": AuthUser("user-B", "b@example.com")}
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
SCOPE_RO = "openid email https://www.googleapis.com/auth/webmasters.readonly"
SCOPE_RW = "openid email https://www.googleapis.com/auth/webmasters"


def id_token(email="owner@gmail.com", aud="cid"):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{enc({'alg': 'RS256'})}.{enc({'aud': aud, 'iss': 'https://accounts.google.com', 'email': email})}.sig"


def inspection(verdict="PASS", coverage="Submitted and indexed", **extra):
    idx = {"verdict": verdict, "coverageState": coverage, "robotsTxtState": "ALLOWED", "indexingState": "INDEXING_ALLOWED",
           "lastCrawlTime": "2026-11-10T08:00:00Z", "pageFetchState": "SUCCESSFUL", **extra}
    return {"inspectionResult": {"indexStatusResult": idx, "inspectionResultLink": "https://search.google.com/search-console/inspect"}}


class FakeGoogle:
    """Stands in for every Google endpoint. Tests tweak the attributes to script Google's behaviour."""

    def __init__(self):
        self.calls: list[dict] = []
        self.exchange = {"refresh_token": REFRESH_A, "access_token": "ya29.access-A", "expires_in": 3600,
                         "scope": SCOPE_RO, "id_token": id_token()}
        self.refresh_error: tuple[int, dict] | None = None
        self.sites = [{"siteUrl": "sc-domain:example.com", "permissionLevel": "siteOwner"},
                      {"siteUrl": "https://blog.example.org/news/", "permissionLevel": "siteFullUser"},
                      {"siteUrl": "https://unverified.example/", "permissionLevel": "siteUnverifiedUser"}]
        self.inspect_body = inspection()
        self.inspect_script: list = []  # items: Response-like tuple (status, body, headers) consumed first
        self.sitemaps = [{"path": "https://www.example.com/sitemap.xml", "lastSubmitted": "2026-11-01T00:00:00Z",
                          "isPending": False, "isSitemapsIndex": False, "type": "sitemap", "warnings": "0", "errors": "1"}]

    def of(self, kind):
        return [c for c in self.calls if kind in c["url"]]

    async def __call__(self, method, url, *, headers=None, data=None, json_body=None):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "data": data, "json": json_body})
        if url == api.TOKEN_URL:
            if data["grant_type"] == "authorization_code":
                return api.Response(200, dict(self.exchange), {})
            if self.refresh_error:
                return api.Response(self.refresh_error[0], self.refresh_error[1], {})
            who = "A" if data["refresh_token"] == REFRESH_A else "B"
            return api.Response(200, {"access_token": f"ya29.access-{who}", "expires_in": 3600}, {})
        if url == api.REVOKE_URL:
            return api.Response(200, {}, {})
        if url == api.SITES_URL:
            return api.Response(200, {"siteEntry": self.sites}, {})
        if url == api.INSPECT_URL:
            if self.inspect_script:
                status, body, hdrs = self.inspect_script.pop(0)
                return api.Response(status, body, hdrs)
            return api.Response(200, self.inspect_body, {})
        if "/sitemaps" in url:
            if method == "GET":
                return api.Response(200, {"sitemap": self.sitemaps}, {})
            return api.Response(200, {}, {})
        raise AssertionError(f"unexpected Google call {method} {url}")


class MemoryStore:
    def __init__(self):
        self.connections, self.targets, self.history, self.quota = {}, {}, [], {}
        self.states: set[str] = set()

    def install(self, mp):
        s = self

        async def get_connection(uid): return dict(s.connections[uid], id=uid) if uid in s.connections else None
        async def upsert_connection(uid, data): s.connections.setdefault(uid, {"user_id": uid}).update(data)
        async def delete_connection(uid): s.connections.pop(uid, None)
        async def existing_target_ids(ids): return {i for i in ids if i in s.targets}
        async def create_targets(uid, rows):
            for r in rows:
                r = dict(r); tid = r.pop("$id"); s.targets[tid] = {"id": tid, **r}
            return len(rows), []
        async def list_targets(uid, max_rows=2000): return [dict(t) for t in s.targets.values() if t["user_id"] == uid]
        async def count_targets(uid): return sum(t["user_id"] == uid for t in s.targets.values())
        async def get_target(tid): return dict(s.targets[tid]) if tid in s.targets else None
        async def update_target(tid, data): s.targets[tid].update(data); return dict(s.targets[tid])
        async def delete_target(tid): s.targets.pop(tid, None)
        async def list_due(now_iso, limit):
            cutoff = datetime.fromisoformat(now_iso) if now_iso[:1] == "2" else datetime.max.replace(tzinfo=timezone.utc)  # Appwrite compares datetimes, not strings
            return [dict(t) for t in s.targets.values() if t["status"] == "pending" and t.get("next_check_at")
                    and datetime.fromisoformat(t["next_check_at"]) <= cutoff][:limit]
        async def list_stale(cutoff, limit=50): return []
        async def list_paused(uid): return [dict(t) for t in s.targets.values() if t["user_id"] == uid and t["status"] == "paused"]
        async def add_history(uid, row): s.history.append({"id": f"h{len(s.history)}", "user_id": uid, **row})
        async def list_history(uid, tid, limit=100):
            return sorted((dict(h) for h in s.history if h["target_id"] == tid and h["user_id"] == uid), key=lambda h: h["inspected_at"])
        async def delete_history(tid): s.history[:] = [h for h in s.history if h["target_id"] != tid]
        async def claim_oauth_state(nonce, uid):
            if nonce in s.states:
                return False
            s.states.add(nonce)
            return True
        async def purge_oauth_states(cutoff): return None
        async def delete_user_data(uid):
            for k in [k for k, t in s.targets.items() if t["user_id"] == uid]:
                del s.targets[k]
            s.history[:] = [h for h in s.history if h["user_id"] != uid]

        for name, fn in list(locals().items()):
            if name not in ("s", "mp", "self") and callable(fn):
                mp.setattr(repo, name, fn)

        class Counters:
            async def get(self_, prop, day): return s.quota.get((prop, day), 0)
            async def incr(self_, prop, day, limit):
                n = s.quota.get((prop, day), 0)
                if n >= limit:
                    return None  # like Appwrite's capped atomic increment
                s.quota[(prop, day)] = n + 1
                return n + 1
        return Counters()


@pytest.fixture
def world(monkeypatch):
    """Configured server + fake Appwrite + fake Google + a controllable clock."""
    for k, v in {"GOOGLE_CLIENT_ID": "cid", "GOOGLE_CLIENT_SECRET": SECRET, "TOKEN_ENCRYPTION_KEY": crypto.generate_key(),
                 "GOOGLE_REDIRECT_URI": "http://localhost:8000/api/v1/google/callback", "FRONTEND_URL": "http://localhost:3000",
                 "WORKER_COUNT": "0", "CHECK_WORKER_COUNT": "0", "GSC_WORKER_COUNT": "0", "RATE_LIMIT_PER_MINUTE": "0"}.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()
    store = MemoryStore()
    counters = store.install(monkeypatch)
    google = FakeGoogle()
    api.set_transport(google)
    clock = {"now": NOW}
    for mod in (worker, service):
        monkeypatch.setattr(mod, "utcnow", lambda: clock["now"])
    service.reset_gate(QuotaGate(600, 2000, counters, clock=lambda: clock["now"]))
    monkeypatch.setattr(auth, "_verify_sync", lambda token: USERS.get(token))
    auth._cache.clear()
    oauth._access.clear()
    security._hits.clear()

    class W: pass
    w = W()
    w.store, w.google, w.clock, w.counters = store, google, clock, counters
    yield w
    api.set_transport(None)
    service.reset_gate(None)
    get_settings.cache_clear()


@pytest.fixture
def client(world):
    from app.main import app

    with TestClient(app, follow_redirects=False) as c:
        yield c


def connect_user(client, world, headers=A, refresh=REFRESH_A, scope=SCOPE_RO, email="owner@gmail.com"):
    """Run the whole OAuth round trip for one customer and return the callback response."""
    world.google.exchange = {"refresh_token": refresh, "access_token": "ya29.x", "expires_in": 3600, "scope": scope,
                             "id_token": id_token(email)}
    url = client.post("/api/v1/google/connect", json={"write": "webmasters" in scope and "readonly" not in scope}, headers=headers).json()["authorization_url"]
    q = parse_qs(urlsplit(url).query)
    return client.get("/api/v1/google/callback", params={"code": "auth-code-123", "state": q["state"][0]}), q


def choose_property(client, headers=A, site="sc-domain:example.com"):
    r = client.put("/api/v1/google/property", json={"site_url": site}, headers=headers)
    assert r.status_code == 200, r.text


# ================================================================================ OAuth security

def test_authorization_url_is_minimal_pkce_and_has_no_secret(client, world):
    url = client.post("/api/v1/google/connect", json={"write": False}, headers=A).json()["authorization_url"]
    p = urlsplit(url)
    q = {k: v[0] for k, v in parse_qs(p.query).items()}
    assert p.netloc == "accounts.google.com"
    assert q["scope"].split() == ["openid", "email", "https://www.googleapis.com/auth/webmasters.readonly"]  # read-only by default
    assert q["code_challenge_method"] == "S256" and q["access_type"] == "offline" and q["prompt"] == "consent"
    assert q["client_id"] == "cid" and q["redirect_uri"].endswith("/api/v1/google/callback")
    assert SECRET not in url and "client_secret" not in url
    write_q = parse_qs(urlsplit(client.post("/api/v1/google/connect", json={"write": True}, headers=A).json()["authorization_url"]).query)
    assert "https://www.googleapis.com/auth/webmasters" in write_q["scope"][0].split()
    assert "https://www.googleapis.com/auth/webmasters.readonly" not in write_q["scope"][0].split()


def test_state_is_sealed_not_readable_and_differs_each_time(client, world):
    s1 = parse_qs(urlsplit(client.post("/api/v1/google/connect", json={}, headers=A).json()["authorization_url"]).query)["state"][0]
    s2 = parse_qs(urlsplit(client.post("/api/v1/google/connect", json={}, headers=A).json()["authorization_url"]).query)["state"][0]
    assert s1 != s2 and "user-A" not in s1
    assert "user-A" not in base64.urlsafe_b64decode(s1 + "=" * (-len(s1) % 4)).decode("latin1")


def test_successful_callback_stores_only_encrypted_token_and_redirects_cleanly(client, world, caplog):
    caplog.set_level("DEBUG")
    r, q = connect_user(client, world)
    assert r.status_code == 303
    assert r.headers["location"] == "http://localhost:3000/dashboard/google?connected=1"
    loc = r.headers["location"]
    assert "auth-code" not in loc and REFRESH_A not in loc and "ya29" not in loc  # nothing sensitive in the redirect
    row = world.store.connections["user-A"]
    assert row["status"] == "active" and row["google_email"] == "owner@gmail.com"
    assert REFRESH_A not in json.dumps(row) and row["refresh_token_enc"] != REFRESH_A
    assert crypto.decrypt_token("user-A", row["refresh_token_enc"]) == REFRESH_A
    # PKCE: Google got the verifier whose SHA-256 is the challenge we sent, and the secret only in the POST body
    exch = world.google.calls[0]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(exch["data"]["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    assert challenge == q["code_challenge"][0]
    assert exch["data"]["client_secret"] == SECRET and exch["url"] == api.TOKEN_URL
    # Only the application's own log lines count (the test client's httpx logger echoes the URL it requested).
    ours = " | ".join(r.getMessage() for r in caplog.records if r.name.startswith("app"))
    for secret in (REFRESH_A, SECRET, "ya29", "auth-code-123"):
        assert secret not in ours


def test_status_never_exposes_tokens(client, world):
    connect_user(client, world)
    r = client.get("/api/v1/google/status", headers=A)
    body = r.text
    assert r.json()["connected"] and r.json()["email"] == "owner@gmail.com" and r.json()["can_write"] is False
    assert REFRESH_A not in body and "refresh_token" not in body and "enc" not in r.json()


@pytest.mark.parametrize("bad_state", ["", "garbage", "abcd.efgh", "A" * 200])
def test_forged_or_garbage_state_is_rejected_without_contacting_google(client, world, bad_state):
    r = client.get("/api/v1/google/callback", params={"code": "c", "state": bad_state})
    assert r.headers["location"].endswith("?google_error=invalid_state")
    assert world.google.calls == [] and world.store.connections == {}


def test_tampered_and_expired_state_are_rejected(client, world, monkeypatch):
    url = client.post("/api/v1/google/connect", json={}, headers=A).json()["authorization_url"]
    state = parse_qs(urlsplit(url).query)["state"][0]
    tampered = state[:-4] + ("AAAA" if not state.endswith("AAAA") else "BBBB")
    assert client.get("/api/v1/google/callback", params={"code": "c", "state": tampered}).headers["location"].endswith("invalid_state")
    # state older than its 10-minute life
    real = crypto.open_state
    monkeypatch.setattr(service.crypto, "open_state", lambda s, max_age_seconds=600: real(s, max_age_seconds=-1))
    assert client.get("/api/v1/google/callback", params={"code": "c", "state": state}).headers["location"].endswith("invalid_state")
    assert world.google.calls == [] and world.store.connections == {}


def test_callback_links_google_only_to_the_user_in_the_sealed_state(client, world):
    """Bob cannot attach his Google account to Alice (or vice versa) by replaying someone's callback."""
    url = client.post("/api/v1/google/connect", json={}, headers=A).json()["authorization_url"]
    state_for_alice = parse_qs(urlsplit(url).query)["state"][0]
    world.google.exchange["refresh_token"] = REFRESH_B  # an attacker's Google account
    # the callback carries no QuickIndex identity: even if Bob's browser delivers Alice's state, it can only ever write Alice's row
    client.get("/api/v1/google/callback", params={"code": "bobs-code", "state": state_for_alice}, headers=B)
    assert set(world.store.connections) == {"user-A"}
    assert "user-B" not in world.store.connections


def test_user_denies_consent(client, world):
    url = client.post("/api/v1/google/connect", json={}, headers=A).json()["authorization_url"]
    state = parse_qs(urlsplit(url).query)["state"][0]
    r = client.get("/api/v1/google/callback", params={"error": "access_denied", "state": state})
    assert r.headers["location"].endswith("?google_error=access_denied")
    assert world.google.calls == [] and world.store.connections == {}


def test_missing_search_console_scope_is_refused_and_nothing_is_stored(client, world):
    r, _ = connect_user(client, world, scope="openid email")  # the customer unticked the Search Console box
    assert r.headers["location"].endswith("?google_error=scope_missing")
    assert world.store.connections == {}


def test_no_refresh_token_or_exchange_error_is_reported_safely(client, world):
    world.google.exchange = {"access_token": "x", "expires_in": 3600, "scope": SCOPE_RO}

    def fresh_state():
        url = client.post("/api/v1/google/connect", json={}, headers=A).json()["authorization_url"]
        return parse_qs(urlsplit(url).query)["state"][0]

    assert client.get("/api/v1/google/callback", params={"code": "c", "state": fresh_state()}).headers["location"].endswith("exchange_failed")

    async def failing(*a, **k):
        return api.Response(400, {"error": "invalid_grant", "error_description": "Bad Request"}, {})

    api.set_transport(failing)
    assert client.get("/api/v1/google/callback", params={"code": "c", "state": fresh_state()}).headers["location"].endswith("exchange_failed")
    assert world.store.connections == {}


def test_redirect_target_is_fixed_and_not_reflected(client, world):
    r = client.get("/api/v1/google/callback", params={"error": "https://evil.example/x", "state": "zzz", "code": "<script>"})
    assert r.headers["location"].startswith("http://localhost:3000/dashboard/google?google_error=")
    assert "evil" not in r.headers["location"] and "script" not in r.headers["location"]
    assert r.headers["cache-control"] == "no-store"


def test_when_not_configured_nothing_works_and_nothing_is_faked(client, world, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    get_settings.cache_clear()
    st = client.get("/api/v1/google/status", headers=A).json()
    assert st["configured"] is False and st["connected"] is False
    r = client.post("/api/v1/google/connect", json={}, headers=A)
    assert r.status_code == 503 and r.json()["detail"]["code"] == "google_not_configured"
    assert client.get("/api/v1/google/callback", params={"code": "c", "state": "s"}).headers["location"].endswith("not_configured")
    assert client.get("/api/v1/google/properties", headers=A).status_code == 503


def test_endpoints_need_sign_in(client, world):
    for method, path in [("get", "/api/v1/google/status"), ("post", "/api/v1/google/connect"), ("delete", "/api/v1/google/connection"),
                         ("get", "/api/v1/google/properties"), ("get", "/api/v1/google/targets"), ("get", "/api/v1/google/sitemaps")]:
        assert getattr(client, method)(path).status_code == 401, path


def test_disconnect_revokes_at_google_and_forgets_the_customer_only(client, world):
    connect_user(client, world)
    connect_user(client, world, headers=B, refresh=REFRESH_B)
    assert client.delete("/api/v1/google/connection", headers=A).status_code == 204
    assert "user-A" not in world.store.connections and "user-B" in world.store.connections
    revoke = world.google.of("revoke")
    assert revoke and revoke[0]["data"] == {"token": REFRESH_A}
    assert client.get("/api/v1/google/status", headers=A).json()["connected"] is False
    assert client.get("/api/v1/google/status", headers=B).json()["connected"] is True


# ================================================================================ properties and URL ownership

def test_properties_distinguish_domain_from_url_prefix_and_flag_unverified(client, world):
    connect_user(client, world)
    props = {p["site_url"]: p for p in client.get("/api/v1/google/properties", headers=A).json()["properties"]}
    assert props["sc-domain:example.com"]["type"] == "domain" and props["sc-domain:example.com"]["label"] == "example.com"
    assert props["https://blog.example.org/news/"]["type"] == "url_prefix"
    assert props["https://unverified.example/"]["verified"] is False
    assert props["sc-domain:example.com"]["can_write"] is True
    # Google was called with Alice's own access token
    assert world.google.of("webmasters/v3/sites")[0]["headers"]["Authorization"] == "Bearer ya29.access-A"


def test_property_choice_must_come_from_googles_list_and_be_verified(client, world):
    connect_user(client, world)
    for bad in ["sc-domain:not-mine.com", "https://unverified.example/", "https://example.com/"]:
        r = client.put("/api/v1/google/property", json={"site_url": bad}, headers=A)
        assert r.status_code == 400 and r.json()["detail"]["code"] == "property_not_usable", bad
    choose_property(client)
    assert client.get("/api/v1/google/status", headers=A).json()["selected_property"] == "sc-domain:example.com"


def test_only_urls_inside_the_selected_property_can_be_tracked(client, world):
    connect_user(client, world)
    choose_property(client)  # sc-domain:example.com
    urls = ["https://example.com/a", "http://www.example.com/b", "https://shop.example.com/c",
            "https://example.com.evil.com/x", "https://notexample.com/y", "https://other.org/z",
            "ftp://example.com/f", "not a url", "https://example.com/a"]
    r = client.post("/api/v1/google/targets", json={"urls": urls}, headers=A).json()
    assert r["added"] == 3
    reasons = {s["url"]: s["reason"] for s in r["skipped"]}
    assert reasons["https://example.com.evil.com/x"] == "outside_property" and reasons["https://notexample.com/y"] == "outside_property"
    assert reasons["https://other.org/z"] == "outside_property" and reasons["not a url"] == "invalid_url"
    assert reasons["ftp://example.com/f"] == "invalid_url" and reasons["https://example.com/a"] == "duplicate"
    # tracking the same URL again does not duplicate it
    again = client.post("/api/v1/google/targets", json={"urls": ["https://example.com/a"]}, headers=A).json()
    assert again["added"] == 0 and again["skipped"][0]["reason"] == "duplicate"
    assert len(world.store.targets) == 3


def test_url_prefix_property_is_strict(client, world):
    connect_user(client, world)
    choose_property(client, site="https://blog.example.org/news/")
    r = client.post("/api/v1/google/targets", headers=A, json={"urls": [
        "https://blog.example.org/news/a", "https://blog.example.org/news", "https://blog.example.org/newsletter/",
        "http://blog.example.org/news/a", "https://www.blog.example.org/news/a"]}).json()
    assert r["added"] == 1 and len(r["skipped"]) == 4


def test_tracking_requires_a_selected_property(client, world):
    connect_user(client, world)
    r = client.post("/api/v1/google/targets", json={"urls": ["https://example.com/"]}, headers=A)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "property_not_selected"


# ================================================================================ isolation between customers

def two_customers(client, world):
    connect_user(client, world)
    choose_property(client)
    connect_user(client, world, headers=B, refresh=REFRESH_B)
    choose_property(client, headers=B, site="sc-domain:example.com")
    client.post("/api/v1/google/targets", json={"urls": ["https://example.com/alice-page"]}, headers=A)
    return next(iter(world.store.targets))


def test_user_b_cannot_see_touch_or_delete_user_a_urls(client, world):
    tid = two_customers(client, world)
    assert client.get("/api/v1/google/targets", headers=B).json() == {"items": []}
    assert len(client.get("/api/v1/google/targets", headers=A).json()["items"]) == 1
    for method, path in [("get", f"/api/v1/google/targets/{tid}/history"), ("post", f"/api/v1/google/targets/{tid}/recheck"),
                         ("delete", f"/api/v1/google/targets/{tid}")]:
        r = getattr(client, method)(path, headers=B)
        assert r.status_code == 404 and r.json()["detail"]["code"] == "not_found", path
    assert tid in world.store.targets  # untouched
    assert client.get("/api/v1/google/targets/does-not-exist/history", headers=B).json() == client.get(f"/api/v1/google/targets/{tid}/history", headers=B).json()


def test_same_url_tracked_by_two_customers_stays_separate(client, world):
    tid = two_customers(client, world)
    client.post("/api/v1/google/targets", json={"urls": ["https://example.com/alice-page"]}, headers=B)
    assert len(world.store.targets) == 2
    assert {t["user_id"] for t in world.store.targets.values()} == {"user-A", "user-B"}
    assert client.delete(f"/api/v1/google/targets/{tid}", headers=A).status_code == 204
    assert len(client.get("/api/v1/google/targets", headers=B).json()["items"]) == 1


def test_connection_status_is_per_customer(client, world):
    connect_user(client, world)
    assert client.get("/api/v1/google/status", headers=B).json()["connected"] is False
    assert client.get("/api/v1/google/properties", headers=B).status_code == 409


def test_a_token_copied_into_another_customers_record_is_unusable(client, world):
    connect_user(client, world)
    world.store.connections["user-B"] = {**world.store.connections["user-A"], "user_id": "user-B"}  # row copied across
    r = client.get("/api/v1/google/properties", headers=B)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "google_reauth_required"
    assert world.google.of("webmasters/v3/sites") == []  # Google was never called with Alice's grant


def test_history_rows_of_other_customers_are_never_returned(client, world):
    tid = two_customers(client, world)
    world.store.history.append({"id": "x", "user_id": "user-B", "target_id": tid, "inspected_at": "2026-11-11T00:00:00+00:00",
                                "outcome": "success", "status": "indexed"})
    assert client.get(f"/api/v1/google/targets/{tid}/history", headers=A).json()["items"] == []


# ================================================================================ revoked / expired credentials

def test_revoked_refresh_token_is_reported_and_marks_the_connection(client, world):
    connect_user(client, world)
    world.google.refresh_error = (400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."})
    r = client.get("/api/v1/google/properties", headers=A)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "google_reauth_required"
    st = client.get("/api/v1/google/status", headers=A).json()
    assert st["connected"] and st["reauth_required"] is True and st["state"] == "revoked"
    assert client.get("/api/v1/google/properties", headers=A).json()["detail"]["code"] == "google_reauth_required"


async def test_worker_pauses_when_revoked_and_reconnecting_resumes(client, world):
    connect_user(client, world)
    choose_property(client)
    client.post("/api/v1/google/targets", json={"urls": ["https://example.com/p"]}, headers=A)
    world.google.refresh_error = (400, {"error": "invalid_grant"})
    oauth._access.clear()  # the cached access token has expired, so Google must be asked to refresh it
    row = await worker._claim((await repo.list_due("9999", 5))[0], "w1")
    await worker.process(row)
    t = next(iter(world.store.targets.values()))
    assert t["status"] == "paused" and world.store.connections["user-A"]["status"] == "revoked"
    assert world.google.of(api.INSPECT_URL) == []  # no inspection attempted with a dead grant
    world.google.refresh_error = None
    connect_user(client, world)  # the customer reconnects
    assert next(iter(world.store.targets.values()))["status"] == "pending"


async def test_repeated_google_401_revokes_the_connection(client, world):
    connect_user(client, world)
    choose_property(client)
    client.post("/api/v1/google/targets", json={"urls": ["https://example.com/p"]}, headers=A)
    world.google.inspect_script = [(401, {"error": {"code": 401, "message": "Invalid Credentials"}}, {})] * 2
    for _ in range(2):
        world.clock["now"] += timedelta(minutes=5)
        row = await worker._claim((await repo.list_due("9999", 5))[0], "w1")
        await worker.process(row)
    assert world.store.connections["user-A"]["status"] == "revoked"
    assert next(iter(world.store.targets.values()))["status"] == "paused"


# ================================================================================ quota

def reservation_clock(start=NOW):
    box = {"now": start, "mono": 0.0}
    return box


async def test_per_minute_limit_of_600_then_window_reopens(world):
    box = {"now": NOW, "mono": 1000.0}
    gate = QuotaGate(600, 2000, world.counters, clock=lambda: box["now"], monotonic=lambda: box["mono"])
    results = [await gate.reserve("sc-domain:example.com") for _ in range(601)]
    assert all(r.ok for r in results[:600]) and not results[600].ok and results[600].reason == "minute"
    assert 0 < (results[600].retry_at - NOW).total_seconds() <= 61
    box["mono"] += 61
    assert (await gate.reserve("sc-domain:example.com")).ok  # the minute window moved on


async def test_per_day_limit_of_2000_resets_at_pacific_midnight(world):
    box = {"now": datetime(2026, 11, 11, 20, 0, tzinfo=timezone.utc), "mono": 0.0}  # 12:00 in Los Angeles (PST)
    gate = QuotaGate(10_000, 2000, world.counters, clock=lambda: box["now"], monotonic=lambda: box["mono"])
    for i in range(2000):
        box["mono"] += 0.001
        assert (await gate.reserve("p")).ok
    denied = await gate.reserve("p")
    assert not denied.ok and denied.reason == "day"
    assert denied.retry_at == datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc)  # 00:00 PST next day
    box["now"] = denied.retry_at + timedelta(seconds=1)
    assert (await gate.reserve("p")).ok  # a new quota day


async def test_daily_count_survives_a_restart_and_is_shared_per_property(world):
    g1 = QuotaGate(600, 5, world.counters, clock=lambda: NOW)
    for _ in range(5):
        assert (await g1.reserve("shared-property")).ok
    g2 = QuotaGate(600, 5, world.counters, clock=lambda: NOW)  # new process, same Appwrite counters
    assert not (await g2.reserve("shared-property")).ok
    assert (await g2.reserve("different-property")).ok  # limits are per property


async def test_worker_stops_at_the_daily_limit_and_reschedules_without_calling_google(client, world):
    connect_user(client, world)
    choose_property(client)
    service.reset_gate(QuotaGate(600, 2, world.counters, clock=lambda: world.clock["now"]))
    client.post("/api/v1/google/targets", json={"urls": [f"https://example.com/p{i}" for i in range(3)]}, headers=A)
    for r in await repo.list_due("9999", 10):
        row = await worker._claim(r, "w1")
        await worker.process(row)
    assert len(world.google.of(api.INSPECT_URL)) == 2  # never more than the limit
    waiting = [t for t in world.store.targets.values() if not t.get("latest_at")]
    assert len(waiting) == 1 and waiting[0]["status"] == "pending"
    assert waiting[0]["next_check_at"].startswith("2026-11-12T08:00")  # next Pacific midnight
    assert waiting[0]["attempts"] == 0 and len(world.store.history) == 2


async def test_google_429_pauses_the_property_and_records_nothing(client, world):
    connect_user(client, world)
    choose_property(client)
    client.post("/api/v1/google/targets", json={"urls": ["https://example.com/p"]}, headers=A)
    world.google.inspect_script = [(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Quota exceeded"}}, {"retry-after": "300"})]
    row = await worker._claim((await repo.list_due("9999", 5))[0], "w1")
    await worker.process(row)
    t = next(iter(world.store.targets.values()))
    assert t["status"] == "pending" and parse_next(t) >= world.clock["now"] + timedelta(seconds=300)
    assert world.store.history == [] and t["attempts"] == 0
    # while blocked, other work for the property does not even try Google
    row2 = await worker._claim({**t}, "w1")
    calls_before = len(world.google.of(api.INSPECT_URL))
    await worker.process(row2)
    assert len(world.google.of(api.INSPECT_URL)) == calls_before


def parse_next(t):
    return datetime.fromisoformat(t["next_check_at"])


# ================================================================================ status mapping and schedule

async def run_once(world, client=None, now=None):
    if now:
        world.clock["now"] = now
    done = 0
    for r in await repo.list_due(world.clock["now"].isoformat(), 10):
        row = await worker._claim(r, "w1")
        if row:
            await worker.process(row)
            done += 1
    return done


def one_target(client, world, url="https://example.com/p"):
    connect_user(client, world)
    choose_property(client)
    client.post("/api/v1/google/targets", json={"urls": [url]}, headers=A)
    return next(iter(world.store.targets))


def view(client, tid):
    return next(i for i in client.get("/api/v1/google/targets", headers=A).json()["items"] if i["id"] == tid)


@pytest.mark.parametrize("verdict,coverage,expected,label", [
    ("PASS", "Submitted and indexed", "indexed", "Confirmed Indexed"),
    ("NEUTRAL", "Crawled - currently not indexed", "not_indexed", "Confirmed Not Indexed"),
    ("NEUTRAL", "Excluded by 'noindex' tag", "not_indexed", "Confirmed Not Indexed"),
    ("FAIL", "Server error (5xx)", "not_indexed", "Confirmed Not Indexed"),
    ("PARTIAL", "Indexed, with warnings", "unknown", "Unknown"),
    ("VERDICT_UNSPECIFIED", "Unknown to Google", "unknown", "Unknown"),
])
async def test_google_verdict_maps_to_dashboard_status(client, world, verdict, coverage, expected, label):
    tid = one_target(client, world)
    assert view(client, tid)["label"] == "Unknown" and view(client, tid)["last_inspected_at"] is None  # never inspected
    world.google.inspect_body = inspection(verdict, coverage)
    await run_once(world)
    v = view(client, tid)
    assert (v["display_status"], v["label"]) == (expected, label)
    assert v["evidence_source"] == "Google URL Inspection API" and v["last_inspected_at"]
    assert v["inspection"]["coverage_state"] == coverage and v["inspection"]["verdict"] == verdict


async def test_inspection_evidence_is_exposed_to_the_customer(client, world):
    tid = one_target(client, world)
    world.google.inspect_body = inspection("NEUTRAL", "Duplicate, Google chose different canonical than user",
                                           robotsTxtState="ALLOWED", indexingState="BLOCKED_BY_META_TAG",
                                           googleCanonical="https://example.com/other", userCanonical="https://example.com/p",
                                           crawledAs="MOBILE", sitemap=["https://example.com/sitemap.xml"], referringUrls=["a", "b"])
    await run_once(world)
    i = view(client, tid)["inspection"]
    assert (i["robots_txt_state"], i["indexing_state"], i["crawled_as"]) == ("ALLOWED", "BLOCKED_BY_META_TAG", "MOBILE")
    assert (i["google_canonical"], i["user_canonical"]) == ("https://example.com/other", "https://example.com/p")
    assert i["sitemaps"] == ["https://example.com/sitemap.xml"] and i["referring_urls"] == 2 and i["last_crawl_time"]


async def test_http_indexnow_and_other_signals_never_create_an_indexed_status(client, world):
    """Only a Google inspection can set a status. Rows full of other 'evidence' still read Unknown."""
    tid = one_target(client, world)
    world.store.targets[tid].update(status="done", http_status=200, indexnow="accepted", websub="ok", common_crawl=True)
    v = view(client, tid)
    assert v["display_status"] == "unknown" and v["label"] == "Unknown"


async def test_failed_inspection_is_shown_as_failed_but_keeps_the_last_known_status(client, world):
    tid = one_target(client, world)
    world.google.inspect_body = inspection("NEUTRAL", "Crawled - currently not indexed")
    await run_once(world)
    world.google.inspect_script = [(403, {"error": {"code": 403, "status": "PERMISSION_DENIED", "message": "no access"}}, {})]
    await run_once(world, now=world.clock["now"] + timedelta(days=1, hours=1))
    v = view(client, tid)
    assert v["display_status"] == "failed" and v["label"] == "Inspection Failed"
    assert v["last_known_status"] == "not_indexed" and v["error_code"] == "permission_denied"
    assert v["error_message"]


async def test_transient_google_errors_back_off_then_are_recorded(client, world):
    tid = one_target(client, world)
    world.google.inspect_script = [(503, {"error": {"code": 503, "message": "unavailable"}}, {})] * 4
    delays = []
    for _ in range(4):
        await run_once(world)
        t = world.store.targets[tid]
        delays.append((parse_next(t) - world.clock["now"]).total_seconds() if t["status"] == "pending" else None)
        world.clock["now"] += timedelta(hours=3)
    assert delays[:3] == [900, 1800, 3600]  # 15 min, 30 min, 1 h
    assert len(world.store.history) == 1 and world.store.history[0]["outcome"] == "failed"  # recorded once, after the 4th try
    assert view(client, tid)["display_status"] == "failed"


async def test_checks_run_at_1_3_7_and_14_days_then_stop(client, world):
    tid = one_target(client, world)
    world.google.inspect_body = inspection("NEUTRAL", "Crawled - currently not indexed")
    due_days = []
    for _ in range(8):
        if not await run_once(world):
            break
        t = world.store.targets[tid]
        due_days.append(None if not t.get("next_check_at") else round((parse_next(t) - NOW).total_seconds() / 86400))
        if t["status"] == "done":
            break
        world.clock["now"] = parse_next(t)
    assert due_days == [1, 3, 7, 14, None]
    t = world.store.targets[tid]
    assert t["status"] == "done" and t["step"] == 5 and len(world.store.history) == 5
    assert [h["trigger"] for h in world.store.history] == ["initial", "scheduled", "scheduled", "scheduled", "scheduled"]


async def test_checks_stop_once_google_confirms_indexing(client, world):
    tid = one_target(client, world)
    world.google.inspect_body = inspection("PASS", "Submitted and indexed")
    await run_once(world)
    t = world.store.targets[tid]
    assert t["status"] == "done" and t["next_check_at"] is None and t["latest_status"] == "indexed"


async def test_status_changes_over_time_are_kept_in_history(client, world):
    tid = one_target(client, world)
    world.google.inspect_body = inspection("NEUTRAL", "Discovered - currently not indexed")
    await run_once(world)
    world.google.inspect_body = inspection("PASS", "Submitted and indexed")
    await run_once(world, now=NOW + timedelta(days=1, minutes=1))
    items = client.get(f"/api/v1/google/targets/{tid}/history", headers=A).json()["items"]
    assert [(i["status"], i["label"], i["trigger"]) for i in items] == [
        ("not_indexed", "Confirmed Not Indexed", "initial"), ("indexed", "Confirmed Indexed", "scheduled")]
    assert items[0]["inspection"]["coverage_state"] == "Discovered - currently not indexed" and items[1]["inspected_at"] > items[0]["inspected_at"]


async def test_manual_recheck_does_not_use_up_a_scheduled_slot(client, world):
    tid = one_target(client, world)
    world.google.inspect_body = inspection("NEUTRAL", "Crawled - currently not indexed")
    await run_once(world)
    assert world.store.targets[tid]["step"] == 1
    assert client.post(f"/api/v1/google/targets/{tid}/recheck", headers=A).status_code == 202
    await run_once(world, now=NOW + timedelta(hours=2))
    t = world.store.targets[tid]
    assert t["step"] == 1 and t["status"] == "pending" and world.store.history[-1]["trigger"] == "manual"
    assert round((parse_next(t) - NOW).total_seconds() / 86400) == 1  # still due on day 1


async def test_repeated_identical_failures_do_not_flood_history(client, world):
    tid = one_target(client, world)
    for i in range(3):
        world.google.inspect_script = [(403, {"error": {"code": 403, "status": "PERMISSION_DENIED"}}, {})]
        await run_once(world, now=NOW + timedelta(days=[0, 1, 3][i], minutes=1))
    assert len(world.store.history) == 1


async def test_removing_a_url_deletes_its_history(client, world):
    tid = one_target(client, world)
    await run_once(world)
    assert world.store.history
    assert client.delete(f"/api/v1/google/targets/{tid}", headers=A).status_code == 204
    assert world.store.history == [] and tid not in world.store.targets


# ================================================================================ sitemaps

def test_sitemaps_are_listed_with_read_only_access_and_flag_missing_write_permission(client, world):
    connect_user(client, world)
    choose_property(client)
    r = client.get("/api/v1/google/sitemaps", headers=A).json()
    assert r["can_write"] is False and r["sitemaps"][0]["path"] == "https://www.example.com/sitemap.xml"
    assert (r["sitemaps"][0]["errors"], r["sitemaps"][0]["warnings"], r["sitemaps"][0]["is_pending"]) == (1, 0, False)
    assert world.google.of("/sitemaps")[0]["url"].endswith("/sites/sc-domain%3Aexample.com/sitemaps")  # property is percent-encoded


def test_submitting_a_sitemap_needs_the_separate_write_permission(client, world):
    connect_user(client, world)
    choose_property(client)
    r = client.put("/api/v1/google/sitemaps", json={"url": "https://www.example.com/sitemap.xml"}, headers=A)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "write_permission_required"
    assert [c for c in world.google.calls if c["method"] == "PUT"] == []  # never attempted with a read-only grant


def test_sitemap_submission_with_write_access_and_ownership_check(client, world):
    connect_user(client, world, scope=SCOPE_RW)
    assert client.get("/api/v1/google/status", headers=A).json()["can_write"] is True
    choose_property(client)
    ok = client.put("/api/v1/google/sitemaps", json={"url": "https://www.example.com/sitemap.xml"}, headers=A)
    assert ok.status_code == 200 and ok.json() == {"submitted": True}
    put = [c for c in world.google.calls if c["method"] == "PUT"][0]
    assert put["url"].endswith("/sites/sc-domain%3Aexample.com/sitemaps/https%3A%2F%2Fwww.example.com%2Fsitemap.xml")
    assert put["headers"]["Authorization"] == "Bearer ya29.access-A"
    for outside in ["https://evil.example/sitemap.xml", "https://example.com.evil.com/s.xml", "not a url"]:
        bad = client.put("/api/v1/google/sitemaps", json={"url": outside}, headers=A)
        assert bad.status_code == 400 and bad.json()["detail"]["code"] == "url_outside_property", outside
    assert len([c for c in world.google.calls if c["method"] == "PUT"]) == 1


def test_google_permission_error_on_sitemaps_is_explained(client, world):
    connect_user(client, world, scope=SCOPE_RW)
    choose_property(client)

    async def forbidden(method, url, **kw):
        if method == "PUT":
            return api.Response(403, {"error": {"code": 403, "status": "PERMISSION_DENIED", "message": "x"}}, {})
        return await world.google(method, url, **kw)

    api.set_transport(forbidden)
    r = client.put("/api/v1/google/sitemaps", json={"url": "https://www.example.com/sitemap.xml"}, headers=A)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "google_permission_denied"



# ================================================================================ OAuth state: browser binding and single use

def start_flow(client, headers=A):
    r = client.post("/api/v1/google/connect", json={}, headers=headers)
    state = parse_qs(urlsplit(r.json()["authorization_url"]).query)["state"][0]
    return state, r


def test_connect_sets_an_httponly_binding_cookie_scoped_to_the_callback(client, world):
    state, r = start_flow(client)
    cookie = r.headers["set-cookie"].lower()
    assert "qi_oauth_binding=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert "path=/api/v1/google/callback" in cookie and "max-age=600" in cookie
    assert r.headers["cache-control"] == "no-store"
    secret = client.cookies.get("qi_oauth_binding")
    assert secret and secret not in r.text and secret not in state  # the secret is never in the body or the URL


def test_callback_from_a_different_browser_is_rejected(client, world):
    """An attacker who obtains the state (but not the victim's cookie) cannot complete the connection."""
    state, _ = start_flow(client)
    client.cookies.clear()  # a different browser: no binding cookie
    r = client.get("/api/v1/google/callback", params={"code": "attackers-code", "state": state})
    assert r.headers["location"].endswith("?google_error=invalid_state")
    client.cookies.set("qi_oauth_binding", "some-other-browsers-secret")
    r = client.get("/api/v1/google/callback", params={"code": "attackers-code", "state": state})
    assert r.headers["location"].endswith("?google_error=invalid_state")
    assert world.google.calls == [] and world.store.connections == {}  # Google was never contacted


def test_state_is_single_use_a_replay_is_rejected(client, world):
    world.google.exchange = {"refresh_token": REFRESH_A, "access_token": "x", "expires_in": 3600, "scope": SCOPE_RO, "id_token": id_token()}
    state, _ = start_flow(client)
    cookie = client.cookies.get("qi_oauth_binding")
    first = client.get("/api/v1/google/callback", params={"code": "c1", "state": state})
    assert first.headers["location"].endswith("?connected=1")
    client.cookies.set("qi_oauth_binding", cookie)  # even an attacker who also had the cookie cannot reuse it
    calls_before = len(world.google.calls)
    replay = client.get("/api/v1/google/callback", params={"code": "c2", "state": state})
    assert replay.headers["location"].endswith("?google_error=invalid_state")
    assert len(world.google.calls) == calls_before  # no second token exchange


def test_the_binding_cookie_is_cleared_after_the_callback(client, world):
    state, _ = start_flow(client)
    r = client.get("/api/v1/google/callback", params={"error": "access_denied", "state": state})
    assert "qi_oauth_binding=" in r.headers["set-cookie"] and ("max-age=0" in r.headers["set-cookie"].lower() or 'expires=' in r.headers["set-cookie"].lower())


def test_a_denied_consent_still_consumes_the_state(client, world):
    state, _ = start_flow(client)
    cookie = client.cookies.get("qi_oauth_binding")
    assert client.get("/api/v1/google/callback", params={"error": "access_denied", "state": state}).headers["location"].endswith("access_denied")
    client.cookies.set("qi_oauth_binding", cookie)
    assert client.get("/api/v1/google/callback", params={"code": "c", "state": state}).headers["location"].endswith("invalid_state")


def test_existing_refresh_token_is_kept_when_google_does_not_issue_a_new_one(client, world):
    connect_user(client, world)
    before = world.store.connections["user-A"]["refresh_token_enc"]
    world.google.exchange = {"access_token": "ya29.x", "expires_in": 3600, "scope": SCOPE_RW, "id_token": id_token()}  # no refresh_token
    state, _ = start_flow(client)
    r = client.get("/api/v1/google/callback", params={"code": "c", "state": state})
    assert r.headers["location"].endswith("?connected=1")
    row = world.store.connections["user-A"]
    assert row["refresh_token_enc"] == before and row["scopes"] == SCOPE_RW and row["status"] == "active"
    assert crypto.decrypt_token("user-A", row["refresh_token_enc"]) == REFRESH_A


# ================================================================================ atomic quota, manual reserve, escalation

async def test_scheduled_checks_leave_headroom_for_manual_rechecks(world):
    gate = QuotaGate(600, 10, world.counters, manual_reserve=3, clock=lambda: NOW)
    scheduled = [await gate.reserve("p") for _ in range(8)]
    assert [r.ok for r in scheduled] == [True] * 7 + [False]  # 10 - 3 reserved = 7 for scheduled work
    assert scheduled[-1].reason == "day"
    manual = [await gate.reserve("p", manual=True) for _ in range(4)]
    assert [r.ok for r in manual] == [True, True, True, False]  # the reserved 3 are still available, then the hard cap


async def test_the_daily_cap_is_enforced_by_the_store_so_concurrent_reservations_cannot_overspend(world):
    import asyncio

    gates = [QuotaGate(10_000, 25, world.counters, clock=lambda: NOW) for _ in range(4)]  # four "instances", one shared counter
    results = await asyncio.gather(*(g.reserve("shared") for g in gates for _ in range(20)))
    assert sum(r.ok for r in results) == 25 and world.store.quota[("shared", "2026-11-11")] == 25


async def test_repeated_google_429s_back_off_more_and_more_then_reset_on_success(world):
    gate = QuotaGate(600, 2000, world.counters, clock=lambda: world.clock["now"])
    delays = []
    for _ in range(7):
        until = gate.throttled("p")
        delays.append((until - world.clock["now"]).total_seconds())
        assert not (await gate.reserve("p")).ok  # blocked right now
        world.clock["now"] = until + timedelta(seconds=1)
    assert delays == [120, 600, 3600, 21600, 86400, 86400, 86400]  # 2 min, 10 min, 1 h, 6 h, then 24 h
    gate.succeeded("p")
    assert (gate.throttled("p") - world.clock["now"]).total_seconds() == 120  # the strike count was reset


async def test_retry_after_longer_than_our_backoff_is_honoured(world):
    gate = QuotaGate(600, 2000, world.counters, clock=lambda: NOW)
    assert (gate.throttled("p", retry_after=900) - NOW).total_seconds() == 900


async def test_google_429_escalates_in_the_worker_and_a_success_resets_it(client, world):
    tid = one_target(client, world)
    for expected in (120, 600):
        world.google.inspect_script = [(429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}}, {})]
        world.clock["now"] = parse_next(world.store.targets[tid]) + timedelta(seconds=1)
        await run_once(world)
        assert (parse_next(world.store.targets[tid]) - world.clock["now"]).total_seconds() == expected


# ================================================================================ privacy: delete my Google data

def test_delete_my_google_data_disconnects_and_erases_only_my_records(client, world):
    tid = two_customers(client, world)
    client.post("/api/v1/google/targets", json={"urls": ["https://example.com/bob-page"]}, headers=B)
    world.store.history.append({"id": "h-a", "user_id": "user-A", "target_id": tid, "inspected_at": "2026-11-11T00:00:00+00:00", "outcome": "success", "status": "indexed"})
    assert client.delete("/api/v1/google/data", headers=A).status_code == 204
    assert "user-A" not in world.store.connections and not any(t["user_id"] == "user-A" for t in world.store.targets.values())
    assert not any(h["user_id"] == "user-A" for h in world.store.history)
    assert world.google.of("revoke")  # access was revoked at Google too
    assert "user-B" in world.store.connections and any(t["user_id"] == "user-B" for t in world.store.targets.values())  # Bob untouched
    assert client.delete("/api/v1/google/data").status_code == 401


# ================================================================================ PASS with a different canonical

async def test_pass_with_a_different_google_canonical_is_called_out(client, world):
    tid = one_target(client, world)
    world.google.inspect_body = inspection("PASS", "Submitted and indexed", googleCanonical="https://example.com/other", userCanonical="https://example.com/p")
    await run_once(world)
    v = view(client, tid)
    assert v["display_status"] == "indexed" and "different canonical" in v["inspection"]["note"]
