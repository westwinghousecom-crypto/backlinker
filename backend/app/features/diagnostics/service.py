import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.features.diagnostics import repository
from app.features.diagnostics.schemas import (
    CheckBatch,
    CheckBatchCreated,
    CheckBatchRequest,
    CheckBatchSummaryRow,
    CheckItem,
    CheckSummary,
    ManualGoogleMark,
    ReportSharingState,
)
from app.features.diagnostics.scanner import UrlCheck
from app.core.bulk import owner_permissions, row_id
from app.core.config import get_settings
from app.core.wakeup import wakeups
from app.features.submissions.schemas import SubmitRequest

log = logging.getLogger(__name__)


class CheckError(Exception):
    pass


class NotFound(Exception):
    pass


class QuotaExceeded(Exception):
    pass


async def _owned_batch(user_id: str, batch_id: str) -> dict[str, Any]:
    """The batch row, but only if it belongs to `user_id`. Anyone else gets NotFound (not Forbidden: no hint it exists)."""
    batch = await repository.get_batch(batch_id)
    if batch is None or batch.get("user_id") != user_id:
        raise NotFound(batch_id)
    return batch


def parse_result(raw: str | None) -> UrlCheck | None:
    if not raw:
        return None
    try:
        return UrlCheck.model_validate(json.loads(raw))
    except Exception:
        log.warning("Unreadable stored check result")
        return None


def summarize(items: list[CheckItem], total: int) -> CheckSummary:
    done = [i.result for i in items if i.state == "done" and i.result]
    return CheckSummary(
        total=total,
        checked=len(done),
        eligible=sum(r.verdict == "eligible" for r in done),
        with_problems=sum(r.verdict != "eligible" for r in done),
        blocked=sum(r.verdict == "blocked" for r in done),
        warnings=sum(r.verdict == "warning" for r in done),
        unreachable=sum(r.verdict == "unreachable" for r in done),
        backlinks_found=sum(r.backlink_found is True for r in done),
        backlinks_missing=sum(r.backlink_found is False for r in done),
        done=len(done) >= total,
    )


async def create_batch(user_id: str, req: CheckBatchRequest) -> CheckBatchCreated:
    # Reuse the existing URL cleaning/validation/dedupe rules from the submit flow.
    urls = SubmitRequest(urls=req.urls).urls
    limit = get_settings().MAX_QUEUED_PER_USER
    try:
        queued = await repository.count_queued(user_id)
    except Exception as e:
        raise CheckError(str(e))
    if queued + len(urls) > limit:
        raise QuotaExceeded(
            f"You have {queued:,} checks waiting and can have at most {limit:,} queued at once. "
            "Wait for the current ones to finish."
        )
    batch_id = str(uuid.uuid4())
    perms = owner_permissions(user_id)
    try:
        await repository.create_batch(batch_id, user_id, req.target, len(urls))
        rows = [
            {
                "$id": row_id(batch_id, i), "$permissions": perms,
                "batch_id": batch_id, "user_id": user_id, "position": i, "url": u,
                "target": req.target, "status": "pending", "attempts": 0,
            }
            for i, u in enumerate(urls)
        ]
        created = await repository.create_checks(rows)
    except Exception as e:
        log.exception("Creating check batch %s failed", batch_id)
        await _discard(batch_id)
        raise CheckError(str(e))
    wakeups.notify("checks")
    return CheckBatchCreated(batch_id=batch_id, total=created)


async def _discard(batch_id: str) -> None:
    try:
        if await repository.count_checks(batch_id) == 0:
            await repository.delete_batch(batch_id)
        else:
            await repository.update_batch_total(batch_id, await repository.count_checks(batch_id))
    except Exception:
        log.exception("Cleanup of batch %s failed", batch_id)


async def get_batch(user_id: str, batch_id: str) -> CheckBatch:
    try:
        batch = await _owned_batch(user_id, batch_id)
        rows = await repository.list_checks(batch_id)
    except NotFound:
        raise
    except Exception as e:
        raise CheckError(str(e))
    rows = [r for r in rows if r.get("user_id") == user_id]  # belt and braces
    items = [
        CheckItem(
            id=r["id"],
            position=int(r.get("position") or 0),
            url=r["url"],
            state="done" if r.get("status") == "done" else ("processing" if r.get("status") == "processing" else "pending"),
            result=parse_result(r.get("result")),
            manual_google=r["manual_google"] if r.get("manual_google") in ("appears", "not_found") else None,
            manual_google_at=r.get("manual_google_at") if r.get("manual_google") in ("appears", "not_found") else None,
        )
        for r in rows
    ]
    total = int(batch.get("total") or len(items))
    return CheckBatch(
        batch_id=batch_id,
        target=batch.get("target"),
        created_at=batch.get("created_at"),
        summary=summarize(items, total),
        items=items,
    )


