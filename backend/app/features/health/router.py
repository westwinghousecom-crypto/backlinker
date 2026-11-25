"""Health endpoints.

* ``/health/live``  : the process is up. Depends on nothing, so a slow database can never make an orchestrator kill a healthy API.
* ``/health/ready`` : the app can do its job: Appwrite is reachable AND every worker that should be running has reported in.
                      Returns 503 otherwise. The Appwrite check is cached (``DEPENDENCY_TTL``) so an uptime monitor that calls
                      this every minute costs a handful of reads a day, not thousands.
* ``/health``       : kept for compatibility, same as live.
Worker heartbeats come from app.core.wakeup: an API can be healthy while its worker loop is stuck, so they are reported separately.
"""
import asyncio
import time

from fastapi import APIRouter, Response

from app.core.config import get_settings
from app.core.usage import usage
from app.core.wakeup import heartbeats

router = APIRouter(tags=["health"])

STARTED = time.monotonic()
STARTUP_GRACE = 90.0  # workers get this long after process start to report their first heartbeat
DEPENDENCY_TTL = 300.0

_dependency: tuple[float, bool, str] | None = None  # (checked_at, ok, detail)


def reset_cache() -> None:
    global _dependency
    _dependency = None


def _probe_appwrite() -> None:
    from appwrite.query import Query

    from app.core.appwrite_client import get_tables_db

    s = get_settings()
    get_tables_db().list_rows(database_id=s.APPWRITE_DATABASE_ID, table_id=s.APPWRITE_URLS_TABLE_ID, queries=[Query.limit(1)])


async def appwrite_status() -> tuple[bool, str, bool]:
    """(ok, detail, from_cache). One real read at most every DEPENDENCY_TTL seconds."""
    global _dependency
    now = time.monotonic()
    if _dependency and now - _dependency[0] < DEPENDENCY_TTL:
        return _dependency[1], _dependency[2], True
    try:
        await asyncio.wait_for(asyncio.to_thread(_probe_appwrite), 10)
        _dependency = (now, True, "reachable")
    except Exception as e:  # never leak details: type and Appwrite's HTTP code only
        _dependency = (now, False, f"unreachable ({getattr(e, 'code', None) or type(e).__name__})")
    return _dependency[1], _dependency[2], False


def expected_workers() -> list[str]:
    s = get_settings()
    names = [f"worker-{i + 1}" for i in range(max(s.WORKER_COUNT, 0))]
    names += [f"check-worker-{i + 1}" for i in range(max(s.CHECK_WORKER_COUNT, 0))]
    if s.google_configured:
        names += [f"gsc-worker-{i + 1}" for i in range(max(s.GSC_WORKER_COUNT, 0))]
    return names


def worker_status() -> tuple[bool, dict]:
    beats = heartbeats.snapshot()
    in_grace = time.monotonic() - STARTED < STARTUP_GRACE
    detail, ok = {}, True
    for name in expected_workers():
        b = beats.get(name)
        if b is None:
            detail[name] = {"state": "not started yet" if in_grace else "missing", "alive": in_grace}
            ok = ok and in_grace
        else:
            detail[name] = b
            ok = ok and b["alive"]
    return ok, detail


@router.get("/health")
@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def ready(response: Response) -> dict:
    db_ok, db_detail, cached = await appwrite_status()
    workers_ok, workers = worker_status()
    ok = db_ok and workers_ok
    response.status_code = 200 if ok else 503
    response.headers["Cache-Control"] = "no-store"
    return {
        "status": "ready" if ok else "not_ready",
        "checks": {
            "appwrite": {"ok": db_ok, "detail": db_detail, "cached": cached},
            "workers": {"ok": workers_ok, "workers": workers},
        },
        # Exact Appwrite request counts made by this process since start (reads include list and get; writes count rows).
        "appwrite_requests": usage.snapshot(),
    }
