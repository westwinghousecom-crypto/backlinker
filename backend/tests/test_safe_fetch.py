"""SSRF / DNS-rebinding regression tests for app.core.safe_fetch."""
import asyncio
import socket
from dataclasses import replace

import aiohttp
import pytest
from aiohttp import web

from app.core import safe_fetch as sf
from app.core.safe_fetch import (
    BlockedDestination,
    FetchPolicy,
    HostNotFound,
    SafeResolver,
    TooManyRedirects,
    fetch,
    is_forbidden_ip,
    make_session,
    validate_url,
)
from app.features.diagnostics import scanner

FORBIDDEN = [
    # IPv4
    "127.0.0.1", "127.255.255.254", "0.0.0.0", "10.0.0.1", "172.16.5.4", "172.31.255.255", "192.168.1.1",
    "169.254.169.254", "100.64.0.1", "192.0.0.1", "192.0.2.1", "198.18.0.1", "198.51.100.7", "203.0.113.9",
    "224.0.0.1", "240.0.0.1", "255.255.255.255",
    # IPv6
    "::1", "::", "fe80::1", "fe80::1%eth0", "fc00::1", "fd12:3456::1", "ff02::1", "2001:db8::1", "100::1",
    # IPv6 forms that embed an IPv4 address
    "::ffff:127.0.0.1", "::ffff:10.0.0.1", "::ffff:169.254.169.254", "::ffff:7f00:1",
    "64:ff9b::7f00:1", "64:ff9b::a9fe:a9fe", "64:ff9b:1::1", "2002:7f00:1::1", "2002:a9fe:a9fe::1",
    "2001:0:4136:e378:8000:63bf:3fff:fdd2",  # teredo
    "::127.0.0.1",  # deprecated IPv4-compatible
    "not-an-ip",
]
ALLOWED = ["93.184.216.34", "8.8.8.8", "1.1.1.1", "2606:2800:220:1:248:1893:25c8:1946", "2001:4860:4860::8888",
           "::ffff:8.8.8.8", "64:ff9b::808:808"]


@pytest.mark.parametrize("ip", FORBIDDEN)
def test_forbidden_addresses(ip):
    assert is_forbidden_ip(ip), ip


@pytest.mark.parametrize("ip", ALLOWED)
def test_public_addresses_allowed(ip):
    assert not is_forbidden_ip(ip), ip


@pytest.mark.parametrize(
    "url",
    [
        "ftp://example.com/", "file:///etc/passwd", "gopher://example.com/", "javascript:alert(1)", "//example.com/",
        "http://user:pass@example.com/", "http://user@example.com/",
        "http://127.0.0.1/", "http://127.0.0.1:80/", "http://[::1]/", "http://[::ffff:127.0.0.1]/", "http://[::ffff:7f00:1]/",
        "http://169.254.169.254/latest/meta-data/", "http://0.0.0.0/", "http://10.1.2.3/", "http://[fe80::1]/",
        "http://[fd00::1]/", "http://[64:ff9b::7f00:1]/",
        "http://example.com:22/", "http://example.com:6379/", "https://example.com:8443/", "http://example.com:99999/",
        "http:///nohost", "", "http://" + "a" * 5000 + ".com/",
    ],
)
def test_prohibited_urls_rejected(url):
    with pytest.raises(BlockedDestination):
        validate_url(url)


@pytest.mark.parametrize("url", ["https://example.com/", "http://example.com:80/x", "https://example.com:443/", "http://[2606:2800:220:1::1]/"])
def test_ordinary_urls_accepted(url):
    validate_url(url)


# ---------------------------------------------------------------------------- resolver / rebinding

def result(ip: str, family=socket.AF_INET):
    return {"hostname": "x", "host": ip, "port": 80, "family": family, "proto": 6, "flags": 0}


