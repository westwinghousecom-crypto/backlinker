import asyncio
import logging
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import get_settings
from app.core.usage import instrument, usage
from app.features.retention import service
from fake_appwrite import FakeTablesDB

NOW = datetime.now(timezone.utc)


def ago(**kw):
    return NOW - timedelta(**kw)


@pytest.fixture
def db(monkeypatch):
    fake = instrument(FakeTablesDB())
    monkeypatch.setattr(service, "get_tables_db", lambda: fake)
    monkeypatch.setenv("RETENTION_ENABLED", "true")
    get_settings.cache_clear()
    usage.reset()
    yield fake
    get_settings.cache_clear()


def seed_everything(db):
    # check batches (90 days) and their results
    db.seed("check_batches", "old-batch", {"user_id": "u"}, ago(days=120))
    db.seed("check_batches", "new-batch", {"user_id": "u"}, ago(days=10))
    db.seed("checks", "old-check", {"user_id": "u", "batch_id": "old-batch"}, ago(days=120))
    db.seed("checks", "new-check", {"user_id": "u", "batch_id": "new-batch"}, ago(days=10))
    # submissions (90 days, only finished ones)
    db.seed("urls", "old-done", {"user_id": "u", "status": "completed"}, ago(days=100))
    db.seed("urls", "old-failed", {"user_id": "u", "status": "failed"}, ago(days=100))
    db.seed("urls", "old-submitted", {"user_id": "u", "status": "submitted"}, ago(days=100))
    db.seed("urls", "old-pending", {"user_id": "u", "status": "pending"}, ago(days=100))  # unfinished work is never deleted
    db.seed("urls", "old-processing", {"user_id": "u", "status": "processing"}, ago(days=100))
    db.seed("urls", "new-done", {"user_id": "u", "status": "completed"}, ago(days=5))
    db.seed("batch_sharing", "old-share", {"user_id": "u"}, ago(days=100))
    db.seed("batch_sharing", "new-share", {"user_id": "u"}, ago(days=1))
    # Google history (365 days), oauth states (1 hour), quota (7 days), tracked targets (never)
    db.seed("gsc_history", "old-h", {"user_id": "u"}, ago(days=400))
    db.seed("gsc_history", "new-h", {"user_id": "u"}, ago(days=30))
    db.seed("google_oauth_states", "old-s", {"user_id": "u"}, ago(hours=3))
    db.seed("google_oauth_states", "new-s", {"user_id": "u"}, ago(minutes=5))
    db.seed("google_quota", "old-q", {"count": 5}, ago(days=10))
    db.seed("google_quota", "new-q", {"count": 5}, ago(days=1))
    db.seed("gsc_targets", "ancient-scheduled-target", {"user_id": "u", "status": "pending"}, ago(days=900))
    db.seed("gsc_targets", "ancient-done-target", {"user_id": "u", "status": "done"}, ago(days=900))


def left(db, table):
    return set(db.tables.get(table, {}))


async def test_old_rows_are_deleted_and_recent_or_unfinished_rows_are_kept(db):
    seed_everything(db)
    counts = await service.run_once()
    assert counts == {"checks": 1, "check_batches": 1, "urls": 3, "batch_sharing": 1, "gsc_history": 1,
                      "google_oauth_states": 1, "google_quota": 1}
    assert left(db, "check_batches") == {"new-batch"} and left(db, "checks") == {"new-check"}
    assert left(db, "urls") == {"old-pending", "old-processing", "new-done"}
    assert left(db, "batch_sharing") == {"new-share"} and left(db, "gsc_history") == {"new-h"}
    assert left(db, "google_oauth_states") == {"new-s"} and left(db, "google_quota") == {"new-q"}


async def test_tracked_google_targets_are_never_deleted(db):
    seed_everything(db)
    await service.run_once()
    assert left(db, "gsc_targets") == {"ancient-scheduled-target", "ancient-done-target"}


async def test_retention_periods_come_from_settings(db, monkeypatch):
    db.seed("check_batches", "b", {"user_id": "u"}, ago(days=20))
    monkeypatch.setenv("RETENTION_CHECK_BATCH_DAYS", "30")
    get_settings.cache_clear()
    assert (await service.run_once())["check_batches"] == 0
    monkeypatch.setenv("RETENTION_CHECK_BATCH_DAYS", "10")
    get_settings.cache_clear()
    assert (await service.run_once())["check_batches"] == 1


async def test_an_idle_run_costs_about_seven_write_requests_and_no_reads(db):
    """The budget rule: with nothing to delete, retention must be almost free."""
    usage.reset()
    counts = await service.run_once()
    assert not any(counts.values())
    snap = usage.snapshot()
    assert snap["reads"] == 0 and snap["writes"] == 7 and snap["by_call"] == {"delete_rows": 7}


async def test_a_busy_run_only_repeats_while_rows_are_actually_deleted(db):
    for i in range(250):
        db.seed("gsc_history", f"h{i}", {"user_id": "u"}, ago(days=500))
    usage.reset()
    assert (await service.run_once())["gsc_history"] == 250
    assert usage.snapshot()["by_call"]["delete_rows"] == 6 + 4  # 6 other tables once each; history: 100 + 100 + 50 + one empty check
    assert usage.snapshot()["reads"] == 0


async def test_retention_never_touches_other_tables_or_rows_outside_its_filters(db):
    db.seed("urls", "fresh", {"user_id": "u", "status": "completed"}, ago(days=1))
    db.seed("google_connections", "conn", {"user_id": "u", "refresh_token_enc": "x"}, ago(days=900))
    await service.run_once()
    assert left(db, "urls") == {"fresh"} and left(db, "google_connections") == {"conn"}


async def test_the_loop_waits_runs_then_repeats_and_survives_errors(db, monkeypatch, caplog):
    runs, sleeps = [], []
    outcomes = [RuntimeError("appwrite down"), {"urls": 2}]

    async def fake_run():
        item = outcomes.pop(0) if outcomes else {}
        runs.append(item)
        if isinstance(item, Exception):
            raise item
        return item

    async def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) >= 4:
            raise asyncio.CancelledError

    monkeypatch.setattr(service, "run_once", fake_run)
    monkeypatch.setattr(service.asyncio, "sleep", fake_sleep)
    caplog.set_level(logging.INFO)
    with pytest.raises(asyncio.CancelledError):
        await service.retention_loop()
    assert sleeps == [300.0, 86400.0, 86400.0, 86400.0]  # first run 5 minutes after start, then every 24 hours
    assert len(runs) == 3 and "retention run failed" in caplog.text  # the error was logged, the loop carried on


async def test_the_loop_can_be_disabled_and_cancelled(db, monkeypatch):
    monkeypatch.setenv("RETENTION_ENABLED", "false")
    get_settings.cache_clear()
    ran = []
    monkeypatch.setattr(service, "run_once", lambda: ran.append(1))
    await asyncio.wait_for(service.retention_loop(), 1)  # returns immediately
    assert ran == []

    monkeypatch.setenv("RETENTION_ENABLED", "true")
    get_settings.cache_clear()
    task = asyncio.create_task(service.retention_loop())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_wired_into_the_app_lifespan():
    import inspect

    from app import main

    assert "retention_loop()" in inspect.getsource(main.lifespan)
