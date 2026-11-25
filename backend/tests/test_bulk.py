import re

import pytest
from appwrite.exception import AppwriteException

from app.core import bulk
from app.core.config import get_settings

ROW_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,35}$")  # Appwrite's rule: <=36 chars, not starting special


class FakeTables:
    def __init__(self, fail_bulk_on=(), fail_single=(), preexisting=()):
        self.bulk_sizes: list[int] = []
        self.singles: list[str] = []
        self.stored: dict[str, dict] = {}
        self.fail_bulk_on = set(fail_bulk_on)  # indexes of bulk calls that raise
        self.fail_single = set(fail_single)  # row ids whose single insert raises a 500
        self.preexisting = set(preexisting)  # row ids that a failed bulk call already stored
        self.calls = 0

    def create_rows(self, database_id, table_id, rows):
        n = self.calls
        self.calls += 1
        self.bulk_sizes.append(len(rows))
        if n in self.fail_bulk_on:
            for r in rows:
                if r["$id"] in self.preexisting:
                    self.stored[r["$id"]] = r
            raise AppwriteException("bulk failed", 500)
        for r in rows:
            self.stored[r["$id"]] = r

    def create_row(self, database_id, table_id, row_id, data, permissions=None):
        self.singles.append(row_id)
        if row_id in self.fail_single:
            raise AppwriteException("boom", 500)
        if row_id in self.stored:
            raise AppwriteException("exists", 409)
        self.stored[row_id] = {"$id": row_id, "$permissions": permissions, **data}


def make_rows(n, batch_id="3f2b8c1e-aaaa-bbbb-cccc-1234567890ab"):
    perms = bulk.owner_permissions("user-1")
    return [{"$id": bulk.row_id(batch_id, i), "$permissions": perms, "url": f"https://x.example/{i}"} for i in range(n)]


@pytest.fixture(autouse=True)
def fresh_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def tables(monkeypatch):
    def install(**kw):
        t = FakeTables(**kw)
        monkeypatch.setattr(bulk, "get_tables_db", lambda: t)
        return t

    return install


def test_row_ids_are_valid_unique_and_deterministic():
    ids = [bulk.row_id("3f2b8c1e-aaaa-bbbb-cccc-1234567890ab", i) for i in range(0, 1000)]
    assert len(set(ids)) == 1000 and all(ROW_ID.match(i) for i in ids)
    assert ids == [bulk.row_id("3f2b8c1e-aaaa-bbbb-cccc-1234567890ab", i) for i in range(1000)]
    assert bulk.row_id("3f2b8c1e-aaaa-bbbb-cccc-1234567890ab", 9_999_999).__len__() == 35
    assert bulk.row_id("aaaa", 0) != bulk.row_id("bbbb", 0)


def test_only_the_owner_gets_read_permission():
    assert bulk.owner_permissions("user-1") == ['read("user:user-1")']


async def test_rows_are_sent_in_chunks_within_the_plan_limit(tables):
    t = tables()
    created, errors = await bulk.bulk_create("urls", make_rows(250), size=100)
    assert (created, errors) == (250, [])
    assert sorted(t.bulk_sizes) == [50, 100, 100]  # 3 requests instead of 250
    assert t.singles == []
    assert all(r["$permissions"] == ['read("user:user-1")'] for r in t.stored.values())


async def test_default_chunk_is_the_free_plan_limit_and_is_capped_at_pro(monkeypatch, tables):
    t = tables()
    assert bulk.chunk_size() == 100
    monkeypatch.setenv("APPWRITE_BULK_CHUNK_SIZE", "1000")
    get_settings.cache_clear()
    assert bulk.chunk_size() == 1000
    monkeypatch.setenv("APPWRITE_BULK_CHUNK_SIZE", "5000")
    get_settings.cache_clear()
    assert bulk.chunk_size() == 1000  # never above Appwrite's highest plan limit
    monkeypatch.setenv("APPWRITE_BULK_CHUNK_SIZE", "0")
    get_settings.cache_clear()
    assert bulk.chunk_size() == 1
    monkeypatch.delenv("APPWRITE_BULK_CHUNK_SIZE")
    get_settings.cache_clear()
    created, _ = await bulk.bulk_create("urls", make_rows(1000))
    assert created == 1000 and max(t.bulk_sizes) == 100


async def test_a_failed_bulk_call_falls_back_to_row_by_row(tables):
    t = tables(fail_bulk_on={1})
    created, errors = await bulk.bulk_create("urls", make_rows(300), size=100)
    assert created == 300 and errors == []
    assert len(t.singles) == 100 and len(t.stored) == 300


async def test_rows_stored_by_a_failed_bulk_call_are_not_duplicated_or_lost(tables):
    rows = make_rows(100)
    already = {r["$id"] for r in rows[:40]}  # the failed call had stored the first 40
    t = tables(fail_bulk_on={0}, preexisting=already)
    created, errors = await bulk.bulk_create("urls", rows, size=100)
    assert created == 100 and errors == []  # 409 means "already there": counted, not an error
    assert len(t.stored) == 100


async def test_partial_failures_are_reported_not_hidden(tables):
    rows = make_rows(100)
    bad = {rows[3]["$id"], rows[77]["$id"]}
    t = tables(fail_bulk_on={0}, fail_single=bad)
    created, errors = await bulk.bulk_create("urls", rows, size=100)
    assert created == 98 and len(errors) == 2
    assert not (bad & set(t.stored))


async def test_submit_flow_uses_bulk_insert_and_reports_partial_creation(monkeypatch, tables):
    from app.features.submissions import repository, service
    from app.features.submissions.schemas import SubmitRequest

    t = tables()

    async def no_queue(user_id):
        return 0

    monkeypatch.setattr(repository, "count_queued", no_queue)
    urls = [f"https://site.example/page-{i}" for i in range(230)]
    res = await service.submit_batch("user-1", SubmitRequest(urls=urls + urls[:10]))  # 10 duplicates removed
    assert res.total == 230 and sorted(t.bulk_sizes) == [30, 100, 100]
    assert {r["user_id"] for r in t.stored.values()} == {"user-1"}
    assert {r["status"] for r in t.stored.values()} == {"pending"}

    # every row failing -> an error, not a silent empty batch
    t2 = tables(fail_bulk_on=set(range(10)), fail_single={r for r in {bulk.row_id(res.batch_id, i) for i in range(5)}})

    async def all_fail(table_id, rows, size=None):
        return 0, ["db down"]

    monkeypatch.setattr(repository, "bulk_create", all_fail)
    with pytest.raises(service.SubmissionError):
        await service.submit_batch("user-1", SubmitRequest(urls=["https://a.example/"]))
    assert t2 is not None