class ScriptedResolver(SafeResolver):
    """Returns scripted DNS answers: a different list on each lookup (hostile DNS)."""

    def __init__(self, answers, **kw):
        super().__init__(**kw)
        self.answers = list(answers)
        self.lookups = 0

    async def _lookup(self, host, port, family):
        self.lookups += 1
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


async def test_resolver_refuses_private_answer():
    r = ScriptedResolver([[result("10.0.0.5")]])
    with pytest.raises(BlockedDestination):
        await r.resolve("evil.example")


async def test_resolver_refuses_mixed_public_and_private_answers():
    r = ScriptedResolver([[result("93.184.216.34"), result("127.0.0.1")]])
    with pytest.raises(BlockedDestination):
        await r.resolve("mixed.example")


async def test_resolver_refuses_private_ipv6_answers():
    for ip in ("::1", "fe80::1", "::ffff:127.0.0.1", "fd00::1"):
        r = ScriptedResolver([[result(ip, socket.AF_INET6)]])
        with pytest.raises(BlockedDestination):
            await r.resolve("v6.example")


async def test_rebinding_public_then_private_is_caught_on_the_second_lookup():
    """Hostile DNS: first answer is public (passes any pre-check), the next is the internal address."""
    r = ScriptedResolver([[result("93.184.216.34")], [result("169.254.169.254")]])
    assert (await r.resolve("rebind.example"))[0]["host"] == "93.184.216.34"
    with pytest.raises(BlockedDestination):
        await r.resolve("rebind.example")  # the connector asks again for the next connection
    assert r.lookups == 2


async def test_unknown_domain_is_host_not_found():
    class NoSuch(SafeResolver):
        async def _lookup(self, host, port, family):
            raise socket.gaierror(socket.EAI_NONAME, "no such host")

    with pytest.raises(HostNotFound):
        await NoSuch().resolve("nope.invalid")


async def test_session_is_hardened():
    async with make_session() as s:
        c = s.connector
        assert isinstance(c._resolver, SafeResolver)
        assert c._use_dns_cache is False  # a cached answer would skip the vetting
        assert s.trust_env is False  # env proxies would hide the real destination
        ctx = c._ssl
        assert ctx.verify_mode.name == "CERT_REQUIRED" and ctx.check_hostname is True


# ---------------------------------------------------------------------------- real sockets

class MapResolver(SafeResolver):
    """Maps test hostnames to addresses, then applies the normal vetting with a custom forbidden-test."""

    def __init__(self, mapping, is_forbidden):
        super().__init__(is_forbidden)
        self.mapping = mapping
        self.calls: list[str] = []

    async def _lookup(self, host, port, family):
        self.calls.append(host)
        if host not in self.mapping:
            raise socket.gaierror(socket.EAI_NONAME, "unknown")
        return [{"hostname": host, "host": self.mapping[host], "port": port, "family": socket.AF_INET, "proto": 6, "flags": 0}]


@pytest.fixture
async def server():
    async def ok(request):
        return web.Response(text="<html>hello</html>", content_type="text/html")

    async def to_internal(request):
        raise web.HTTPFound("http://169.254.169.254/latest/meta-data/")

    async def to_ipv6_loopback(request):
        raise web.HTTPFound("http://[::1]/admin")

    async def to_mapped(request):
        raise web.HTTPFound("http://[::ffff:127.0.0.1]/")

    async def to_evil_host(request):
        raise web.HTTPFound(f"http://evil.test:{request.url.port}/")

    async def to_file(request):
        raise web.HTTPFound("file:///etc/passwd")

    async def loop(request):
        raise web.HTTPFound("/loop")

    async def big(request):
        resp = web.StreamResponse()
        await resp.prepare(request)
        for _ in range(50):
            await resp.write(b"x" * 100_000)
        return resp

    async def slow(request):
        resp = web.StreamResponse()
        await resp.prepare(request)
        await resp.write(b"start")
        await asyncio.sleep(10)
        return resp

    app = web.Application()
    for path, h in {"/ok": ok, "/internal": to_internal, "/v6": to_ipv6_loopback, "/mapped": to_mapped,
                    "/evil": to_evil_host, "/file": to_file, "/loop": loop, "/big": big, "/slow": slow}.items():
        app.router.add_get(path, h)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    yield port
    await runner.cleanup()


