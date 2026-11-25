import logging
from collections import defaultdict
from urllib.parse import quote, urlsplit

import aiohttp

from app.core.config import Settings
from app.features.proxy.rotator import FreeProxyRotator

log = logging.getLogger(__name__)

PROXY_ATTEMPTS = 2
INDEXNOW_BATCH_MAX = 10_000  # per the IndexNow spec
FALLBACK_ENDPOINTS = ["https://www.bing.com/indexnow", "https://yandex.com/indexnow"]


async def _post_indexnow(
    session: aiohttp.ClientSession,
    endpoint: str,
    settings: Settings,
    host: str,
    urls: list[str],
    proxy: str | None,
) -> int:
    payload: dict = {"host": host, "key": settings.INDEXNOW_KEY, "urlList": urls}
    if settings.INDEXNOW_KEY_LOCATION:
        payload["keyLocation"] = settings.INDEXNOW_KEY_LOCATION
    async with session.post(
        endpoint, json=payload, headers={"Content-Type": "application/json; charset=utf-8"}, proxy=proxy
    ) as resp:
        # 200 OK, 202 Accepted (key validation pending). 403/422 = key or host mismatch.
        if resp.status not in (200, 202):
            log.info("IndexNow %s rejected %s (%d URLs): HTTP %d", endpoint, host, len(urls), resp.status)
        return resp.status


def _outcome(status: int) -> str | None:
    """200 = accepted; 202 = received but key validation still pending (not confirmed)."""
    return {200: "completed", 202: "submitted"}.get(status)


async def _submit_host(
    session: aiohttp.ClientSession,
    settings: Settings,
    host: str,
    urls: list[str],
    rotator: FreeProxyRotator | None,
) -> str | None:
    """Submit one host's URLs. Returns "completed" (HTTP 200), "submitted" (HTTP 202) or None. Tries proxies (optional) on the primary endpoint, then direct + fallbacks."""
    if settings.USE_PROXY and rotator is not None:
        for _ in range(PROXY_ATTEMPTS):
            proxy = await rotator.get_proxy()
            if proxy is None:
                break
            try:
                result = _outcome(await _post_indexnow(session, settings.INDEXNOW_ENDPOINT, settings, host, urls, proxy))
                if result:
                    await rotator.release(proxy)
                    return result
            except Exception as e:
                log.debug("Proxy %s failed: %s", proxy, e)
            await rotator.discard(proxy)
    for endpoint in [settings.INDEXNOW_ENDPOINT, *FALLBACK_ENDPOINTS]:
        try:
            result = _outcome(await _post_indexnow(session, endpoint, settings, host, urls, None))
            if result:
                return result
        except Exception as e:
            log.warning("IndexNow submit to %s failed for %s: %s", endpoint, host, e)
    return None


async def save_to_wayback(session: aiohttp.ClientSession, url: str) -> bool:
    """Ask the Internet Archive to snapshot the page (public, rate limited; best effort)."""
    try:
        async with session.get(f"https://web.archive.org/save/{quote(url, safe=':/?&=%#')}") as resp:
            return resp.status == 200
    except Exception as e:
        log.debug("Wayback save failed for %s: %s", url, e)
        return False


async def submit_urls(
    session: aiohttp.ClientSession,
    settings: Settings,
    urls: list[str],
    rotator: FreeProxyRotator | None = None,
) -> dict[str, str | None]:
    """Submit URLs via every enabled channel. Returns {url: "completed" | "submitted" | None}.

    IndexNow takes many URLs of one host per request, so URLs are grouped by host.
    """
    by_host: dict[str, list[str]] = defaultdict(list)
    for u in urls:
        by_host[urlsplit(u).netloc].append(u)

    results: dict[str, str | None] = {}
    for host, group in by_host.items():
        for i in range(0, len(group), INDEXNOW_BATCH_MAX):
            chunk = group[i : i + INDEXNOW_BATCH_MAX]
            ok = await _submit_host(session, settings, host, chunk, rotator)
            results.update({u: ok for u in chunk})

    if settings.WAYBACK_SAVE:
        for u in urls:
            if await save_to_wayback(session, u):
                results[u] = "completed"
    return results
