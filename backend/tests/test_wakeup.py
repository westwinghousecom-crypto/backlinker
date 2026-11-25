"""Idle workers sleep until woken, and nothing is lost across restarts, busy periods or crashes."""
import asyncio
import time
from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import get_settings
from app.core.wakeup import Heartbeats, Wakeups, heartbeats, wakeups
from app.features.diagnostics import repository as drepo
from app.features.diagnostics import worker as dworker
from app.features.indexing import repository as irepo
from app.features.indexing import worker as iworker


# ============================================================================== the signal itself

async def test_notify_before_wait_is_not_lost():
    w = Wakeups()
    w.notify("q")
    t = time.monotonic()
    assert await w.wait("q", 5) is True and time.monotonic() - t < 0.1  # returns at once
    assert await w.wait("q", 0.05) is False  # and the flag was consumed


async def test_notify_wakes_a_sleeping_waiter_quickly():
    w = Wakeups()
    waiter = asyncio.create_task(w.wait("q", 30))
    await asyncio.sleep(0.05)
    t = time.monotonic()
    w.notify("q")
    assert await waiter is True and time.monotonic() - t < 0.2


async def test_every_waiting_worker_wakes_and_queues_are_independent():
    w = Wakeups()
    a, b = asyncio.create_task(w.wait("q", 30)), asyncio.create_task(w.wait("q", 30))
    other = asyncio.create_task(w.wait("other", 0.3))
    await asyncio.sleep(0.05)
    w.notify("q")
    assert await a is True and await b is True
    assert await other is False  # a different queue was not woken


async def test_timeout_is_the_fallback_poll():
    assert await Wakeups().wait("q", 0.05) is False


def test_heartbeats_report_alive_and_stale():
    hb = Heartbeats()
    hb.beat("w1", "idle", stale_after=100)
    hb.beat("w2", "busy", stale_after=0.0)
    hb.beat("w1", "idle", stale_after=100, processed=3)
    time.sleep(0.01)
    snap = hb.snapshot()
    assert snap["w1"]["alive"] and snap["w1"]["processed"] == 3 and snap["w1"]["state"] == "idle"
    assert snap["w2"]["alive"] is False  # missed its own deadline
    hb.remove("w1")
    assert "w1" not in hb.snapshot()


# ============================================================================== indexing worker

class FakeIndexQueue:
    def __init__(self, monkeypatch):
        self.rows: dict[str, dict] = {}
        self.polls = 0
        self.processed: list[str] = []
        self.delay = 0.0
        s = self

        async def list_pending(limit):
            s.polls += 1
            return [dict(r) for r in s.rows.values() if r["status"] == "pending"][:limit]

        async def update_row(rid, data):
            s.rows[rid].update(data)
            return dict(s.rows[rid])

        async def get_row(rid):
            return dict(s.rows[rid])

        async def list_stale(cutoff, limit=50):
            return [dict(r) for r in s.rows.values() if r["status"] == "processing" and r.get("stale")]

        async def submit_urls(session, settings, urls, rotator=None):
            await asyncio.sleep(s.delay)
            s.processed += urls
            return {u: "completed" for u in urls}

        for name, fn in dict(list_pending=list_pending, update_row=update_row, get_row=get_row, list_stale=list_stale).items():
            monkeypatch.setattr(irepo, name, fn)
        monkeypatch.setattr(iworker, "submit_urls", submit_urls)

    def add(self, rid, **extra):
        self.rows[rid] = {"id": rid, "url": f"https://x.example/{rid}", "status": "pending", "attempts": 0, "locked_by": None, **extra}


@pytest.fixture
def idx(monkeypatch):
    monkeypatch.setenv("WORKER_FALLBACK_POLL_SECONDS", "240")  # the real default: only wake-ups can make these tests pass
    get_settings.cache_clear()
    heartbeats.clear()
    wakeups._pending.clear()
    q = FakeIndexQueue(monkeypatch)
    yield q
    get_settings.cache_clear()
    heartbeats.clear()


