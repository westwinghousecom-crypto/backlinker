"""Check-batch flow against an in-memory fake of the Appwrite repository."""
import itertools

import pytest
from pydantic import ValidationError

from app.core.config import get_settings
from app.features.diagnostics import repository as repo
from app.features.diagnostics import service, worker
from app.features.diagnostics.scanner import UrlCheck, evaluate
from app.features.diagnostics.schemas import CheckBatchRequest

ids = itertools.count(1)


@pytest.fixture
def db(monkeypatch):
    batches: dict[str, dict] = {}
    checks: dict[str, dict] = {}

    async def create_batch(batch_id, user_id, target, total):
        batches[batch_id] = {"id": batch_id, "user_id": user_id, "target": target, "total": total, "created_at": "2026-01-01T00:00:00Z"}

    async def get_batch(batch_id):
        return batches.get(batch_id)

    async def create_checks(rows):
        for r in rows:
            r = dict(r)
            cid = r.pop("$id")
            r.pop("$permissions", None)
            checks[cid] = {"id": cid, **r}
        return len(rows)

    async def count_queued(user_id):
        return sum(c["user_id"] == user_id and c["status"] in ("pending", "processing") for c in checks.values())

    async def list_checks(batch_id, max_rows=1000):
        return sorted((dict(c) for c in checks.values() if c["batch_id"] == batch_id), key=lambda c: c["position"])

    async def count_checks(batch_id, status=None):
        return sum(c["batch_id"] == batch_id and (status is None or c["status"] == status) for c in checks.values())

    async def get_check(cid):
        return dict(checks[cid])

    async def update_check(cid, data):
        checks[cid].update(data)
        return dict(checks[cid])

    async def list_pending(limit):
        return [dict(c) for c in checks.values() if c["status"] == "pending"][:limit]

    async def list_batches(user_id, limit):
        return [b for b in batches.values() if b["user_id"] == user_id][:limit]

    for name, fn in dict(create_batch=create_batch, get_batch=get_batch, create_checks=create_checks,
                         list_checks=list_checks, count_checks=count_checks, get_check=get_check,
                         update_check=update_check, list_pending=list_pending, list_batches=list_batches, count_queued=count_queued).items():
        monkeypatch.setattr(repo, name, fn)
    return checks


def fake_check(outcomes):
    async def _check(session, url, target=None):
        c = UrlCheck(url=url, **outcomes[url])
        return evaluate(c)

    return _check


async def run_worker_once(monkeypatch, outcomes):
    monkeypatch.setattr(worker, "check_url", fake_check(outcomes))
    settings = get_settings()
    claimed = [c for c in [await worker._claim(r, "w1") for r in await repo.list_pending(10)] if c]
    for c in claimed:
        await worker._run_check(None, c, settings)


async def test_full_flow_summary_and_recheck(db, monkeypatch):
    req = CheckBatchRequest(urls=["https://a.com/1", "https://b.com/2", "https://c.com/3", "https://a.com/1"], target="mysite.com")
    assert req.target == "https://mysite.com"
    created = await service.create_batch("u", req)
    assert created.total == 3  # duplicate removed

    b = await service.get_batch("u", created.batch_id)
    assert b.summary.checked == 0 and not b.summary.done

    outcomes = {
        "https://a.com/1": dict(status=200, robots_allowed=True, backlink_found=True, backlink_anchor="great"),
        "https://b.com/2": dict(status=200, robots_allowed=True, noindex=True, noindex_source="meta robots tag", backlink_found=False),
        "https://c.com/3": dict(),  # unreachable
    }
    await run_worker_once(monkeypatch, outcomes)

    b = await service.get_batch("u", created.batch_id)
    s = b.summary
    assert (s.total, s.checked, s.eligible, s.with_problems, s.blocked, s.unreachable) == (3, 3, 1, 2, 1, 1)
    assert (s.backlinks_found, s.backlinks_missing, s.done) == (1, 1, True)
    assert [i.url for i in b.items] == ["https://a.com/1", "https://b.com/2", "https://c.com/3"]  # paste order
    assert b.items[0].result.backlink_anchor == "great" and b.items[0].result.google_index_status == "unknown"

    # recheck one URL: it goes back to pending and the summary reflects it
    await service.recheck("u", created.batch_id, b.items[1].id)
    b = await service.get_batch("u", created.batch_id)
    assert b.summary.checked == 2 and not b.summary.done and b.items[1].state == "pending" and b.items[1].result is None
    outcomes["https://b.com/2"] = dict(status=200, robots_allowed=True, backlink_found=True)
    await run_worker_once(monkeypatch, outcomes)
    assert (await service.get_batch("u", created.batch_id)).summary.eligible == 2


async def test_recheck_rejects_other_batch_and_history(db):
    a = await service.create_batch("u", CheckBatchRequest(urls=["https://a.com/1"]))
    b = await service.create_batch("u", CheckBatchRequest(urls=["https://b.com/1"]))
    row_of_b = (await service.get_batch("u", b.batch_id)).items[0].id
    with pytest.raises(service.NotFound):
        await service.recheck("u", a.batch_id, row_of_b)
    with pytest.raises(service.NotFound):
        await service.get_batch("u", "missing")
    history = await service.list_history("u")
    assert {h.batch_id for h in history} == {a.batch_id, b.batch_id} and all(h.checked == 0 for h in history)


def test_request_validation():
    with pytest.raises(ValidationError):
        CheckBatchRequest(urls=["https://a.com"], target="not a url!")
    with pytest.raises(ValidationError):
        CheckBatchRequest(urls=[f"https://a.com/{i}" for i in range(1001)])
    assert CheckBatchRequest(urls=["https://a.com"], target="  ").target is None


async def test_unexpected_error_retries_then_reports(db, monkeypatch):
    created = await service.create_batch("u", CheckBatchRequest(urls=["https://a.com/1"]))

    async def boom(session, url, target=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(worker, "check_url", boom)
    settings = get_settings()
    for _ in range(settings.CHECK_MAX_ATTEMPTS):
        for r in await repo.list_pending(10):
            c = await worker._claim(r, "w1")
            await worker._run_check(None, c, settings)
    item = (await service.get_batch("u", created.batch_id)).items[0]
    assert item.state == "done" and item.result.verdict == "unreachable"
    assert item.result.problems[0].code == "fetch_failed"
