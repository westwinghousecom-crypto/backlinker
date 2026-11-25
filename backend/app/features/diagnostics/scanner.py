"""Eligibility scanner: can Google crawl and index this backlink page, and is the link really there?

Fetches pages on behalf of users, so every hop is checked against private/internal
addresses (SSRF protection). Pages are fetched as plain HTML: content added by JavaScript
after load is not visible to this scanner.
"""
import asyncio
import re
import ssl
import time
from dataclasses import replace
from html.parser import HTMLParser
from typing import Literal
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

import aiohttp
from pydantic import BaseModel, Field

from app.features.diagnostics.social import platform_for
from app.core.safe_fetch import (
    DEFAULT_POLICY,
    BlockedDestination,
    FetchPolicy,
    HostNotFound,
    TooManyRedirects,
    fetch,
    make_session,
)

ROBOTS_TTL = 600.0
ROBOTS_MAX_BYTES = 512_000  # Google reads at most 500 KiB of robots.txt
Verdict = Literal["eligible", "warning", "blocked", "unreachable"]
LinkType = Literal["follow", "nofollow", "ugc", "sponsored"]


class Problem(BaseModel):
    code: str
    severity: Literal["error", "warning", "info"]
    title: str
    explanation: str
    fix: str


class UrlCheck(BaseModel):
    url: str
    final_url: str | None = None
    status: int | None = None
    redirects: list[str] = Field(default_factory=list)
    robots_allowed: bool | None = None  # can Googlebot crawl it? None = robots.txt unreadable
    noindex: bool = False
    noindex_source: str | None = None
    canonical: str | None = None
    canonical_mismatch: bool = False
    backlink_found: bool | None = None  # None when no target was given
    backlink_rel: list[str] = Field(default_factory=list)
    backlink_type: LinkType | None = None
    backlink_anchor: str | None = None
    verdict: Verdict = "unreachable"
    issues: list[str] = Field(default_factory=list)  # problem titles, kept for simple clients
    problems: list[Problem] = Field(default_factory=list)
    # Technical checks cannot prove indexing. Only authorized Search Console data could.
    google_index_status: Literal["unknown"] = "unknown"


# --------------------------------------------------------------------------- problems

def _problem(code: str, severity: str, title: str, explanation: str, fix: str) -> Problem:
    return Problem(code=code, severity=severity, title=title, explanation=explanation, fix=fix)  # type: ignore[arg-type]


def http_problem(status: int) -> Problem:
    if status in (404, 410):
        why = "The page does not exist (anymore), so there is nothing for Google to index and the backlink is lost."
        fix = "Ask the site owner to restore the page, or get the link placed on a live page and submit the new URL."
    elif status in (401, 403):
        why = "The site refuses to show this page to visitors without permission, so Google cannot read it either."
        fix = "Use a page that is publicly viewable without logging in."
    elif status == 429:
        why = "The site temporarily blocked our check for making too many requests. This may not affect Google."
        fix = "Recheck this URL later."
    elif status >= 500:
        why = "The site had a server error. If it keeps happening, Google will drop the page."
        fix = "Recheck later. If the error stays, contact the site owner."
    else:
        why = "The page did not return a normal successful response, so Google may not index it."
        fix = "Open the URL in a browser and confirm it loads normally."
    return _problem("http_error", "error", f"Page returns HTTP {status}", why, fix)


def robots_blocked_problem() -> Problem:
    return _problem(
        "robots_blocked", "error", "robots.txt blocks Googlebot",
        "The site's robots.txt file tells Google not to visit this page, so it will not be crawled.",
        "Ask the site owner to allow Googlebot for this path, or place the link on a page that is not blocked.",
    )


def robots_unknown_problem() -> Problem:
    return _problem(
        "robots_unknown", "info", "robots.txt could not be read",
        "The site's robots.txt file did not respond properly, so we cannot say if Googlebot is allowed.",
        "Recheck later. This does not change the verdict.",
    )


def noindex_problem(source: str | None) -> Problem:
    return _problem(
        "noindex", "error", f"Page is marked noindex ({source or 'unknown source'})",
        "The page tells search engines not to include it in their index, so it will never appear in Google.",
        "Ask the site owner to remove the noindex instruction, or use a different page for the backlink.",
    )


def canonical_problem(canonical: str | None) -> Problem:
    return _problem(
        "canonical_mismatch", "warning", "Canonical points to a different URL",
        f"The page says its 'main' version is {canonical}. Google may index that address instead of this one.",
        "Submit the canonical URL instead, or ask the site owner to correct the canonical tag.",
    )


def redirect_problem(hops: int) -> Problem:
    return _problem(
        "redirect_chain", "warning", f"Long redirect chain ({hops} hops)",
        "The URL jumps through several addresses before reaching the page. Google may stop following or index the wrong one.",
        "Use the final URL shown here as the link target.",
    )


