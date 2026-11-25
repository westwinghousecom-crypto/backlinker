import asyncio
import logging
import random

import aiohttp

log = logging.getLogger(__name__)

PROXIFLY_URL = (
    "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/http/data.json"
)


class FreeProxyRotator:
    """Pool of free HTTP proxies. All access is guarded by an asyncio.Lock."""

    def __init__(self, min_pool: int = 10, source_url: str = PROXIFLY_URL) -> None:
        self._pool: list[str] = []
        self._lock = asyncio.Lock()
        self._min_pool = min_pool
        self._source_url = source_url

    async def _refetch(self) -> None:
        try:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self._source_url) as resp:
                    resp.raise_for_status()
                    data = await resp.json(content_type=None)
            proxies = [e["proxy"] for e in data if isinstance(e, dict) and e.get("proxy")]
            random.shuffle(proxies)
            known = set(self._pool)
            self._pool.extend(p for p in proxies if p not in known)
            log.info("Proxy pool refreshed: %d proxies", len(self._pool))
        except Exception as e:  # network/parse errors must never break indexing
            log.warning("Failed to fetch proxy list: %s", e)

    async def get_proxy(self) -> str | None:
        """Pop one proxy URL, refetching when low. Returns None if unavailable."""
        async with self._lock:
            if len(self._pool) < self._min_pool:
                await self._refetch()
            return self._pool.pop() if self._pool else None

    async def discard(self, proxy: str) -> None:
        # Proxies are popped on use, so a failing one is simply not returned.
        async with self._lock:
            if proxy in self._pool:
                self._pool.remove(proxy)

    async def release(self, proxy: str) -> None:
        """Return a proxy that worked back to the pool."""
        async with self._lock:
            if proxy not in self._pool:
                self._pool.append(proxy)