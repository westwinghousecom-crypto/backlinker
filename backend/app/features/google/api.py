"""Google API access: Search Console (sites, URL Inspection, sitemaps) and the OAuth token endpoints.

All HTTP goes through ``transport`` so tests can replace it with recorded/mocked Google responses. Only fixed Google
hosts are contacted here (never customer-supplied URLs), and nothing secret is ever logged: errors carry Google's own
error code and a short message, not tokens or request bodies.
"""
import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable
from urllib.parse import quote

import aiohttp

from app.core.safe_fetch import make_session

log = logging.getLogger(__name__)

SITES_URL = "https://www.googleapis.com/webmasters/v3/sites"
INSPECT_URL = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
MAX_RESPONSE_BYTES = 2_000_000

QUOTA_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded", "dailyLimitExceeded", "RESOURCE_EXHAUSTED"}


class GoogleApiError(Exception):
    """A failed Google call. `kind` is one of: auth, permission, quota, not_found, bad_request, transient."""

    def __init__(self, kind: str, status: int, message: str = "", code: str = "", retry_after: float | None = None):
        super().__init__(f"{kind} ({status}): {message}")
        self.kind, self.status, self.message, self.code, self.retry_after = kind, status, message, code, retry_after


@dataclass
class Response:
    status: int
    body: dict[str, Any] | None
    headers: dict[str, str]


Transport = Callable[..., Awaitable[Response]]


async def _aiohttp_transport(method: str, url: str, *, headers: dict | None = None, data: dict | None = None,
                            json_body: dict | None = None) -> Response:
    async with make_session() as s:  # TLS verified; only fixed Google URLs are passed in
        async with s.request(method, url, headers=headers, data=data, json=json_body) as r:
            raw = await r.content.read(MAX_RESPONSE_BYTES)
            body = None
            if raw:
                try:
                    body = json.loads(raw)
                except ValueError:
                    body = None
            return Response(r.status, body if isinstance(body, dict) else None, {k.lower(): v for k, v in r.headers.items()})


transport: Transport = _aiohttp_transport


def set_transport(t: Transport | None) -> None:
    """Replace the HTTP layer (tests). Pass None to restore the real one."""
    global transport
    transport = t or _aiohttp_transport


def _error_from(resp: Response) -> GoogleApiError:
    err = (resp.body or {}).get("error")
    code = message = ""
    reasons: set[str] = set()
    if isinstance(err, dict):
        message = str(err.get("message", ""))[:200]
        code = str(err.get("status", ""))
        reasons = {str(e.get("reason")) for e in err.get("errors", []) if isinstance(e, dict)}
        reasons.add(code)
    elif isinstance(err, str):  # OAuth endpoints: {"error": "invalid_grant", "error_description": ...}
        code = err
        message = str((resp.body or {}).get("error_description", ""))[:200]
    retry_after = None
    try:
        retry_after = float(resp.headers.get("retry-after", ""))
    except ValueError:
        pass
    if resp.status == 429 or reasons & QUOTA_REASONS:
        return GoogleApiError("quota", resp.status, message, code, retry_after)
    if resp.status == 401:
        return GoogleApiError("auth", resp.status, message, code)
    if resp.status == 403:
        return GoogleApiError("permission", resp.status, message, code)
    if resp.status == 404:
        return GoogleApiError("not_found", resp.status, message, code)
    if 400 <= resp.status < 500:
        return GoogleApiError("bad_request", resp.status, message, code)
    return GoogleApiError("transient", resp.status, message, code, retry_after)


async def call(method: str, url: str, access_token: str | None = None, *, data: dict | None = None,
               json_body: dict | None = None) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
    try:
        resp = await transport(method, url, headers=headers, data=data, json_body=json_body)
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError) as e:
        raise GoogleApiError("transient", 0, type(e).__name__)
    if resp.status >= 400:
        raise _error_from(resp)
    return resp.body or {}


# ---------------------------------------------------------------------------- Search Console

async def list_sites(access_token: str) -> list[dict]:
    return (await call("GET", SITES_URL, access_token)).get("siteEntry", []) or []


async def inspect_url(access_token: str, inspection_url: str, site_url: str) -> dict:
    return await call(
        "POST", INSPECT_URL, access_token,
        json_body={"inspectionUrl": inspection_url, "siteUrl": site_url, "languageCode": "en-US"},
    )


def _sitemaps_url(site_url: str, feedpath: str | None = None) -> str:
    base = f"{SITES_URL}/{quote(site_url, safe='')}/sitemaps"
    return f"{base}/{quote(feedpath, safe='')}" if feedpath else base


async def list_sitemaps(access_token: str, site_url: str) -> list[dict]:
    return (await call("GET", _sitemaps_url(site_url), access_token)).get("sitemap", []) or []


async def submit_sitemap(access_token: str, site_url: str, feedpath: str) -> None:
    await call("PUT", _sitemaps_url(site_url, feedpath), access_token)
