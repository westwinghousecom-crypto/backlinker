"""Respect Google's URL Inspection quota: 2,000 per property per day and 600 per property per minute.

* The per-day counter lives in Appwrite and is incremented ATOMICALLY with a cap (``increment_row_column(max=...)``),
  so two workers or instances can never spend the same unit twice and a restart does not forget usage.
* Scheduled checks may use ``per_day - manual_reserve`` units; the rest is kept for customers pressing "Recheck".
* The per-minute window is in memory. It only spans 60 seconds; run ONE Google worker (see GOOGLE_SETUP.md) or accept
  that several instances could together exceed 600/minute, in which case Google's 429 pauses the property anyway.
* The quota day is assumed to roll over at midnight Pacific time. Google does not clearly document this for the URL
  Inspection API, so a 429 from Google ALWAYS wins: it blocks the property with an escalating delay
  (2 min, 10 min, 1 h, 6 h, 24 h) that resets after the next success.
* Limits belong to the Search Console PROPERTY, not to a QuickIndex customer, so counters are keyed by property.
"""
import asyncio
import hashlib
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")
ESCALATION = (timedelta(minutes=2), timedelta(minutes=10), timedelta(hours=1), timedelta(hours=6), timedelta(hours=24))


def quota_day(now: datetime) -> str:
    return now.astimezone(PACIFIC).strftime("%Y-%m-%d")


def next_reset(now: datetime) -> datetime:
    """The next midnight in Pacific time, as UTC."""
    local = now.astimezone(PACIFIC)
    midnight = datetime(local.year, local.month, local.day, tzinfo=PACIFIC) + timedelta(days=1)
    return midnight.astimezone(timezone.utc)


def counter_id(property_url: str, day: str) -> str:
    """Appwrite row id (<= 36 chars) for one property on one quota day."""
    return hashlib.sha1(property_url.encode()).hexdigest()[:20] + day.replace("-", "")


class CounterStore(Protocol):
    async def get(self, property_url: str, day: str) -> int: ...

    async def incr(self, property_url: str, day: str, limit: int) -> int | None:
        """Atomically add one unless that would exceed `limit`. Returns the new count, or None when the cap is reached."""


@dataclass
class Reservation:
    ok: bool
    reason: str | None = None  # "minute" | "day" | "blocked"
    retry_at: datetime | None = None


class QuotaGate:
    def __init__(self, per_minute: int, per_day: int, store: CounterStore, manual_reserve: int = 0,
                 clock=lambda: datetime.now(timezone.utc), monotonic=time.monotonic):
        self.per_minute, self.per_day, self.store = per_minute, per_day, store
        self.manual_reserve = max(min(manual_reserve, per_day), 0)
        self._clock, self._mono = clock, monotonic
        self._minute: dict[str, deque[float]] = defaultdict(deque)
        self._blocked: dict[str, datetime] = {}
        self._strikes: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()

    async def usage(self, prop: str) -> int:
        return await self.store.get(prop, quota_day(self._clock()))

    async def reserve(self, prop: str, manual: bool = False) -> Reservation:
        """Ask for permission to make ONE inspection call on `prop`. Counts it if granted."""
        async with self._lock:
            now, mono = self._clock(), self._mono()
            until = self._blocked.get(prop)
            if until and until > now:
                return Reservation(False, "blocked", until)
            window = self._minute[prop]
            while window and mono - window[0] >= 60:
                window.popleft()
            if len(window) >= self.per_minute:
                return Reservation(False, "minute", now + timedelta(seconds=60 - (mono - window[0]) + 1))
            limit = self.per_day if manual else self.per_day - self.manual_reserve
            if await self.store.incr(prop, quota_day(now), limit) is None:
                return Reservation(False, "day", next_reset(now))
            window.append(mono)
            return Reservation(True)

    def throttled(self, prop: str, retry_after: float | None = None) -> datetime:
        """Google answered 429/quota: block this property with an escalating delay (or Retry-After if longer)."""
        delay = ESCALATION[min(self._strikes[prop], len(ESCALATION) - 1)]
        self._strikes[prop] += 1
        if retry_after:
            delay = max(delay, timedelta(seconds=retry_after))
        until = self._clock() + delay
        self._blocked[prop] = until
        return until

    def succeeded(self, prop: str) -> None:
        self._strikes.pop(prop, None)

    def block_until(self, prop: str, when: datetime) -> None:
        self._blocked[prop] = when
