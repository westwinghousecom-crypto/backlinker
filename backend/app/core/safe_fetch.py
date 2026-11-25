"""Hardened outbound HTTP fetching for user-supplied URLs (SSRF and DNS-rebinding protection).

Why this exists: users submit arbitrary URLs and this server fetches them. Without care, a URL (or a
redirect, or a DNS answer) can point the server at internal systems such as cloud metadata services.

How it defends:
  * ``SafeResolver`` vets every address the HTTP connector is about to connect to. aiohttp connects to
    exactly the addresses the resolver returns, and DNS caching is off, so the IP that was checked is the
    IP that is used. There is no separate "check, then connect" step for an attacker to race (DNS rebinding).
  * IP-literal hosts (``http://127.0.0.1/``, ``http://[::1]/``) never reach a resolver, so
    ``validate_url`` checks them directly.
  * Every redirect hop is validated and resolved again. Only http/https on ports 80/443, no credentials in
    the URL, bounded redirects, response size and total time. HTTPS certificates are verified (certifi).
  * Environment proxies are ignored (``trust_env=False``): a proxy would hide the real destination.
"""
import asyncio
import ipaddress
import socket
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import SplitResult, urljoin, urlsplit

import aiohttp
import certifi

UA = "Mozilla/5.0 (compatible; QuickIndexChecker/1.0)"
MAX_URL_LENGTH = 4096
REDIRECT_STATUSES = (301, 302, 303, 307, 308)


class BlockedDestination(ValueError):
    """The URL points at a non-public, reserved or otherwise prohibited network destination."""


class HostNotFound(ValueError):
    """The domain name does not resolve."""


class TooManyRedirects(ValueError):
    pass


@dataclass(frozen=True)
class FetchPolicy:
    allowed_ports: tuple[int, ...] | None = (80, 443)  # None = any port (tests only)
    max_redirects: int = 5
    max_bytes: int = 1_000_000
    total_timeout: float = 30.0  # the whole redirect chain
    connect_timeout: float = 8.0
    read_timeout: float = 10.0
    user_agent: str = UA


DEFAULT_POLICY = FetchPolicy()

# ---------------------------------------------------------------------------- IP classification

_BLOCKED_NETWORKS = [
    ipaddress.ip_network(n)
    for n in (
        # IPv4
        "0.0.0.0/8", "10.0.0.0/8", "100.64.0.0/10", "127.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12",
        "192.0.0.0/24", "192.0.2.0/24", "192.88.99.0/24", "192.168.0.0/16", "198.18.0.0/15",
        "198.51.100.0/24", "203.0.113.0/24", "224.0.0.0/4", "240.0.0.0/4", "255.255.255.255/32",
        # IPv6
        "::/96", "::1/128", "100::/64", "2001::/23", "2001:db8::/32", "3fff::/20", "fc00::/7",
        "fe80::/10", "fec0::/10", "ff00::/8",
    )
]
_NAT64 = ipaddress.ip_network("64:ff9b::/96")
_NAT64_LOCAL = ipaddress.ip_network("64:ff9b:1::/48")