async def list_history(user_id: str, limit: int = 20) -> list[CheckBatchSummaryRow]:
    try:
        batches = await repository.list_batches(user_id, limit)
        counts = await asyncio.gather(*(repository.count_checks(b["id"], "done") for b in batches))
    except Exception as e:
        raise CheckError(str(e))
    return [
        CheckBatchSummaryRow(
            batch_id=b["id"], target=b.get("target"), created_at=b.get("created_at"),
            total=int(b.get("total") or 0), checked=c,
        )
        for b, c in zip(batches, counts)
    ]


async def recheck(user_id: str, batch_id: str, check_id: str) -> None:
    try:
        await _owned_batch(user_id, batch_id)
        row: dict[str, Any] = await repository.get_check(check_id)
    except NotFound:
        raise
    except Exception:
        raise NotFound(check_id)
    if row.get("batch_id") != batch_id or row.get("user_id") != user_id:
        raise NotFound(check_id)
    if row.get("status") == "processing":
        return  # already being rechecked
    try:
        await repository.update_check(
            check_id, {"status": "pending", "attempts": 0, "locked_by": None, "verdict": None, "result": None}
        )
    except Exception as e:
        raise CheckError(str(e))
    wakeups.notify("checks")


async def set_manual_google(user_id: str, batch_id: str, check_id: str, result: str) -> ManualGoogleMark:
    """Record (or clear) what the customer saw when they searched Google themselves. Owner only; 404 for anyone else's ids."""
    try:
        await _owned_batch(user_id, batch_id)
        row: dict[str, Any] = await repository.get_check(check_id)
    except NotFound:
        raise
    except Exception:
        raise NotFound(check_id)
    if row.get("batch_id") != batch_id or row.get("user_id") != user_id:
        raise NotFound(check_id)
    mark = None if result == "clear" else result
    at = None if mark is None else datetime.now(timezone.utc).isoformat()
    try:
        await repository.update_check(check_id, {"manual_google": mark, "manual_google_at": at})
    except Exception as e:
        raise CheckError(str(e))
    return ManualGoogleMark(manual_google=mark, manual_google_at=at)


def _report_url(batch_id: str, public: bool) -> str | None:
    if not public:
        return None
    base = get_settings().FRONTEND_URL.rstrip("/")
    return f"{base}/report/{batch_id}"


async def get_sharing(user_id: str, batch_id: str) -> ReportSharingState:
    """Owner only; 404 for anyone else (same pattern as every other owner check in this file)."""
    try:
        batch = await _owned_batch(user_id, batch_id)
    except NotFound:
        raise
    except Exception as e:
        raise CheckError(str(e))
    public = bool(batch.get("public_report"))
    return ReportSharingState(public_report=public, public_url=_report_url(batch_id, public))


async def set_sharing(user_id: str, batch_id: str, public: bool) -> ReportSharingState:
    try:
        await _owned_batch(user_id, batch_id)
    except NotFound:
        raise
    except Exception as e:
        raise CheckError(str(e))
    try:
        await repository.set_public_report(batch_id, public)
    except Exception as e:
        raise CheckError(str(e))
    return ReportSharingState(public_report=public, public_url=_report_url(batch_id, public))


async def get_public_batch(batch_id: str) -> CheckBatch:
    """No user_id, no auth: this is the link a customer shares with their own client. Raises NotFound, with the SAME
    message, whether the batch does not exist or simply is not public -- a 404 here must never reveal that a private
    batch exists. The self-reported "I searched Google myself" note is the batch owner's private note and must never
    reach a third party who did not write it, so it is always stripped from this view regardless of what is stored."""
    try:
        batch = await repository.get_batch(batch_id)
    except Exception as e:
        raise CheckError(str(e))
    if batch is None or not batch.get("public_report"):
        raise NotFound(batch_id)
    try:
        rows = await repository.list_checks(batch_id)
    except Exception as e:
        raise CheckError(str(e))
    items = [
        CheckItem(
            id=r["id"],
            position=int(r.get("position") or 0),
            url=r["url"],
            state="done" if r.get("status") == "done" else ("processing" if r.get("status") == "processing" else "pending"),
            result=parse_result(r.get("result")),
            manual_google=None,  # stripped: a private, self-reported note the batch owner wrote for themselves
            manual_google_at=None,
        )
        for r in rows
    ]
    total = int(batch.get("total") or len(items))
    return CheckBatch(
        batch_id=batch_id,
        target=batch.get("target"),
        created_at=batch.get("created_at"),
        summary=summarize(items, total),
        items=items,
    )


async def delete_batch(user_id: str, batch_id: str) -> None:
    try:
        await _owned_batch(user_id, batch_id)
        await repository.delete_checks(batch_id)
        await repository.delete_batch(batch_id)
    except NotFound:
        raise
    except Exception as e:
        raise CheckError(str(e))