def social_problem(platform: str, advice: str, via_redirect: bool) -> Problem:
    extra = " This address redirects to the real post: submit the final address, not the share link." if via_redirect else ""
    return _problem(
        "social_platform", "warning", f"Social media link ({platform}): indexing is controlled by the platform",
        advice + extra + " Submitting cannot override this.",
        "Make sure the post is public, use its direct post address, and link to it from a page that search engines already index "
        "(for example your own blog). Treat these links as visibility and traffic, not as a guaranteed backlink.",
    )


def backlink_missing_problem() -> Problem:
    return _problem(
        "backlink_missing", "warning", "Your link was not found in the page HTML",
        "We did not find a link to your target site in the HTML the server sent. The link may have been removed, or the page may add it with JavaScript after loading, which this check does not run, so it can still be visible in a browser.",
        "Open the page in a browser and look for your link. If it is gone, contact the site owner.",
    )


def qualified_link_problem(link_type: str) -> Problem:
    detail = {
        "nofollow": "Google treats nofollow links as a hint and usually passes little ranking value.",
        "ugc": "A 'ugc' link is marked as user-generated content, which passes little or no ranking value.",
        "sponsored": "A 'sponsored' link is marked as paid, which passes no ranking value.",
    }[link_type]
    return _problem(
        "link_qualified", "warning", f"Link is marked {link_type}",
        detail,
        "This is not a technical fault. If you need ranking value, ask for a normal (follow) link.",
    )


FETCH_PROBLEMS: dict[str, tuple[str, str, str]] = {
    "private_address": (
        "URL points to a non-public or invalid address",
        "The address is not a normal public website (or uses an unsupported scheme), so we do not fetch it.",
        "Check the URL for typos and make sure it starts with http:// or https://.",
    ),
    "timeout": (
        "The site took too long to respond",
        "No answer within the time limit. Slow sites are crawled less and may be skipped.",
        "Recheck later. If it keeps timing out, the site may be down or very slow.",
    ),
    "tls_error": (
        "The site's security certificate is invalid",
        "The HTTPS certificate is expired, mismatched or untrusted. Google may refuse to index the page.",
        "Ask the site owner to fix the certificate.",
    ),
    "host_unreachable": (
        "The site could not be reached",
        "The domain does not resolve or refused the connection.",
        "Check the domain for typos. If it is correct, the site may be offline.",
    ),
    "too_many_redirects": (
        "Too many redirects",
        "The URL redirects in a loop or through more than 5 addresses, so browsers and Google give up.",
        "Use the final destination URL instead.",
    ),
    "fetch_failed": (
        "The page could not be checked",
        "An unexpected error stopped the check.",
        "Recheck this URL. If it keeps failing, the site may be blocking automated requests.",
    ),
}


def fetch_problem(code: str, detail: str = "") -> Problem:
    title, why, fix = FETCH_PROBLEMS[code]
    return _problem(code, "error", title, why + (f" ({detail})" if detail else ""), fix)


def _causes(e: BaseException):
    seen = set()
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        yield e
        e = e.__cause__ or e.__context__


def classify_fetch_error(e: BaseException) -> Problem:
    chain = list(_causes(e))
    if any(isinstance(c, BlockedDestination) for c in chain):
        return fetch_problem("private_address")
    if any(isinstance(c, HostNotFound) for c in chain):
        return fetch_problem("host_unreachable")
    if any(isinstance(c, TooManyRedirects) for c in chain):
        return fetch_problem("too_many_redirects")
    if any(isinstance(c, TimeoutError) for c in chain):
        return fetch_problem("timeout")
    if any(isinstance(c, (aiohttp.ClientConnectorCertificateError, aiohttp.ClientSSLError, ssl.SSLError)) for c in chain):
        return fetch_problem("tls_error")
    if any(isinstance(c, aiohttp.ClientConnectorError) for c in chain):
        return fetch_problem("host_unreachable")
    return fetch_problem("fetch_failed", type(e).__name__)


# --------------------------------------------------------------------------- parsing

