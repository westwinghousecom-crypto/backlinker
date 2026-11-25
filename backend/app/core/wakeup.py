"""In-process wake-up signals and worker heartbeats.

Why: the queue workers used to poll Appwrite every few seconds even when nothing was queued, which cost about 690,000 read
requests per 30 days for an IDLE server (Appwrite Free allows 500,000). The workers run in the same process as the API, so the code
that creates work can simply tell them. Workers now sleep until they are woken, with a slow fallback poll
(``WORKER_FALLBACK_POLL_SECONDS``, default 240 s) that is the safety net for:
  * work created by another process or by a restart (rows already 'pending' are found by the first poll after startup),
  * rows whose retry time arrived while the worker was idle (scheduled Google rechecks),
  * stale 'processing' rows left by a crash (recovered on every wake-up).

A notification can never be lost: if it arrives while a worker is busy, a flag stays set and the next ``wait`` returns at once.
Call ``notify`` from the event loop (async request handlers and services), not from threads.
"""
import asyncio
import time
from collections import defaultdict


class Wakeups:
    def __init__(self) -> None:
        self._pending: dict[str, bool] = defaultdict(bool)
        self._waiters: dict[str, set[asyncio.Future]] = defaultdict(set)

    def notify(self, queue: str) -> None:
        self._pending[queue] = True
        for fut in list(self._waiters[queue]):
            if not fut.done():
                fut.set_result(None)

    async def wait(self, queue: str, timeout: float) -> bool:
        """Sleep until `queue` is notified or `timeout` passes. True if woken by a signal, False on timeout."""
        if self._pending[queue]:
            self._pending[queue] = False
            return True
        fut = asyncio.get_running_loop().create_future()
        self._waiters[queue].add(fut)
        try:
            await asyncio.wait_for(fut, timeout)
            self._pending[queue] = False
            return True
        except asyncio.TimeoutError:
            return False
        finally:
            self._waiters[queue].discard(fut)


class Heartbeats:
    """Each worker records that it is alive, what it is doing and when it should next report."""

    def __init__(self) -> None:
        self._beats: dict[str, dict] = {}

    def beat(self, name: str, state: str, stale_after: float, processed: int = 0) -> None:
        prev = self._beats.get(name, {"processed": 0})
        self._beats[name] = {"state": state, "at": time.monotonic(), "stale_after": stale_after,
                             "processed": prev["processed"] + processed}

    def remove(self, name: str) -> None:
        self._beats.pop(name, None)

    def snapshot(self) -> dict[str, dict]:
        now = time.monotonic()
        return {n: {"state": b["state"], "age_seconds": round(now - b["at"], 1), "processed": b["processed"],
                    "alive": now - b["at"] <= b["stale_after"]} for n, b in self._beats.items()}

    def clear(self) -> None:
        self._beats.clear()


wakeups = Wakeups()
heartbeats = Heartbeats()
