from fastapi import APIRouter, HTTPException, Response

from app.core.config import get_settings
from app.features.discovery import render, repository, sharing

router = APIRouter(tags=["discovery"])

SITEMAP_LIMIT = 5000  # sitemap protocol allows up to 50,000; keep responses light
FEED_LIMIT = 200
XML_HEADERS = {"Cache-Control": "public, max-age=300"}


def _hub() -> str | None:
    hubs = get_settings().WEBSUB_HUBS
    return hubs[0] if hubs else None


def _global_feed_enabled() -> bool:
    """The all-customers sitemap/feed is off unless explicitly enabled: it lists every customer's URLs."""
    return get_settings().PUBLIC_GLOBAL_FEED


def _xml(body: str, media: str) -> Response:
    return Response(content=body, media_type=media, headers=XML_HEADERS)


@router.get("/sitemap.xml")
async def sitemap() -> Response:
    if not _global_feed_enabled():
        raise HTTPException(status_code=404)
    rows = await repository.list_published(SITEMAP_LIMIT)
    return _xml(render.sitemap_xml(rows), "application/xml")


@router.get("/feed.xml")
async def feed() -> Response:
    if not _global_feed_enabled():
        raise HTTPException(status_code=404)
    base = get_settings().PUBLIC_BASE_URL.rstrip("/")
    rows = await repository.list_published(FEED_LIMIT)
    return _xml(
        render.rss_xml(rows, "QuickIndex - newly indexed URLs", base, f"{base}/feed.xml", _hub()),
        "application/rss+xml",
    )


def build_batch_sitemap(rows: list) -> str:
    return render.sitemap_xml(rows)


def build_batch_feed(rows: list, batch_id: str) -> str:
    base = get_settings().PUBLIC_BASE_URL.rstrip("/")
    self_url = f"{base}/batches/{batch_id}/feed.xml"
    return render.rss_xml(rows, f"QuickIndex batch {batch_id}", self_url, self_url, _hub())


async def _require_public(batch_id: str) -> None:
    # Private by default: 404 (not 403) so a private batch is indistinguishable from one that does not exist.
    if not await sharing.is_public(batch_id):
        raise HTTPException(status_code=404)


@router.get("/batches/{batch_id}/sitemap.xml")
async def batch_sitemap(batch_id: str) -> Response:
    await _require_public(batch_id)
    return _xml(build_batch_sitemap(await repository.list_published(SITEMAP_LIMIT, batch_id)), "application/xml")


@router.get("/batches/{batch_id}/feed.xml")
async def batch_feed(batch_id: str) -> Response:
    await _require_public(batch_id)
    return _xml(build_batch_feed(await repository.list_published(FEED_LIMIT, batch_id), batch_id), "application/rss+xml")


@router.get("/robots.txt")
async def robots() -> Response:
    base = get_settings().PUBLIC_BASE_URL.rstrip("/")
    lines = [
        "User-agent: *",
        "Allow: /batches/",
        "Disallow: /api/",
        "",
    ]
    if _global_feed_enabled():
        lines[1:1] = ["Allow: /sitemap.xml", "Allow: /feed.xml"]
        lines += [f"Sitemap: {base}/sitemap.xml", ""]
    body = chr(10).join(lines)
    return Response(content=body, media_type="text/plain")


@router.get("/{key}.txt")
async def indexnow_key_file(key: str) -> Response:
    """IndexNow ownership proof: https://<host>/<INDEXNOW_KEY>.txt must return the key."""
    expected = get_settings().INDEXNOW_KEY
    if not expected or key != expected:
        raise HTTPException(status_code=404)
    return Response(content=expected, media_type="text/plain")
