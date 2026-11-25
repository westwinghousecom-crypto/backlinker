from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ValidationError

from app.core.auth import AuthUser, current_user, rate_limited_user
from app.core.config import get_settings
from app.features.discovery import repository as feed_repo
from app.features.discovery import router as feeds
from app.features.discovery import sharing
from app.features.submissions import repository, service
from app.features.submissions.schemas import (
    BatchStatus,
    RecentBatch,
    SubmitOneRequest,
    SubmitRequest,
    SubmitResponse,
)

router = APIRouter(prefix="/api/v1", tags=["submissions"])


async def _submit(user: AuthUser, req: SubmitRequest) -> SubmitResponse:
    try:
        return await service.submit_batch(user.id, req)
    except service.QuotaExceeded as e:
        raise HTTPException(status_code=429, detail=str(e))
    except service.SubmissionError as e:
        raise HTTPException(status_code=502, detail=f"Database error: {e}")


@router.post("/submit", response_model=SubmitResponse)
async def submit(req: SubmitRequest, user: AuthUser = Depends(rate_limited_user)) -> SubmitResponse:
    return await _submit(user, req)


@router.post("/submit-one", response_model=SubmitResponse)
async def submit_one(req: SubmitOneRequest, user: AuthUser = Depends(rate_limited_user)) -> SubmitResponse:
    try:
        batch = SubmitRequest(urls=[req.url])
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()[0]["msg"].removeprefix("Value error, "))
    return await _submit(user, batch)


@router.get("/batches", response_model=list[RecentBatch])
async def recent_batches(user: AuthUser = Depends(current_user)) -> list[RecentBatch]:
    """The signed-in customer's own recent submission batches. There is deliberately no user_id parameter."""
    try:
        return [RecentBatch(**r) for r in await service.recent_batches(user.id)]
    except service.SubmissionError as e:
        raise HTTPException(status_code=502, detail=f"Database error: {e}")


@router.get("/batches/{batch_id}", response_model=BatchStatus)
async def batch_status(batch_id: str, user: AuthUser = Depends(current_user)) -> BatchStatus:
    try:
        return await service.get_batch_status(user.id, batch_id)
    except service.BatchNotFound:
        raise HTTPException(status_code=404, detail="Batch not found")
    except service.SubmissionError as e:
        raise HTTPException(status_code=502, detail=f"Database error: {e}")


# ---------------------------------------------------------------------------- feeds and sharing (owner only)

PRIVATE_HEADERS = {"Cache-Control": "private, no-store"}


class SharingState(BaseModel):
    public_feed: bool
    public_url: str | None = None


class SharingUpdate(BaseModel):
    public_feed: bool


async def _owned(user: AuthUser, batch_id: str) -> None:
    try:
        owns = await repository.batch_exists(batch_id, user.id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Database error: {e}")
    if not owns:
        raise HTTPException(status_code=404, detail="Batch not found")


def _state(batch_id: str, public: bool) -> SharingState:
    base = get_settings().PUBLIC_BASE_URL.rstrip("/")
    return SharingState(public_feed=public, public_url=f"{base}/batches/{batch_id}/feed.xml" if public else None)


@router.get("/batches/{batch_id}/sharing", response_model=SharingState)
async def get_sharing(batch_id: str, user: AuthUser = Depends(current_user)) -> SharingState:
    await _owned(user, batch_id)
    return _state(batch_id, await sharing.is_public(batch_id))


@router.put("/batches/{batch_id}/sharing", response_model=SharingState)
async def set_sharing(batch_id: str, body: SharingUpdate, user: AuthUser = Depends(rate_limited_user)) -> SharingState:
    await _owned(user, batch_id)
    try:
        await sharing.set_public(batch_id, user.id, body.public_feed)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Database error: {e}")
    return _state(batch_id, body.public_feed)


@router.get("/batches/{batch_id}/feed.xml")
async def private_feed(batch_id: str, user: AuthUser = Depends(current_user)) -> Response:
    """The owner's own feed, always available to them and never cached by anyone else."""
    await _owned(user, batch_id)
    rows = await feed_repo.list_published(feeds.FEED_LIMIT, batch_id)
    return Response(feeds.build_batch_feed(rows, batch_id), media_type="application/rss+xml", headers=PRIVATE_HEADERS)


@router.get("/batches/{batch_id}/sitemap.xml")
async def private_sitemap(batch_id: str, user: AuthUser = Depends(current_user)) -> Response:
    await _owned(user, batch_id)
    rows = await feed_repo.list_published(feeds.SITEMAP_LIMIT, batch_id)
    return Response(feeds.build_batch_sitemap(rows), media_type="application/xml", headers=PRIVATE_HEADERS)
