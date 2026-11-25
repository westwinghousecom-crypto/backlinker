from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.auth import AuthUser, current_user, rate_limited_user
from app.features.diagnostics import service
from app.features.diagnostics.scanner import UrlCheck, check_urls
from app.features.diagnostics.schemas import (
    CheckBatch,
    CheckBatchCreated,
    CheckBatchRequest,
    CheckBatchSummaryRow,
    ManualGoogleMark,
    ManualGoogleRequest,
    ReportSharingState,
    ReportSharingUpdate,
)

router = APIRouter(prefix="/api/v1", tags=["diagnostics"])


class CheckRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=50)
    target: str | None = Field(default=None, description="Your site; the page must link to it")


def _db_error(e: Exception) -> HTTPException:
    return HTTPException(status_code=502, detail=f"Database error: {e}")


@router.post("/check", response_model=list[UrlCheck])
async def check(req: CheckRequest, user: AuthUser = Depends(rate_limited_user)) -> list[UrlCheck]:
    """Quick stateless check (max 50 URLs, nothing saved). For big or saved checks use /check-batches."""
    return await check_urls([u.strip() for u in req.urls if u.strip()], req.target)


@router.post("/check-batches", response_model=CheckBatchCreated)
async def create_check_batch(req: CheckBatchRequest, user: AuthUser = Depends(rate_limited_user)) -> CheckBatchCreated:
    try:
        return await service.create_batch(user.id, req)
    except service.QuotaExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))
    except service.CheckError as e:
        raise _db_error(e)


@router.get("/check-batches", response_model=list[CheckBatchSummaryRow])
async def check_history(limit: int = Query(20, ge=1, le=50), user: AuthUser = Depends(current_user)):
    """The signed-in customer's own batches. There is deliberately no user_id parameter."""
    try:
        return await service.list_history(user.id, limit)
    except service.CheckError as e:
        raise _db_error(e)


@router.get("/check-batches/{batch_id}", response_model=CheckBatch)
async def get_check_batch(batch_id: str, user: AuthUser = Depends(current_user)) -> CheckBatch:
    try:
        return await service.get_batch(user.id, batch_id)
    except service.NotFound:
        raise HTTPException(status_code=404, detail="Batch not found")
    except service.CheckError as e:
        raise _db_error(e)


@router.post("/check-batches/{batch_id}/checks/{check_id}/recheck", status_code=202)
async def recheck(batch_id: str, check_id: str, user: AuthUser = Depends(rate_limited_user)) -> dict[str, str]:
    try:
        await service.recheck(user.id, batch_id, check_id)
    except service.NotFound:
        raise HTTPException(status_code=404, detail="Check not found")
    except service.CheckError as e:
        raise _db_error(e)
    return {"status": "queued"}


@router.put("/check-batches/{batch_id}/checks/{check_id}/manual-google", response_model=ManualGoogleMark)
async def mark_manual_google(
    batch_id: str, check_id: str, req: ManualGoogleRequest, user: AuthUser = Depends(rate_limited_user)
) -> ManualGoogleMark:
    """Save the customer's own note from searching Google themselves ("appears" / "not_found" / "clear")."""
    try:
        return await service.set_manual_google(user.id, batch_id, check_id, req.result)
    except service.NotFound:
        raise HTTPException(status_code=404, detail="Check not found")
    except service.CheckError as e:
        raise _db_error(e)


@router.get("/check-batches/{batch_id}/sharing", response_model=ReportSharingState)
async def get_report_sharing(batch_id: str, user: AuthUser = Depends(current_user)) -> ReportSharingState:
    try:
        return await service.get_sharing(user.id, batch_id)
    except service.NotFound:
        raise HTTPException(status_code=404, detail="Batch not found")
    except service.CheckError as e:
        raise _db_error(e)


@router.put("/check-batches/{batch_id}/sharing", response_model=ReportSharingState)
async def set_report_sharing(
    batch_id: str, req: ReportSharingUpdate, user: AuthUser = Depends(rate_limited_user)
) -> ReportSharingState:
    """Owner's opt-in for a read-only, no-sign-in link to this batch's results (e.g. to show a client)."""
    try:
        return await service.set_sharing(user.id, batch_id, req.public_report)
    except service.NotFound:
        raise HTTPException(status_code=404, detail="Batch not found")
    except service.CheckError as e:
        raise _db_error(e)


@router.get("/check-batches/{batch_id}/public", response_model=CheckBatch)
async def get_public_check_batch(batch_id: str) -> CheckBatch:
    """No sign-in. Only returns a batch whose owner explicitly turned sharing on; same 404 either way, so this can
    never be used to learn whether a given batch id exists."""
    try:
        return await service.get_public_batch(batch_id)
    except service.NotFound:
        raise HTTPException(status_code=404, detail="Batch not found")
    except service.CheckError as e:
        raise _db_error(e)


@router.delete("/check-batches/{batch_id}", status_code=204)
async def delete_check_batch(batch_id: str, user: AuthUser = Depends(rate_limited_user)) -> None:
    try:
        await service.delete_batch(user.id, batch_id)
    except service.NotFound:
        raise HTTPException(status_code=404, detail="Batch not found")
    except service.CheckError as e:
        raise _db_error(e)
