"""Phase A backend: password recovery (no account enumeration, abuse limits) and email verification resend.

Appwrite is never contacted: `_send_recovery` / `_send_verification` (and Appwrite's Account class) are replaced.
"""
import logging
import time

import pytest
from fastapi.testclient import TestClient

from app.core import auth, security
from app.core.auth import AuthUser
from app.core.config import get_settings
from app.features.account import router as account_router

NEUTRAL = account_router.NEUTRAL
FRONTEND = "https://app.quickindex.test"

VERIFIED = {"token-ver": ("user-V", "v@example.com", True)}
USERS = {
    "token-A": ("user-A", "a@example.com", False),
    "token-B": ("user-B", "b@example.com", False),
    **VERIFIED,
}
A = {"Authorization": "Bearer token-A"}
B = {"Authorization": "Bearer token-B"}
V = {"Authorization": "Bearer token-ver"}


def configure(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, str(v))
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    security._hits.clear()
    auth._cache.clear()
    monkeypatch.setattr(account_router, "MIN_RESPONSE_SECONDS", 0.0)  # tests that need the floor restore it
    yield
    security._hits.clear()
    auth._cache.clear()
    get_settings.cache_clear()


@pytest.fixture
def client(monkeypatch):
    for k, v in dict(WORKER_COUNT=0, CHECK_WORKER_COUNT=0, GSC_WORKER_COUNT=0, FRONTEND_URL=FRONTEND,
                     RECOVERY_PER_IP=100, RECOVERY_PER_EMAIL=100).items():
        monkeypatch.setenv(k, str(v))
    get_settings.cache_clear()

    def fake_verify(token):
        row = USERS.get(token)
        return AuthUser(id=row[0], email=row[1], email_verified=row[2], token=token) if row else None

    monkeypatch.setattr(auth, "_verify_sync", fake_verify)
    from app.main import app

    with TestClient(app) as c:
        yield c


def recover(client, email="someone@example.com", **kw):
    return client.post("/api/v1/account/recovery", json={"email": email}, **kw)


# ------------------------------------------------------------------------------ recovery: no enumeration

def test_recovery_answers_identically_whether_or_not_the_account_exists(client, monkeypatch):
    seen: list[str] = []

    def sent(email):
        seen.append(email)

    def unknown_user(email):
        raise RuntimeError("user_not_found: user with the requested id could not be found")

    def arbitrary_failure(email):
        raise ValueError("SMTP exploded")

    responses = []
    for fn, address in ((sent, "exists@example.com"), (unknown_user, "ghost@example.com"), (arbitrary_failure, "other@example.com")):
        monkeypatch.setattr(account_router, "_send_recovery", fn)
        r = recover(client, address)
        responses.append(r)

    assert seen == ["exists@example.com"]
    assert [r.status_code for r in responses] == [202, 202, 202]
    assert all(r.json() == NEUTRAL for r in responses)
    assert len({r.text for r in responses}) == 1  # byte-for-byte identical bodies
    assert len({tuple(sorted((k, v) for k, v in r.headers.items() if k in ("content-type",))) for r in responses}) == 1


def test_recovery_swallows_appwrite_exceptions_of_any_type(client, monkeypatch):
    from appwrite.exception import AppwriteException

    for exc in (AppwriteException("User not found", 404, "user_not_found"), AppwriteException("rate", 429),
                ConnectionError("down"), KeyError("x")):
        def boom(email, exc=exc):
            raise exc

        monkeypatch.setattr(account_router, "_send_recovery", boom)
        security._hits.clear()
        r = recover(client)
        assert r.status_code == 202 and r.json() == NEUTRAL


def test_default_timing_floor_is_at_least_half_a_second():
    import inspect
    import re

    # The autouse fixture patches the module attribute for speed, so read the shipped default from the source.
    match = re.search(r"^MIN_RESPONSE_SECONDS\s*=\s*([0-9.]+)", inspect.getsource(account_router), re.M)
    assert match and float(match.group(1)) >= 0.5


def test_timing_floor_applies_to_both_success_and_failure(client, monkeypatch):
    monkeypatch.setattr(account_router, "MIN_RESPONSE_SECONDS", 0.6)
    durations = []
    for i, fn in enumerate((lambda e: None, lambda e: (_ for _ in ()).throw(RuntimeError("no such user")))):
        monkeypatch.setattr(account_router, "_send_recovery", fn)
        start = time.monotonic()
        assert recover(client, f"user{i}@example.com").status_code == 202
        durations.append(time.monotonic() - start)
    assert all(d >= 0.55 for d in durations), durations  # a fast "no such account" cannot be told from a send
    assert abs(durations[0] - durations[1]) < 0.4


