from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.core.auth import AuthUser, current_user, rate_limited_user
from app.core.config import get_settings
from app.features.google import service
from app.features.google.service import GoogleError

router = APIRouter(prefix="/api/v1/google", tags=["google"])


def _raise(e: GoogleError) -> HTTPException:
    return HTTPException(status_code=e.status, detail={"code": e.code, "message": e.message})


class ConnectRequest(BaseModel):
    write: bool = False


class PropertyRequest(BaseModel):
    site_url: str = Field(min_length=1, max_length=512)


class TargetsRequest(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=200)


class SitemapRequest(BaseModel):
    url: str = Field(min_length=1, max_length=2048)


@router.get("/status")
async def status(user: AuthUser = Depends(current_user)) -> dict:
    return await service.get_status(user.id)


BINDING_COOKIE = "qi_oauth_binding"


@router.post("/connect")
async def connect(body: ConnectRequest, response: Response, user: AuthUser = Depends(rate_limited_user)) -> dict:
    """Returns the Google consent URL. The browser then navigates to it (the API cannot redirect an authenticated XHR).

    A random secret is also set as an HttpOnly cookie that only the callback path receives. The callback accepts the
    returned state only from the browser holding that cookie, so a leaked or forged state is useless to anyone else.
    The app and the API must be same-site (for example app.example.com and api.example.com)."""
    try:
        url, binding = service.begin_connect(user.id, body.write)
    except GoogleError as e:
        raise _raise(e)
    https = get_settings().FRONTEND_URL.lower().startswith("https")
    response.set_cookie(BINDING_COOKIE, binding, max_age=600, httponly=True, samesite="lax", secure=https,
                        path="/api/v1/google/callback")
    response.headers["Cache-Control"] = "no-store"
    return {"authorization_url": url}


@router.get("/callback", include_in_schema=False)
async def callback(code: str | None = None, state: str | None = None, error: str | None = None,
                   qi_oauth_binding: str | None = Cookie(default=None)) -> RedirectResponse:
    """Where Google sends the browser back. No token is available here, so identity comes ONLY from the sealed state.
    The redirect target is fixed configuration plus a short result code; nothing from the request is reflected."""
    result = await service.complete_callback(code, state, error, qi_oauth_binding)
    base = f"{get_settings().FRONTEND_URL.rstrip('/')}/dashboard/google"
    target = f"{base}?connected=1" if result == "connected" else f"{base}?google_error={result}"
    redirect = RedirectResponse(target, status_code=303, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})
    redirect.delete_cookie(BINDING_COOKIE, path="/api/v1/google/callback")  # the binding is one-time too
    return redirect


@router.delete("/connection", status_code=204)
async def disconnect(user: AuthUser = Depends(rate_limited_user)) -> None:
    await service.disconnect(user.id)


@router.delete("/data", status_code=204)
async def delete_data(user: AuthUser = Depends(rate_limited_user)) -> None:
    """Disconnect Google AND delete this customer's tracked URLs and inspection history."""
    await service.delete_all_data(user.id)


@router.get("/properties")
async def properties(user: AuthUser = Depends(current_user)) -> dict:
    try:
        return {"properties": [p.as_dict() for p in await service.list_properties(user.id)]}
    except GoogleError as e:
        raise _raise(e)


@router.put("/property")
async def select_property(body: PropertyRequest, user: AuthUser = Depends(rate_limited_user)) -> dict:
    try:
        return {"selected_property": await service.select_property(user.id, body.site_url)}
    except GoogleError as e:
        raise _raise(e)


@router.get("/targets")
async def targets(user: AuthUser = Depends(current_user)) -> dict:
    return {"items": await service.list_targets(user.id)}


@router.post("/targets")
async def add_targets(body: TargetsRequest, user: AuthUser = Depends(rate_limited_user)) -> dict:
    try:
        return await service.add_targets(user.id, body.urls)
    except GoogleError as e:
        raise _raise(e)


@router.get("/targets/{target_id}/history")
async def target_history(target_id: str, user: AuthUser = Depends(current_user)) -> dict:
    try:
        return {"items": await service.history(user.id, target_id)}
    except GoogleError as e:
        raise _raise(e)


@router.post("/targets/{target_id}/recheck", status_code=202)
async def recheck(target_id: str, user: AuthUser = Depends(rate_limited_user)) -> dict:
    try:
        await service.recheck(user.id, target_id)
    except GoogleError as e:
        raise _raise(e)
    return {"status": "queued"}


@router.delete("/targets/{target_id}", status_code=204)
async def remove_target(target_id: str, user: AuthUser = Depends(rate_limited_user)) -> None:
    try:
        await service.remove_target(user.id, target_id)
    except GoogleError as e:
        raise _raise(e)


@router.get("/sitemaps")
async def sitemaps(user: AuthUser = Depends(current_user)) -> dict:
    try:
        return await service.list_sitemaps(user.id)
    except GoogleError as e:
        raise _raise(e)


@router.put("/sitemaps")
async def submit_sitemap(body: SitemapRequest, user: AuthUser = Depends(rate_limited_user)) -> dict:
    try:
        await service.submit_sitemap(user.id, body.url)
    except GoogleError as e:
        raise _raise(e)
    return {"submitted": True}