def is_forbidden_ip(value: str | ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True for anything that is not an ordinary, globally routable unicast address.

    IPv6 forms that embed an IPv4 address (IPv4-mapped, 6to4, NAT64) are judged by the embedded address,
    so ``::ffff:127.0.0.1`` cannot slip past a check that only looks at IPv4 ranges.
    """
    try:
        ip = ipaddress.ip_address(value.split("%", 1)[0] if isinstance(value, str) else value)
    except ValueError:
        return True  # unparsable: refuse
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return is_forbidden_ip(ip.ipv4_mapped)
        if ip.sixtofour is not None:
            return is_forbidden_ip(ip.sixtofour)
        if ip.teredo is not None:
            return True
        if ip in _NAT64_LOCAL:
            return True
        if ip in _NAT64:
            return is_forbidden_ip(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    if (
        ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified or not ip.is_global
    ):
        return True
    return any(ip in net for net in _BLOCKED_NETWORKS if net.version == ip.version)


# ---------------------------------------------------------------------------- URL validation

def validate_url(url: str, policy: FetchPolicy = DEFAULT_POLICY) -> SplitResult:
    """Reject URLs that must never be fetched. Resolved hostnames are vetted later, by the resolver."""
    if len(url) > MAX_URL_LENGTH:
        raise BlockedDestination("URL is too long")
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise BlockedDestination("URL is not valid")
    host = (parts.hostname or "").rstrip(".")
    if parts.scheme not in ("http", "https") or not host:
        raise BlockedDestination("Only http and https URLs are allowed")
    if parts.username is not None or parts.password is not None:
        raise BlockedDestination("URLs with embedded credentials are not allowed")
    if policy.allowed_ports is not None:
        effective = port or (443 if parts.scheme == "https" else 80)
        if effective not in policy.allowed_ports:
            raise BlockedDestination(f"Port {effective} is not allowed")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and is_forbidden_ip(literal):
        raise BlockedDestination("IP address is not publicly routable")
    return parts


class SafeResolver(aiohttp.ThreadedResolver):
    """DNS resolver that refuses to return prohibited addresses.

    aiohttp connects to the addresses returned here, and the session disables DNS caching, so every
    connection is made to an address that was just vetted. If ANY answer is prohibited the whole name is
    refused, which is what a rebinding attacker mixing public and private records would hit.
    """

    def __init__(self, is_forbidden: Callable[[str], bool] = is_forbidden_ip) -> None:
        super().__init__()
        self._is_forbidden = is_forbidden

    async def _lookup(self, host: str, port: int, family: socket.AddressFamily) -> list:
        return await super().resolve(host, port, family)

    async def resolve(self, host: str, port: int = 0, family: socket.AddressFamily = socket.AF_INET) -> list:
        try:
            results = await self._lookup(host, port, family)
        except socket.gaierror as e:
            raise HostNotFound(f"cannot resolve {host}") from e
        if not results:
            raise HostNotFound(f"cannot resolve {host}")
        for r in results:
            if self._is_forbidden(r["host"]):
                raise BlockedDestination("Hostname resolves to a non-public address")
        return results


def make_session(
    policy: FetchPolicy = DEFAULT_POLICY, resolver: aiohttp.abc.AbstractResolver | None = None
) -> aiohttp.ClientSession:
    ctx = ssl.create_default_context(cafile=certifi.where())  # verifies certificate chain and hostname
    connector = aiohttp.TCPConnector(
        ssl=ctx,
        resolver=resolver or SafeResolver(),
        use_dns_cache=False,  # never reuse an old answer: resolve (and vet) again for each connection
        limit=100,
        limit_per_host=5,
    )
    timeout = aiohttp.ClientTimeout(
        total=policy.total_timeout, sock_connect=policy.connect_timeout, sock_read=policy.read_timeout
    )
    return aiohttp.ClientSession(connector=connector, timeout=timeout, trust_env=False)


# ---------------------------------------------------------------------------- fetching

@dataclass
class Fetched:
    status: int
    final_url: str
    redirects: list[str]
    headers: "aiohttp.typedefs.LooseHeaders"
    text: str
    truncated: bool = False


async def read_limited(content, limit: int) -> tuple[bytes, bool]:
    """Read the whole body up to `limit` bytes. (StreamReader.read(n) can return a partial chunk.)"""
    chunks: list[bytes] = []
    total = 0
    async for chunk in content.iter_chunked(65536):
        chunks.append(chunk)
        total += len(chunk)
        if total >= limit:
            break
    data = b"".join(chunks)
    return data[:limit], len(data) > limit or total >= limit


def _decode(raw: bytes, charset: str | None) -> str:
    try:
        return raw.decode(charset or "utf-8", "replace")
    except LookupError:
        return raw.decode("utf-8", "replace")


async def fetch(session: aiohttp.ClientSession, url: str, policy: FetchPolicy = DEFAULT_POLICY) -> Fetched:
    """GET `url`, following up to ``policy.max_redirects`` redirects. Every hop is validated."""

    async def run() -> Fetched:
        hops: list[str] = []
        current = url
        for _ in range(policy.max_redirects + 1):
            validate_url(current, policy)
            async with session.get(
                current,
                allow_redirects=False,
                headers={"User-Agent": policy.user_agent, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
            ) as resp:
                location = resp.headers.get("Location")
                if resp.status in REDIRECT_STATUSES and location:
                    hops.append(current)
                    current = urljoin(current, location)
                    continue
                raw, truncated = await read_limited(resp.content, policy.max_bytes)
                return Fetched(resp.status, current, hops, resp.headers, _decode(raw, resp.charset), truncated)
        raise TooManyRedirects(f"more than {policy.max_redirects} redirects")

    return await asyncio.wait_for(run(), policy.total_timeout)