@pytest.mark.parametrize("bad", ["", "not-an-email", "a@b", "@example.com", "a b@example.com", "a@@example.com",
                                 "a@example", "x" * 80 + "@example.com", "a@" + "x" * 300 + ".com"])
def test_malformed_email_is_rejected_before_anything_is_sent(client, monkeypatch, bad):
    monkeypatch.setattr(account_router, "_send_recovery", lambda e: pytest.fail("must not be called"))
    assert recover(client, bad).status_code == 422


def test_missing_email_field_is_rejected(client):
    assert client.post("/api/v1/account/recovery", json={}).status_code == 422


# ------------------------------------------------------------------------------ recovery: abuse limits

def test_per_ip_limit_applies_to_any_address(client, monkeypatch):
    configure(monkeypatch, RECOVERY_PER_IP=2, RECOVERY_PER_EMAIL=100)
    monkeypatch.setattr(account_router, "_send_recovery", lambda e: None)
    codes = [recover(client, f"person{i}@example.com").status_code for i in range(4)]
    assert codes == [202, 202, 429, 429]


def test_per_email_limit_and_case_insensitivity(client, monkeypatch):
    configure(monkeypatch, RECOVERY_PER_IP=100, RECOVERY_PER_EMAIL=3)
    sent = []
    monkeypatch.setattr(account_router, "_send_recovery", lambda e: sent.append(e))
    codes = [recover(client, a).status_code for a in
             ("Alice@Example.com", "alice@example.com", "ALICE@EXAMPLE.COM", "alice@example.com")]
    assert codes == [202, 202, 202, 429]
    assert sent == ["alice@example.com"] * 3  # normalised to lower case before Appwrite sees it
    assert recover(client, "bob@example.com").status_code == 202  # other addresses unaffected


def test_limit_response_does_not_depend_on_whether_the_account_exists(client, monkeypatch):
    configure(monkeypatch, RECOVERY_PER_IP=100, RECOVERY_PER_EMAIL=1)
    outcomes = {"real@example.com": lambda e: None,
                "ghost@example.com": lambda e: (_ for _ in ()).throw(RuntimeError("user_not_found"))}
    bodies = []
    for address, fn in outcomes.items():
        monkeypatch.setattr(account_router, "_send_recovery", fn)
        assert recover(client, address).status_code == 202
        r = recover(client, address)
        assert r.status_code == 429
        bodies.append(r.text)
    assert len(set(bodies)) == 1  # real and unknown addresses are throttled with the identical answer


def test_ip_and_email_limits_give_the_same_429_body(client, monkeypatch):
    configure(monkeypatch, RECOVERY_PER_IP=100, RECOVERY_PER_EMAIL=1)
    monkeypatch.setattr(account_router, "_send_recovery", lambda e: None)
    recover(client, "x@example.com")
    by_email = recover(client, "x@example.com")
    security._hits.clear()
    configure(monkeypatch, RECOVERY_PER_IP=1, RECOVERY_PER_EMAIL=100)
    recover(client, "y@example.com")
    by_ip = recover(client, "z@example.com")
    assert by_email.status_code == by_ip.status_code == 429 and by_email.json() == by_ip.json()


def test_malformed_requests_do_not_consume_the_limits(client, monkeypatch):
    configure(monkeypatch, RECOVERY_PER_IP=2, RECOVERY_PER_EMAIL=100)
    monkeypatch.setattr(account_router, "_send_recovery", lambda e: None)
    for _ in range(5):
        assert recover(client, "nope").status_code == 422
    assert recover(client, "ok1@example.com").status_code == 202


# ------------------------------------------------------------------------------ recovery: link and logging

class CapturingAccount:
    calls: list[dict] = []

    def __init__(self, client):
        self.client = client

    def create_recovery(self, email, url):
        CapturingAccount.calls.append({"email": email, "url": url})


def test_reset_link_comes_from_server_config_not_from_request_headers(client, monkeypatch):
    CapturingAccount.calls = []
    monkeypatch.setattr(account_router, "Account", CapturingAccount)
    configure(monkeypatch, FRONTEND_URL=FRONTEND + "/")  # trailing slash must not double up
    hostile = {"Host": "evil.example", "Origin": "https://evil.example", "Referer": "https://evil.example/x",
               "X-Forwarded-Host": "evil.example", "X-Forwarded-Proto": "http", "Forwarded": "host=evil.example"}
    r = recover(client, "victim@example.com", headers=hostile)
    assert r.status_code == 202 and r.json() == NEUTRAL
    assert CapturingAccount.calls == [{"email": "victim@example.com", "url": f"{FRONTEND}/reset-password"}]
    assert "evil.example" not in CapturingAccount.calls[0]["url"]