class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.robots: list[str] = []
        self.canonical: str | None = None
        self.links: list[dict] = []
        self._open: dict | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta" and a.get("name", "").lower() in ("robots", "googlebot"):
            self.robots.append(a.get("content", "").lower())
        elif tag == "link" and "canonical" in a.get("rel", "").lower().split():
            self.canonical = a.get("href") or None
        elif tag == "a" and a.get("href"):
            self._open = {"href": a["href"], "rel": a.get("rel", "").lower().split(), "text": []}
            self.links.append(self._open)
        elif tag == "img" and self._open is not None and a.get("alt"):
            self._open["text"].append(a["alt"])

    def handle_data(self, data: str) -> None:
        if self._open is not None:
            self._open["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._open = None


def _host(url: str) -> str:
    h = (urlsplit(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def _norm(url: str) -> str:
    return url.split("#")[0].rstrip("/")


def link_type(rel: list[str]) -> LinkType:
    for t in ("sponsored", "ugc", "nofollow"):
        if t in rel:
            return t  # type: ignore[return-value]
    return "follow"


def _anchor(text: list[str]) -> str:
    return re.sub(r"\s+", " ", "".join(text)).strip()[:200]


def analyze_html(html: str, page_url: str, target: str | None) -> dict:
    """Pure parsing step: robots meta, canonical and the best link to `target` (follow links win)."""
    p = _Page()
    p.feed(html)
    noindex = any("noindex" in r or r.strip() == "none" for r in p.robots)
    out: dict = {
        "noindex_meta": noindex,
        "canonical": urljoin(page_url, p.canonical)[:2000] if p.canonical else None,
    }
    if target:
        want = _host(target)
        matches = [lk for lk in p.links if _host(urljoin(page_url, lk["href"])) == want]
        matches.sort(key=lambda lk: link_type(lk["rel"]) != "follow")  # stable: follow first
        if matches:
            best = matches[0]
            out.update(backlink_found=True, backlink_rel=best["rel"], backlink_anchor=_anchor(best["text"]) or None)
        else:
            out.update(backlink_found=False, backlink_rel=[], backlink_anchor=None)
    return out


def evaluate(check: UrlCheck) -> UrlCheck:
    """Turn raw findings into problems and a verdict. Fetch failures are added by the caller."""
    problems = check.problems
    social = platform_for(check.url)
    if social:
        problems.append(social_problem(social[0], social[1], bool(check.redirects)))
    if check.status is not None:
        if check.status >= 400:
            problems.append(http_problem(check.status))
        if check.robots_allowed is False:
            problems.append(robots_blocked_problem())
        elif check.robots_allowed is None:
            problems.append(robots_unknown_problem())
        if check.noindex:
            problems.append(noindex_problem(check.noindex_source))
        if check.canonical_mismatch:
            problems.append(canonical_problem(check.canonical))
        if len(check.redirects) > 2:
            problems.append(redirect_problem(len(check.redirects)))
        if check.backlink_found is False:
            problems.append(backlink_missing_problem())
        elif check.backlink_found:
            check.backlink_type = link_type(check.backlink_rel)
            if check.backlink_type != "follow":
                problems.append(qualified_link_problem(check.backlink_type))
    check.issues = [p.title for p in problems if p.severity != "info"]
    if check.status is None:
        check.verdict = "unreachable"
    elif any(p.severity == "error" for p in problems):
        check.verdict = "blocked"
    elif any(p.severity == "warning" for p in problems):
        check.verdict = "warning"
    else:
        check.verdict = "eligible"
    return check


# --------------------------------------------------------------------------- fetching

_robots_cache: dict[str, tuple[float, robotparser.RobotFileParser | bool | None]] = {}


async def _robots_allowed(
    session: aiohttp.ClientSession, url: str, policy: FetchPolicy = DEFAULT_POLICY
) -> bool | None:
    """Can Googlebot fetch `url`? robots.txt is cached per site so 1000 URLs do not mean 1000 fetches."""
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}"
    now = time.monotonic()
    cached = _robots_cache.get(origin)
    if cached is None or now - cached[0] > ROBOTS_TTL:
        parsed: robotparser.RobotFileParser | bool | None
        try:
            got = await fetch(session, f"{origin}/robots.txt", replace(policy, max_bytes=ROBOTS_MAX_BYTES))
            if got.status >= 500:
                parsed = None
            elif got.status >= 400:
                parsed = True  # no robots.txt means everything is allowed
            else:
                parsed = robotparser.RobotFileParser()
                parsed.parse(got.text.splitlines())
        except Exception:
            parsed = None
        if len(_robots_cache) > 5000:
            _robots_cache.clear()
        cached = _robots_cache[origin] = (now, parsed)
    parsed = cached[1]
    return parsed.can_fetch("Googlebot", url) if isinstance(parsed, robotparser.RobotFileParser) else parsed


async def check_url(
    session: aiohttp.ClientSession, url: str, target: str | None = None, policy: FetchPolicy = DEFAULT_POLICY
) -> UrlCheck:
    check = UrlCheck(url=url)
    try:
        got = await fetch(session, url, policy)
    except Exception as e:
        check.problems.append(classify_fetch_error(e))
        return evaluate(check)
    final, html, headers = got.final_url, got.text, got.headers
    check.status, check.final_url, check.redirects = got.status, final[:2000], [h[:2000] for h in got.redirects]
    check.robots_allowed = await _robots_allowed(session, final, policy)

    if "noindex" in headers.get("X-Robots-Tag", "").lower():
        check.noindex, check.noindex_source = True, "X-Robots-Tag header"
    info = analyze_html(html, final, target)
    if info["noindex_meta"]:
        check.noindex, check.noindex_source = True, check.noindex_source or "meta robots tag"
    check.canonical = info["canonical"]
    if check.canonical:
        check.canonical_mismatch = _norm(check.canonical) != _norm(final)
    if target:
        check.backlink_found = info["backlink_found"]
        check.backlink_rel = info["backlink_rel"]
        check.backlink_anchor = info["backlink_anchor"]
    return evaluate(check)


async def check_urls(urls: list[str], target: str | None = None, concurrency: int = 5) -> list[UrlCheck]:
    sem = asyncio.Semaphore(concurrency)
    async with make_session() as session:

        async def one(u: str) -> UrlCheck:
            async with sem:
                return await check_url(session, u, target)

        return list(await asyncio.gather(*(one(u) for u in urls)))
