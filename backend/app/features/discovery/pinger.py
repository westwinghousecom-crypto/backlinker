import asyncio
import logging
import re
import xmlrpc.client

import aiohttp

from app.core.config import get_settings
from app.features.discovery import repository

log = logging.getLogger(__name__)

_FLERROR = re.compile(r"flerror</name>\s*<value>\s*<boolean>\s*1", re.I)


def build_ping_payload(name: str, url: str) -> bytes:
    """weblogUpdates.ping XML-RPC body (the classic blog/feed update notification)."""
    return xmlrpc.client.dumps((name, url), "weblogUpdates.ping").encode("utf-8")


def ping_succeeded(status: int, body: str) -> bool:
    return status == 200 and "<fault>" not in body and not _FLERROR.search(body)


async def ping_endpoint(session: aiohttp.ClientSession, endpoint: str, name: str, url: str) -> bool:
    try:
        async with session.post(
            endpoint, data=build_ping_payload(name, url), headers={"Content-Type": "text/xml"}
        ) as resp:
            return ping_succeeded(resp.status, await resp.text())
    except Exception as e:
        log.debug("Ping to %s failed: %s", endpoint, e)
        return False


async def ping_all(endpoints: list[str], name: str, url: str) -> int:
    """Announce the feed to every endpoint concurrently. Returns how many accepted it."""
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        results = await asyncio.gather(*(ping_endpoint(session, e, name, url) for e in endpoints))
    return sum(results)


async def websub_publish(session: aiohttp.ClientSession, hub: str, feed_url: str) -> bool:
    """WebSub publisher ping: tell the hub the feed changed so it can fetch and push it (hubs reply 204/202)."""
    try:
        async with session.post(hub, data={"hub.mode": "publish", "hub.url": feed_url}) as resp:
            return resp.status in (200, 202, 204)
    except Exception as e:
        log.debug("WebSub publish to %s failed: %s", hub, e)
        return False


async def websub_all(hubs: list[str], feed_url: str) -> int:
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
        results = await asyncio.gather(*(websub_publish(session, h, feed_url) for h in hubs))
    return sum(results)


def _is_public(base_url: str) -> bool:
    return not any(h in base_url for h in ("localhost", "127.0.0.1", "0.0.0.0"))


async def discovery_pinger() -> None:
    """Ping our public feed whenever new URLs have been published (at most once per interval)."""
    s = get_settings()
    if not s.PUBLIC_GLOBAL_FEED or not s.PING_ENDPOINTS or not _is_public(s.PUBLIC_BASE_URL):
        log.info("Feed pinging disabled (PUBLIC_GLOBAL_FEED off, no endpoints, or PUBLIC_BASE_URL not public)")
        return
    feed_url = f"{s.PUBLIC_BASE_URL.rstrip('/')}/feed.xml"
    last_seen: str | None = None
    while True:
        try:
            rows = await repository.list_published(1)
            latest = rows[0].get("updated_at") if rows else None
            if latest and latest != last_seen:
                ok = await ping_all(s.PING_ENDPOINTS, "QuickIndex", feed_url)
                log.info("Pinged feed: %d/%d endpoints accepted", ok, len(s.PING_ENDPOINTS))
                if s.WEBSUB_HUBS:
                    hubs_ok = await websub_all(s.WEBSUB_HUBS, feed_url)
                    log.info("WebSub: %d/%d hubs accepted", hubs_ok, len(s.WEBSUB_HUBS))
                last_seen = latest
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("Discovery pinger error")
        await asyncio.sleep(max(s.PING_INTERVAL_SECONDS, 60))
