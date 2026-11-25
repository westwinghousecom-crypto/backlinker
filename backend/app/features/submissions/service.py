import logging
import uuid

from app.core.bulk import owner_permissions, row_id
from app.core.config import get_settings
from app.core.wakeup import wakeups
from app.features.submissions import repository
from app.features.submissions.schemas import (
    BatchStatus,
    BatchUrl,
    SubmitRequest,
    SubmitResponse,
)

log = logging.getLogger(__name__)

STATUSES = ("pending", "processing", "submitted", "completed", "failed")


class SubmissionError(Exception):
    pass


class QuotaExceeded(Exception):
    pass


class BatchNotFound(Exception):
    pass


async def submit_batch(user_id: str, req: SubmitRequest) -> SubmitResponse:
    """Queue URLs for the signed-in customer. ``user_id`` must come from the verified session."""
    limit = get_settings().MAX_QUEUED_PER_USER
    try:
        queued = await repository.count_queued(user_id)
    except Exception as e:
        raise SubmissionError(str(e))
    if queued + len(req.urls) > limit:
        raise QuotaExceeded(
            f"You have {queued:,} URLs waiting and can have at most {limit:,} queued at once. "
            "Wait for the current ones to finish."
        )

    batch_id = str(uuid.uuid4())
    perms = owner_permissions(user_id)
    rows = [
        {
            "$id": row_id(batch_id, i),
            "$permissions": perms,
            "batch_id": batch_id,
            "user_id": user_id,
            "url": url,
            "status": "pending",
            "attempts": 0,
            "locked_by": None,
        }
        for i, url in enumerate(req.urls)
    ]
    created, errors = await repository.create_url_rows(rows)
    if errors:
        log.error("%d/%d rows failed for batch %s: %s", len(errors), len(rows), batch_id, errors[0])
    if created == 0:
        raise SubmissionError(errors[0] if errors else "No rows created")
    wakeups.notify("indexing")  # workers sleep until told; no polling needed
    return SubmitResponse(batch_id=batch_id, total=created)


async def get_batch_status(user_id: str, batch_id: str) -> BatchStatus:
    try:
        rows = await repository.list_batch(batch_id, user_id)
    except Exception as e:
        raise SubmissionError(str(e))
    # Belt and braces: even if the repository filter were bypassed, other customers' rows are dropped.
    rows = [r for r in rows if r.get("user_id") == user_id]
    if not rows:
        raise BatchNotFound(batch_id)  # also what a stranger's batch id looks like: no hint it exists
    counts = {s: 0 for s in STATUSES}
    for r in rows:
        counts[r.get("status", "pending")] = counts.get(r.get("status", "pending"), 0) + 1
    return BatchStatus(
        batch_id=batch_id,
        total=len(rows),
        counts=counts,
        done=counts["pending"] == 0 and counts["processing"] == 0,
        urls=[BatchUrl(url=r["url"], status=r.get("status", "pending"), attempts=int(r.get("attempts") or 0)) for r in rows],
    )


async def recent_batches(user_id: str) -> list[dict]:
    try:
        rows = await repository.recent_batches(user_id)
    except Exception as e:
        raise SubmissionError(str(e))
    return [r for r in rows if r.get("batch_id")]