def test_email_address_is_never_logged(client, monkeypatch, caplog):
    secret_address = "very.private.person@example.com"

    def failing(email):
        raise RuntimeError(f"no user for {email}")  # even if a library puts the address in its message

    monkeypatch.setattr(account_router, "_send_recovery", failing)
    caplog.set_level(logging.DEBUG)
    assert recover(client, secret_address).status_code == 202
    monkeypatch.setattr(account_router, "_send_recovery", lambda e: None)
    security._hits.clear()
    assert recover(client, secret_address.upper()).status_code == 202
    blob = caplog.text.lower()
    assert secret_address not in blob and "very.private.person" not in blob
    assert "keys" not in blob


def test_rate_limit_state_does_not_store_the_plain_address(client, monkeypatch):
    monkeypatch.setattr(account_router, "_send_recovery", lambda e: None)
    recover(client, "stored.plain@example.com")
    assert not any("stored.plain" in key for key in security._hits)


# ------------------------------------------------------------------------------ verification resend

def test_verification_requires_sign_in(client):
    assert client.post("/api/v1/account/verification").status_code == 401
    assert client.post("/api/v1/account/verification", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_already_verified_user_gets_a_message_and_no_email(client, monkeypatch):
    monkeypatch.setattr(account_router, "_send_verification", lambda token: pytest.fail("must not be called"))
    for _ in range(5):  # not rate limited: nothing is sent
        r = client.post("/api/v1/account/verification", headers=V)
        assert r.status_code == 202 and r.json()["already_verified"] is True


def test_verification_sends_with_the_callers_own_token(client, monkeypatch):
    tokens = []
    monkeypatch.setattr(account_router, "_send_verification", lambda token: tokens.append(token))
    r = client.post("/api/v1/account/verification", headers=A)
    assert r.status_code == 202 and r.json()["already_verified"] is False
    assert tokens == ["token-A"]


def test_verification_link_uses_frontend_url_from_config(client, monkeypatch):
    captured = {}

    class FakeAccount:
        def __init__(self, c):
            captured["jwt_client"] = c

        def create_email_verification(self, url):
            captured["url"] = url

    monkeypatch.setattr(account_router, "Account", FakeAccount)
    r = client.post("/api/v1/account/verification", headers={**A, "Host": "evil.example", "Origin": "https://evil.example"})
    assert r.status_code == 202
    assert captured["url"] == f"{FRONTEND}/verify-email"


def test_verification_cooldown(client, monkeypatch):
    monkeypatch.setattr(account_router, "_send_verification", lambda token: None)
    assert client.post("/api/v1/account/verification", headers=A).status_code == 202
    again = client.post("/api/v1/account/verification", headers=A)
    assert again.status_code == 429 and "wait" in again.json()["detail"].lower()


def test_verification_hourly_cap(client, monkeypatch):
    configure(monkeypatch, VERIFICATION_RESEND_COOLDOWN=0, VERIFICATION_PER_HOUR=2)  # cooldown off, cap on
    monkeypatch.setattr(account_router, "_send_verification", lambda token: None)
    codes = [client.post("/api/v1/account/verification", headers=A).status_code for _ in range(4)]
    assert codes == [202, 202, 429, 429]


def test_verification_limits_are_per_user(client, monkeypatch):
    monkeypatch.setattr(account_router, "_send_verification", lambda token: None)
    assert client.post("/api/v1/account/verification", headers=A).status_code == 202
    assert client.post("/api/v1/account/verification", headers=A).status_code == 429
    assert client.post("/api/v1/account/verification", headers=B).status_code == 202  # B unaffected by A's cooldown
    assert client.post("/api/v1/account/verification", headers=B).status_code == 429


def test_failed_send_is_a_502_and_leaks_no_details(client, monkeypatch):
    def failing(token):
        raise RuntimeError("smtp password=hunter2 refused")

    monkeypatch.setattr(account_router, "_send_verification", failing)
    r = client.post("/api/v1/account/verification", headers=A)
    assert r.status_code == 502
    assert "hunter2" not in r.text and "smtp" not in r.text.lower()


def test_oauth_code_and_state_are_redacted_from_access_logs():
    import logging

    from app.core.logfilter import RedactQueryFilter, redact

    assert redact("GET /api/v1/google/callback?code=4/0AbC&state=gAAAA-xyz&scope=x HTTP/1.1") == (
        "GET /api/v1/google/callback?code=[redacted]&state=[redacted]&scope=x HTTP/1.1")
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                            ("127.0.0.1:1", "GET", "/api/v1/google/callback?code=SECRETCODE&state=SEALED", "1.1", 303), None)
    assert RedactQueryFilter().filter(rec)
    assert "SECRETCODE" not in rec.getMessage() and "SEALED" not in rec.getMessage() and "/callback?" in rec.getMessage()
    import app.main  # noqa: F401  (installs the filter on uvicorn's loggers)
    assert any(isinstance(f, RedactQueryFilter) for f in logging.getLogger("uvicorn.access").filters)