def local_policy(**kw):
    return replace(FetchPolicy(allowed_ports=None), **kw)


def local_resolver():
    # Pretend only 10.0.0.5 is prohibited, so 127.0.0.1 (our test server) is reachable via the vetted path.
    return MapResolver({"good.test": "127.0.0.1", "evil.test": "10.0.0.5"}, lambda ip: ip == "10.0.0.5")


async def test_connection_goes_to_the_address_the_resolver_returned(server):
    """'good.test' does not exist in real DNS: this only works if the connector used the vetted address."""
    resolver = local_resolver()
    async with make_session(local_policy(), resolver) as s:
        got = await fetch(s, f"http://good.test:{server}/ok", local_policy())
    assert got.status == 200 and "hello" in got.text
    assert resolver.calls == ["good.test"]


@pytest.mark.parametrize("path", ["internal", "v6", "mapped", "file"])
async def test_redirect_to_private_or_unsupported_destination_is_blocked(server, path):
    async with make_session(local_policy(), local_resolver()) as s:
        with pytest.raises(BlockedDestination):
            await fetch(s, f"http://good.test:{server}/{path}", local_policy())


async def test_redirect_to_hostname_that_resolves_privately_is_blocked(server):
    resolver = local_resolver()
    async with make_session(local_policy(), resolver) as s:
        with pytest.raises(BlockedDestination):
            await fetch(s, f"http://good.test:{server}/evil", local_policy())
    assert resolver.calls == ["good.test", "evil.test"]  # the second hop was resolved and vetted again


async def test_redirect_loop_is_cut_off(server):
    async with make_session(local_policy(), local_resolver()) as s:
        with pytest.raises(TooManyRedirects):
            await fetch(s, f"http://good.test:{server}/loop", local_policy(max_redirects=3))


async def test_response_size_is_capped(server):
    async with make_session(local_policy(), local_resolver()) as s:
        got = await fetch(s, f"http://good.test:{server}/big", local_policy(max_bytes=250_000))
    assert len(got.text) == 250_000 and got.truncated


async def test_slow_response_hits_the_total_timeout(server):
    async with make_session(local_policy(), local_resolver()) as s:
        with pytest.raises(TimeoutError):
            await fetch(s, f"http://good.test:{server}/slow", local_policy(total_timeout=1.0))


async def test_default_policy_refuses_the_test_servers_port(server):
    async with make_session() as s:
        with pytest.raises(BlockedDestination):
            await fetch(s, f"http://127.0.0.1:{server}/ok")


# ---------------------------------------------------------------------------- via the scanner

async def test_scanner_reports_blocked_destinations_in_plain_english():
    async with make_session() as s:
        for url in ("http://127.0.0.1/", "http://[::1]/", "http://169.254.169.254/latest/meta-data/",
                    "http://[::ffff:10.0.0.1]/", "http://user:pw@example.com/", "http://example.com:22/"):
            res = await scanner.check_url(s, url)
            assert res.verdict == "unreachable" and res.problems[0].code == "private_address", url


async def test_scanner_classifies_dns_failure_and_blocked_dns_differently(server):
    resolver = local_resolver()
    async with make_session(local_policy(), resolver) as s:
        missing = await scanner.check_url(s, f"http://unknown.test:{server}/", policy=local_policy())
        assert missing.problems[0].code == "host_unreachable"
        evil = await scanner.check_url(s, f"http://evil.test:{server}/", policy=local_policy())
        assert evil.problems[0].code == "private_address"
        ok = await scanner.check_url(s, f"http://good.test:{server}/ok", policy=local_policy())
        assert ok.status == 200 and ok.verdict in ("eligible", "warning")
