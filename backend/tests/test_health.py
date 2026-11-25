import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.usage import UsageCounter, instrument, usage
from app.core.wakeup import heartbeats
from app.features.health import router as health


@pytest.fixture
def app_client(monkeypatch):
    monkeypatch.setenv("WORKER_COUNT", "0")
    monkeypatch.setenv("CHECK_WORKER_COUNT", "0")
    monkeypatch.setenv("GSC_WORKER_COUNT", "0")
    get_settings.cache_clear()
    health.reset_cache()
    heartbeats.clear()
    from app.main import app

    with TestClient(app) as c:
        yield c
    get_settings.cache_clear()
    health.reset_cache()
    heartbeats.clear()


def probe_ok(monkeypatch, counter):
    def probe():
        counter["n"] += 1

    monkeypatch.setattr(health, "_probe_appwrite", probe)


def test_live_never_touches_a_dependency(app_client, monkeypatch):
    monkeypatch.setattr(health, "_probe_appwrite", lambda: (_ for _ in ()).throw(AssertionError("live must not call Appwrite")))
    for path in ("/health", "/health/live"):
        assert app_client.get(path).json() == {"status": "ok"}


def test_ready_ok_with_no_workers_expected_and_appwrite_reachable(app_client, monkeypatch):
    calls = {"n": 0}
    probe_ok(monkeypatch, calls)
    r = app_client.get("/health/ready")
    assert r.status_code == 200 and r.json()["status"] == "ready"
    assert r.json()["checks"]["appwrite"] == {"ok": True, "detail": "reachable", "cached": False}
    assert r.headers["cache-control"] == "no-store"


def test_dependency_check_is_cached_so_monitors_do_not_burn_the_read_budget(app_client, monkeypatch):
    calls = {"n": 0}
    probe_ok(monkeypatch, calls)
    for _ in range(50):  # an uptime monitor polling constantly
        assert app_client.get("/health/ready").status_code == 200
    assert calls["n"] == 1
    assert app_client.get("/health/ready").json()["checks"]["appwrite"]["cached"] is True


def test_ready_is_503_when_appwrite_is_down_and_never_leaks_error_text(app_client, monkeypatch):
    class Down(Exception):
        code = 503

    def probe():
        raise Down("secret-internal-host.example refused connection")

    monkeypatch.setattr(health, "_probe_appwrite", probe)
    r = app_client.get("/health/ready")
    assert r.status_code == 503 and r.json()["status"] == "not_ready"
    assert r.json()["checks"]["appwrite"]["detail"] == "unreachable (503)" and "secret-internal-host" not in r.text


def test_ready_requires_every_expected_worker_to_report_after_the_startup_grace(app_client, monkeypatch):
    probe_ok(monkeypatch, {"n": 0})
    monkeypatch.setenv("WORKER_COUNT", "2")
    monkeypatch.setenv("CHECK_WORKER_COUNT", "1")
    get_settings.cache_clear()
    # inside the startup grace period missing workers are tolerated
    assert app_client.get("/health/ready").status_code == 200
    monkeypatch.setattr(health, "STARTED", health.STARTED - 3600)  # pretend the process has been up for an hour
    r = app_client.get("/health/ready")
    assert r.status_code == 503
    missing = {n for n, w in r.json()["checks"]["workers"]["workers"].items() if w["state"] == "missing"}
    assert missing == {"worker-1", "worker-2", "check-worker-1"}
    heartbeats.beat("worker-1", "idle", stale_after=600)
    heartbeats.beat("worker-2", "busy", stale_after=600)
    assert app_client.get("/health/ready").status_code == 503  # one still missing
    heartbeats.beat("check-worker-1", "idle", stale_after=600, processed=4)
    r = app_client.get("/health/ready")
    assert r.status_code == 200 and r.json()["checks"]["workers"]["workers"]["check-worker-1"]["processed"] == 4


def test_a_stuck_worker_makes_the_app_not_ready(app_client, monkeypatch):
    probe_ok(monkeypatch, {"n": 0})
    monkeypatch.setenv("WORKER_COUNT", "1")
    get_settings.cache_clear()
    monkeypatch.setattr(health, "STARTED", health.STARTED - 3600)
    heartbeats.beat("worker-1", "busy", stale_after=0.0)  # missed its own deadline: the loop is stuck
    r = app_client.get("/health/ready")
    assert r.status_code == 503 and r.json()["checks"]["workers"]["workers"]["worker-1"]["alive"] is False


def test_google_worker_is_expected_only_when_google_is_configured(app_client, monkeypatch):
    monkeypatch.setenv("GSC_WORKER_COUNT", "1")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")  # the developer's real .env may have Google configured
    get_settings.cache_clear()
    assert "gsc-worker-1" not in health.expected_workers()
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "x")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "y")
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "z")
    get_settings.cache_clear()
    assert "gsc-worker-1" in health.expected_workers()


def test_ready_reports_exact_appwrite_request_counts(app_client, monkeypatch):
    probe_ok(monkeypatch, {"n": 0})
    usage.reset()
    usage.record("list_rows", 3)
    usage.record("create_rows", 10)
    body = app_client.get("/health/ready").json()["appwrite_requests"]
    assert body["reads"] == 3 and body["writes"] == 10 and body["by_call"] == {"list_rows": 3, "create_rows": 10}


def test_instrument_counts_reads_and_writes_without_changing_behaviour():
    class Fake:
        def list_rows(self, **kw): return "L"
        def get_row(self, **kw): return "G"
        def create_rows(self, **kw): return "CR"
        def update_row(self, **kw): return "U"
        def delete_rows(self, **kw): return "D"
        def increment_row_column(self, **kw): return "I"

    u = UsageCounter()
    import app.core.usage as mod
    mod.usage, original = u, mod.usage
    try:
        f = instrument(Fake())
        assert (f.list_rows(), f.get_row(), f.create_rows(rows=[1, 2, 3]), f.update_row(), f.delete_rows(), f.increment_row_column()) == ("L", "G", "CR", "U", "D", "I")
        snap = u.snapshot()
        assert snap["reads"] == 2 and snap["writes"] == 3 + 1 + 1 + 1  # create_rows counts one write per row
    finally:
        mod.usage = original
