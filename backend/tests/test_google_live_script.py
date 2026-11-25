"""The live-test harness (scripts/google_live_check.py), exercised against a MOCKED Google.

These tests prove the harness itself behaves (redaction, ownership checks, accounting, revocation reporting). They are NOT
live results: no real Google API is called here.
"""
import importlib.util
from datetime import timedelta
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.features.google import api
from test_google_flow import (  # noqa: F401  (fixtures: world, client)
    A, NOW, REFRESH_A, SECRET, SCOPE_RO, client, connect_user, choose_property, inspection, world,
)

SPEC = importlib.util.spec_from_file_location("google_live_check", Path(__file__).resolve().parents[1] / "scripts" / "google_live_check.py")
live = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(live)
LEAKS = (REFRESH_A, SECRET, "ya29.", "auth-code-123", "GOCSPX")


def ready(client, world):
    connect_user(client, world)
    choose_property(client)


def test_redact_masks_credentials_and_shortens_emails():
    out = live.redact({"access_token": "ya29.abc", "refresh_token": "1//0gXYZxyzxyzxyz", "client_secret": "GOCSPX-abc",
                       "note": "token ya29.a0AfBxyz and mail owner@gmail.com", "nested": [{"id_token": "eyJabc.def.ghi"}], "siteUrl": "sc-domain:example.com"})
    assert out["access_token"] == out["refresh_token"] == out["client_secret"] == "[redacted]"
    assert "ya29" not in out["note"] and "owner@" not in out["note"] and "o***@gmail.com" in out["note"]
    assert out["nested"][0]["id_token"] == "[redacted]" and out["siteUrl"] == "sc-domain:example.com"


def test_preflight_config_checks(world, monkeypatch):
    status = {n: s for s, n, _ in live.check_config()}
    assert status["TOKEN_ENCRYPTION_KEY"] == "PASS" and status["GOOGLE_REDIRECT_URI path"] == "PASS" and status["same-site hosting"] == "PASS"
    assert status["GOOGLE_CLIENT_ID"] == "FAIL"  # the test id "cid" is not a real-looking Google client id
    for var, value, name in [("GOOGLE_REDIRECT_URI", "http://localhost:8000/auth/google/callback", "GOOGLE_REDIRECT_URI path"),
                             ("GOOGLE_REDIRECT_URI", "http://api.example.com/api/v1/google/callback", "GOOGLE_REDIRECT_URI scheme"),
                             ("TOKEN_ENCRYPTION_KEY", "", "TOKEN_ENCRYPTION_KEY"),
                             ("GSC_INSPECT_PER_DAY", "5000", "quota limits")]:
        monkeypatch.setenv(var, value)
        get_settings.cache_clear()
        assert {n: s for s, n, _ in live.check_config()}[name] == "FAIL", name
        monkeypatch.undo()
        get_settings.cache_clear()


def test_preflight_flags_hosting_that_would_drop_the_binding_cookie(world, monkeypatch):
    monkeypatch.setenv("FRONTEND_URL", "https://app.one.com")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://api.two.com/api/v1/google/callback")
    get_settings.cache_clear()
    assert {n: s for s, n, _ in live.check_config()}["same-site hosting"] == "FAIL"
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://api.one.com/api/v1/google/callback")
    get_settings.cache_clear()
    assert {n: s for s, n, _ in live.check_config()}["same-site hosting"] == "PASS"


async def test_credential_check_distinguishes_valid_and_invalid_clients(world, monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "123456-abc.apps.googleusercontent.com")
    get_settings.cache_clear()

    async def answer(code):
        async def t(method, url, **kw):
            if "openid-configuration" in url:
                return api.Response(200, {}, {})
            return api.Response(400 if code != "ok" else 200, {"error": code}, {})
        api.set_transport(t)

    # discovery uses aiohttp directly, so only the token-endpoint part is exercised through the transport
    for code, expected in [("invalid_grant", "PASS"), ("invalid_client", "FAIL"), ("redirect_uri_mismatch", "FAIL")]:
        await answer(code)
        rows = await live.check_google_network()
        got = [s for s, n, _ in rows if n == "Google accepts the client (live)"]
        assert got and got[0] in (expected, "WARN"), (code, rows)  # WARN only if the (real) discovery fetch was offline


async def test_properties_command_prints_raw_response_and_classification_without_secrets(client, world, capsys):
    ready(client, world)
    assert await live.cmd_properties("user-A") == 0
    out = capsys.readouterr().out
    assert "RAW Google response" in out and "siteEntry" in out and "siteOwner" in out and "sc-domain:example.com" in out
    assert "domain" in out and "url_prefix" in out
    assert not any(leak in out for leak in LEAKS)


