import time
from collections import defaultdict, deque

_hits: dict[str, deque[float]] = defaultdict(deque)


def check_rate_limit(key: str, limit: int, window: float = 60.0, now: float | None = None) -> bool:
    """Sliding-window limiter (in-memory, per process). Returns True if allowed."""
    now = time.monotonic() if now is None else now
    q = _hits[key]
    while q and now - q[0] >= window:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    return True