async def until(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        await asyncio.sleep(0.02)
    return cond()


async def test_work_that_existed_before_a_restart_is_found_without_any_signal(idx):
    idx.add("r1")
    idx.add("r2")
    task = asyncio.create_task(iworker.background_worker("worker-1"))
    try:
        assert await until(lambda: all(r["status"] == "completed" for r in idx.rows.values()))  # first poll at startup
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_idle_worker_does_not_poll_and_wakes_instantly_for_new_work(idx):
    task = asyncio.create_task(iworker.background_worker("worker-1"))
    try:
        await asyncio.sleep(3.3)
        polls_idle = idx.polls
        assert polls_idle <= 2  # the old code polled every second or so (4+ polls in 3 s); now it sleeps
        idx.add("late")
        wakeups.notify("indexing")
        assert await until(lambda: idx.rows["late"]["status"] == "completed", timeout=2)
        assert idx.polls - polls_idle <= 3
        assert heartbeats.snapshot()["worker-1"]["state"] in ("idle", "polling")
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_a_signal_that_arrives_while_the_worker_is_busy_is_not_lost(idx):
    idx.delay = 0.3
    idx.add("first")
    task = asyncio.create_task(iworker.background_worker("worker-1"))
    try:
        await asyncio.sleep(0.1)  # the worker is inside submit_urls for "first"
        idx.add("second")
        wakeups.notify("indexing")  # nobody is waiting yet: the flag must survive
        assert await until(lambda: idx.rows["second"]["status"] == "completed", timeout=3)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_rows_left_processing_by_a_crash_are_recovered_after_restart(idx):
    idx.add("orphan", status="processing", locked_by="dead-worker", stale=True)
    task = asyncio.create_task(iworker.background_worker("worker-1"))  # worker -1 runs recovery on its first pass
    try:
        assert await until(lambda: idx.rows["orphan"]["status"] == "completed", timeout=3)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_shutdown_while_busy_releases_the_claimed_rows_and_drops_the_heartbeat(idx):
    idx.delay = 5
    idx.add("held")
    task = asyncio.create_task(iworker.background_worker("worker-1"))
    assert await until(lambda: idx.rows["held"]["status"] == "processing", timeout=2)
    task.cancel()  # a deployment stops the process
    await asyncio.gather(task, return_exceptions=True)
    assert idx.rows["held"]["status"] == "pending" and idx.rows["held"]["locked_by"] is None  # nothing is stuck
    assert "worker-1" not in heartbeats.snapshot()


async def test_a_lost_claim_race_is_retried_soon_not_after_the_fallback(idx, monkeypatch):
    idx.add("contested")
    real_claim = iworker._claim
    calls = {"n": 0}

    async def flaky_claim(row, wid):
        calls["n"] += 1
        return None if calls["n"] == 1 else await real_claim(row, wid)

    monkeypatch.setattr(iworker, "_claim", flaky_claim)
    task = asyncio.create_task(iworker.background_worker("worker-1"))
    try:
        assert await until(lambda: idx.rows["contested"]["status"] == "completed", timeout=6)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


# ============================================================================== backlink-check worker

async def test_check_worker_sleeps_until_woken_and_finds_pre_existing_work(monkeypatch):
    monkeypatch.setenv("WORKER_FALLBACK_POLL_SECONDS", "240")
    get_settings.cache_clear()
    heartbeats.clear()
    rows = {"c1": {"id": "c1", "url": "https://a.example", "status": "pending", "attempts": 0, "locked_by": None, "target": None}}
    polls = {"n": 0}

    async def list_pending(limit):
        polls["n"] += 1
        return [dict(r) for r in rows.values() if r["status"] == "pending"][:limit]

    async def update_check(cid, data):
        rows[cid].update(data)
        return dict(rows[cid])

    async def get_check(cid):
        return dict(rows[cid])

    async def list_stale(cutoff, limit=50):
        return []

    async def fake_check(session, url, target=None, policy=None):
        from app.features.diagnostics.scanner import UrlCheck, evaluate

        return evaluate(UrlCheck(url=url, status=200, robots_allowed=True))

    for name, fn in dict(list_pending=list_pending, update_check=update_check, get_check=get_check, list_stale=list_stale).items():
        monkeypatch.setattr(drepo, name, fn)
    monkeypatch.setattr(dworker, "check_url", fake_check)
    task = asyncio.create_task(dworker.check_worker("check-worker-1"))
    try:
        assert await until(lambda: rows["c1"]["status"] == "done")
        await asyncio.sleep(1.2)
        idle_polls = polls["n"]
        assert idle_polls <= 3
        rows["c2"] = {"id": "c2", "url": "https://b.example", "status": "pending", "attempts": 0, "locked_by": None, "target": None}
        wakeups.notify("checks")
        assert await until(lambda: rows["c2"]["status"] == "done", timeout=2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        get_settings.cache_clear()
        heartbeats.clear()


# ============================================================================== Google worker + services announce new work

from test_google_flow import A, USERS, client, connect_user, choose_property, inspection, world  # noqa: E402,F401
from app.features.google import service as gservice  # noqa: E402
from app.features.google import worker as gworker  # noqa: E402


async def test_google_worker_wakes_for_new_targets_and_does_not_poll_while_idle(client, world, monkeypatch):
    monkeypatch.setenv("WORKER_FALLBACK_POLL_SECONDS", "240")
    get_settings.cache_clear()
    connect_user(client, world)
    choose_property(client)
    heartbeats.clear()
    wakeups._pending.clear()
    from app.features.google import repository as grepo

    polls = {"n": 0}
    real = grepo.list_due

    async def counting(now_iso, limit):
        polls["n"] += 1
        return await real(now_iso, limit)

    monkeypatch.setattr(grepo, "list_due", counting)
    task = asyncio.create_task(gworker.gsc_worker("gsc-worker-1"))
    try:
        await asyncio.sleep(1.2)
        assert polls["n"] <= 2  # idle: one poll at startup, then asleep
        before = polls["n"]
        result = await gservice.add_targets("user-A", ["https://example.com/new-page"])  # announces itself
        assert result["added"] == 1
        assert await until(lambda: next(iter(world.store.targets.values())).get("latest_at"), timeout=3)
        assert polls["n"] - before <= 3
        await gservice.recheck("user-A", next(iter(world.store.targets)))  # also announces itself
        assert await until(lambda: len(world.store.history) >= 2, timeout=3)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        get_settings.cache_clear()
        heartbeats.clear()


async def test_services_announce_new_work(monkeypatch, client, world):
    sent = []
    monkeypatch.setattr(wakeups, "notify", lambda q: sent.append(q))
    from app.features.submissions import repository as srepo
    from app.features.submissions import service as sservice
    from app.features.submissions.schemas import SubmitRequest

    async def create_url_rows(rows):
        return len(rows), []

    async def count_queued(uid):
        return 0

    monkeypatch.setattr(srepo, "create_url_rows", create_url_rows)
    monkeypatch.setattr(srepo, "count_queued", count_queued)
    await sservice.submit_batch("user-A", SubmitRequest(urls=["https://a.example/"]))
    assert sent == ["indexing"]
    connect_user(client, world)
    choose_property(client)
    await gservice.add_targets("user-A", ["https://example.com/p"])
    await gservice.recheck("user-A", next(iter(world.store.targets)))
    assert sent == ["indexing", "gsc", "gsc"]