async def test_inspect_command_shows_verdict_coverage_crawl_canonical_and_counts_one_unit(client, world, capsys):
    ready(client, world)
    world.google.inspect_body = inspection("PASS", "Submitted and indexed", googleCanonical="https://example.com/a", userCanonical="https://example.com/a")
    assert await live.cmd_inspect("user-A", ["https://example.com/a", "https://outside.org/x"]) == 0
    out = capsys.readouterr().out
    assert "verdict=PASS" in out and "coverageState='Submitted and indexed'" in out and "lastCrawlTime=2026-11-10T08:00:00Z" in out
    assert "googleCanonical=https://example.com/a" in out and "Confirmed Indexed" in out
    assert "today's counter 0 -> 1 (expected +1)" in out
    assert "SKIPPED https://outside.org/x" in out
    assert len(world.google.of("index:inspect")) == 1  # the outside URL never reached Google
    assert not any(leak in out for leak in LEAKS)


async def test_inspect_stops_instead_of_exceeding_the_quota_gate(client, world, capsys):
    from app.features.google import service
    from app.features.google.quota import QuotaGate

    ready(client, world)
    service.reset_gate(QuotaGate(600, 1, world.counters, clock=lambda: NOW))
    assert await live.cmd_inspect("user-A", ["https://example.com/a", "https://example.com/b"]) == 2
    assert len(world.google.of("index:inspect")) == 1 and "STOPPED" in capsys.readouterr().out


async def test_refresh_command_reports_a_new_access_token_and_unchanged_refresh_token(client, world, capsys):
    ready(client, world)
    refreshes = lambda: len([c for c in world.google.calls if c["url"] == api.TOKEN_URL and c["data"].get("grant_type") == "refresh_token"])  # noqa: E731
    before = refreshes()  # setting up the connection already fetched one access token
    assert await live.cmd_refresh("user-A") == 0
    out = capsys.readouterr().out
    assert "new access token obtained from Google: True" in out and "stored refresh token unchanged in Appwrite: True" in out
    assert "served from memory cache (no extra Google call): True" in out
    assert refreshes() - before == 1  # exactly one new Google call: the second token request came from the cache
    assert not any(leak in out for leak in LEAKS)


async def test_sitemaps_command_lists_with_read_only_access(client, world, capsys):
    ready(client, world)
    assert await live.cmd_sitemaps("user-A") == 0
    out = capsys.readouterr().out
    assert "granted scopes include write: False" in out and "sitemap.xml" in out and [c for c in world.google.calls if c["method"] == "PUT"] == []


async def test_schedule_command_persists_target_and_history_and_plans_day_one(client, world, capsys):
    ready(client, world)
    world.google.inspect_body = inspection("NEUTRAL", "Crawled - currently not indexed")
    assert await live.cmd_schedule("user-A", "https://example.com/new") == 0
    out = capsys.readouterr().out
    assert "target row persisted" in out and "history rows persisted" in out and '"status": "not_indexed"' in out
    target = next(iter(world.store.targets.values()))
    assert target["step"] == 1 and len(world.store.history) == 1
    started, nxt = (__import__("datetime").datetime.fromisoformat(target[k]) for k in ("started_at", "next_check_at"))
    assert nxt - started == timedelta(days=1)


async def test_disconnect_command_reports_revocation_only_if_google_rejects_the_old_token(client, world, capsys):
    ready(client, world)
    real = world.google

    async def revoking(method, url, **kw):
        resp = await real(method, url, **kw)
        if url == api.REVOKE_URL:
            real.refresh_error = (400, {"error": "invalid_grant"})
        return resp

    api.set_transport(revoking)
    assert await live.cmd_disconnect("user-A") == 0
    out = capsys.readouterr().out
    assert "connection row deleted from Appwrite: True" in out and "revocation confirmed" in out
    assert not any(leak in out for leak in LEAKS)


async def test_disconnect_command_fails_loudly_if_the_old_token_still_works(client, world, capsys):
    ready(client, world)
    assert await live.cmd_disconnect("user-A") == 1  # the mock keeps accepting the token: the harness must not claim success
    assert "STILL WORKS" in capsys.readouterr().out


async def test_delete_data_command_leaves_nothing_behind(client, world, capsys):
    ready(client, world)
    client.post("/api/v1/google/targets", json={"urls": ["https://example.com/a"]}, headers=A)
    assert world.store.targets
    assert await live.cmd_delete_data("user-A") == 0
    assert "'connection': False, 'targets': 0" in capsys.readouterr().out
    assert not world.store.connections and not world.store.targets


async def test_commands_refuse_to_run_without_a_connection(world, capsys):
    with pytest.raises(SystemExit) as e:
        await live.cmd_properties("nobody")
    assert "Connect in the web app first" in str(e.value)
