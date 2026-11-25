"""End-to-end queue flow against an in-memory fake of the Appwrite repositories."""
import itertools

import pytest

from app.core.config import get_settings
from app.features.indexing import repository as idx_repo
from app.features.indexing import worker
from app.features.submissions import repository as sub_repo
from app.features.submissions import service
from app.features.submissions.schemas import SubmitRequest

ids = itertools.count(1)


@pytest.fixture
def db(monkeypatch):
    rows: dict[str, dict] = {}

    async def create_url_rows(data):
        for d in data:
            d = dict(d)
            rid = d.pop("$id")
            d.pop("$permissions", None)
            rows[rid] = {"id": rid, **d}
        return len(data), []

    async def list_batch(batch_id, user_id, max_rows=1000):
        return [dict(r) for r in rows.values() if r["batch_id"] == batch_id and r["user_id"] == user_id][:max_rows]

    async def count_queued(user_id):
        return sum(r["user_id"] == user_id and r["status"] in ("pending", "processing") for r in rows.values())

    async def list_pending(limit):
        return [dict(r) for r in rows.values() if r["status"] == "pending"][:limit]

    async def update_row(rid, data):
        rows[rid].update(data)
        return dict(rows[rid])

    async def get_row(rid):
        return dict(rows[rid])

    async def list_stale(cutoff, limit=50):
        return [dict(r) for r in rows.values() if r["status"] == "processing"]

    monkeypatch.setattr(sub_repo, "create_url_rows", create_url_rows)
    monkeypatch.setattr(sub_repo, "list_batch", list_batch)
    monkeypatch.setattr(sub_repo, "count_queued", count_queued)
    for name, fn in [("list_pending", list_pending), ("update_row", update_row),
                     ("get_row", get_row), ("list_stale", list_stale)]:
        monkeypatch.setattr(idx_repo, name, fn)
    return rows


async def run_once(monkeypatch, outcomes):
    async def fake_submit(session, settings, urls, rotator=None):
        return {u: outcomes[u] for u in urls}

    monkeypatch.setattr(worker, "submit_urls", fake_submit)
    settings = get_settings()
    pending = await idx_repo.list_pending(10)
    claimed = [c for c in [await worker._claim(r, "worker-1") for r in pending] if c]
    await worker._process_batch(claimed, None, settings, None)


async def test_submit_process_and_status(db, monkeypatch):
    resp = await service.submit_batch("u", SubmitRequest(urls=["https://a.com/1", "https://b.com/2"]))
    assert resp.total == 2

    st = await service.get_batch_status("u", resp.batch_id)
    assert st.counts["pending"] == 2 and not st.done

    outcomes = {"https://a.com/1": "completed", "https://b.com/2": None}
    await run_once(monkeypatch, outcomes)  # attempt 1: b.com goes back to pending
    st = await service.get_batch_status("u", resp.batch_id)
    assert st.counts["completed"] == 1 and st.counts["pending"] == 1 and not st.done

    for _ in range(get_settings().MAX_ATTEMPTS):  # exhaust retries
        await run_once(monkeypatch, outcomes)
    st = await service.get_batch_status("u", resp.batch_id)
    assert st.counts == {"pending": 0, "processing": 0, "submitted": 0, "completed": 1, "failed": 1} and st.done


async def test_unknown_batch_raises(db):
    with pytest.raises(service.BatchNotFound):
        await service.get_batch_status("u", "nope")


async def test_stale_rows_recovered(db):
    db["x"] = {"id": "x", "batch_id": "b", "url": "https://a.com", "status": "processing", "attempts": 1, "locked_by": "dead"}
    db["y"] = {"id": "y", "batch_id": "b", "url": "https://a.com/2", "status": "processing", "attempts": 99, "locked_by": "dead"}
    assert await worker.recover_stale(get_settings()) == 2
    assert db["x"]["status"] == "pending" and db["x"]["locked_by"] is None
    assert db["y"]["status"] == "failed"


async def test_202_is_marked_submitted_not_completed(db, monkeypatch):
    resp = await service.submit_batch("u", SubmitRequest(urls=["https://a.com/1"]))
    await run_once(monkeypatch, {"https://a.com/1": "submitted"})
    st = await service.get_batch_status("u", resp.batch_id)
    assert st.counts["submitted"] == 1 and st.counts["completed"] == 0 and st.done
