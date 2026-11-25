"""When to inspect a URL: now, then 1, 3, 7 and 14 days after it was first tracked. Pure functions."""
from datetime import datetime, timedelta, timezone

OFFSETS_DAYS = (0, 1, 3, 7, 14)  # step i is due OFFSETS_DAYS[i] days after the URL was first tracked
MAX_ATTEMPTS = 4  # transient failures per scheduled check before the failure is recorded
RETRY_BASE = timedelta(minutes=15)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "+00:00")


def parse(value: str | datetime | None) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def due_at(started_at: datetime, step: int) -> datetime | None:
    """When scheduled check number `step` (0-based) is due, or None when the schedule is finished."""
    if step >= len(OFFSETS_DAYS):
        return None
    return started_at + timedelta(days=OFFSETS_DAYS[step])


def next_after_scheduled(started_at: datetime, steps_done: int, now: datetime, indexed: bool) -> tuple[int, datetime | None]:
    """After a scheduled inspection finished: (new steps_done, next due or None).

    Stops once Google confirms the page is indexed (no point spending quota; a manual recheck is always possible).
    A check that is already overdue is run as soon as possible, not skipped."""
    steps = steps_done + 1
    if indexed:
        return steps, None
    nxt = due_at(started_at, steps)
    return steps, (max(nxt, now) if nxt else None)


def next_after_manual(started_at: datetime, steps_done: int, now: datetime, indexed: bool) -> datetime | None:
    """A manual recheck does not use up a scheduled slot."""
    if indexed:
        return None
    nxt = due_at(started_at, steps_done)
    return max(nxt, now + timedelta(hours=1)) if nxt else None


def backoff(attempts: int) -> timedelta:
    """Delay before retrying a transient failure: 15 min, 30 min, 1 h, 2 h ..."""
    return RETRY_BASE * (2 ** max(attempts - 1, 0))
