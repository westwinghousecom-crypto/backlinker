"""Counts the Appwrite database calls this process makes, so usage can be measured instead of guessed.

Appwrite's plans meter database reads and writes (Free: 500,000 reads and 250,000 writes per month at the time of writing).
Every TablesDB call made through ``get_tables_db()`` is tallied here. A read is a list/get request; a write is a create,
update, delete or increment (``create_rows`` counts one write per row, as Appwrite meters it). Appwrite's own meter may
count rows returned by a list as separate reads, so these numbers are REQUESTS, a lower bound on what is billed.
"""
import threading
import time
from collections import Counter
from functools import wraps

READS = ("list_rows", "get_row")
WRITES = ("create_row", "create_rows", "update_row", "update_rows", "upsert_row", "delete_row", "delete_rows",
          "increment_row_column", "decrement_row_column")


class UsageCounter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls: Counter[str] = Counter()
        self.reads = 0
        self.writes = 0
        self.started = time.monotonic()

    def record(self, name: str, weight: int = 1) -> None:
        with self._lock:
            self.calls[name] += weight
            if name in READS:
                self.reads += weight
            elif name in WRITES:
                self.writes += weight

    def reset(self) -> None:
        with self._lock:
            self.calls.clear()
            self.reads = self.writes = 0
            self.started = time.monotonic()

    def snapshot(self) -> dict:
        with self._lock:
            return {"seconds": round(time.monotonic() - self.started, 1), "reads": self.reads, "writes": self.writes,
                    "by_call": dict(self.calls)}


usage = UsageCounter()


def instrument(tables_db):
    """Wrap a TablesDB instance so each call is counted. Behaviour is unchanged."""
    for name in (*READS, *WRITES):
        original = getattr(tables_db, name, None)
        if original is None:
            continue

        def make(orig, call_name):
            @wraps(orig)
            def wrapper(*args, **kwargs):
                weight = len(kwargs.get("rows") or []) if call_name == "create_rows" else 1
                usage.record(call_name, max(weight, 1))
                return orig(*args, **kwargs)

            return wrapper

        setattr(tables_db, name, make(original, name))
    return tables_db
