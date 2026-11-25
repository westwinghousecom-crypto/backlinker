import re
from pathlib import Path

import pytest

from app.features.diagnostics.scanner import UrlCheck, evaluate
from app.features.diagnostics.social import PLATFORMS, platform_for

TS = Path(__file__).resolve().parents[2] / "frontend" / "src" / "features" / "submission" / "lib" / "social.ts"


@pytest.mark.parametrize("url,expected", [
    ("https://www.facebook.com/share/p/1JaLqV9B7M/", "facebook"),
    ("https://m.facebook.com/story.php?id=1", "facebook"),
    ("https://fb.watch/abc/", "facebook"),
    ("https://www.instagram.com/p/xyz/", "instagram"),
    ("https://x.com/user/status/1", "x"),
    ("https://twitter.com/user/status/1", "x"),
    ("https://www.linkedin.com/posts/abc", "linkedin"),
    ("https://youtu.be/abc", "youtube"),
    ("https://www.reddit.com/r/x/comments/1/", "reddit"),
    ("https://www.pinterest.com/pin/1/", "pinterest"),
    ("https://www.tiktok.com/@u/video/1", "tiktok"),
    ("HTTPS://WWW.FACEBOOK.COM/x", "facebook"),
    ("https://www.facebook.com./x", "facebook"),
])
def test_known_social_links_are_recognised(url, expected):
    assert platform_for(url)[0] == expected


@pytest.mark.parametrize("url", [
    "https://westwinghouse.com/west-wing-writings/post",
    "https://notfacebook.com/x", "https://facebook.com.evil.example/x", "https://example.com/facebook.com",
    "https://myx.com/", "not a url", "", "https://medium.com/@someone/post",
])
def test_ordinary_and_lookalike_sites_are_not_flagged(url):
    assert platform_for(url) is None


def test_social_link_gets_a_warning_with_plain_advice_even_when_otherwise_fine():
    c = evaluate(UrlCheck(url="https://www.linkedin.com/posts/abc", status=200, robots_allowed=True))
    p = next(p for p in c.problems if p.code == "social_platform")
    assert p.severity == "warning" and c.verdict == "warning"
    assert "linkedin" in p.title.lower() and "Submitting cannot override this" in p.explanation and p.fix


def test_share_link_that_redirected_tells_the_customer_to_submit_the_real_post():
    c = evaluate(UrlCheck(url="https://www.facebook.com/share/p/1JaLqV9B7M/", status=200, robots_allowed=True,
                          redirects=["https://www.facebook.com/share/p/1JaLqV9B7M/"],
                          final_url="https://www.facebook.com/page/posts/123"))
    assert "submit the final address" in next(p for p in c.problems if p.code == "social_platform").explanation


def test_a_noindex_facebook_page_is_blocked_and_still_explained():
    c = evaluate(UrlCheck(url="https://www.facebook.com/page/posts/1", status=200, robots_allowed=True, noindex=True, noindex_source="meta robots tag"))
    assert c.verdict == "blocked" and {"noindex", "social_platform"} <= {p.code for p in c.problems}


def test_non_social_pages_are_unaffected():
    c = evaluate(UrlCheck(url="https://westwinghouse.com/post", status=200, robots_allowed=True))
    assert c.verdict == "eligible" and not any(p.code == "social_platform" for p in c.problems)


def test_unreachable_social_link_still_gets_the_guidance():
    c = evaluate(UrlCheck(url="https://www.facebook.com/gone"))
    assert c.verdict == "unreachable" and any(p.code == "social_platform" for p in c.problems)


def test_frontend_and_backend_platform_lists_match():
    src = TS.read_text(encoding="utf-8")
    block = re.findall(r'name: "([a-z]+)",\s*hosts: \[([^\]]*)\],\s*advice: "([^"]*)"', src)
    front = {n: (tuple(re.findall(r'"([^"]+)"', h)), a) for n, h, a in block}
    assert front == {n: (hosts, advice) for n, (hosts, advice) in PLATFORMS.items()}


def test_missing_link_is_described_as_not_in_the_html_and_mentions_javascript():
    c = evaluate(UrlCheck(url="https://blog.example/post", status=200, robots_allowed=True, backlink_found=False))
    p = next(p for p in c.problems if p.code == "backlink_missing")
    assert "not found in the page HTML" in p.title
    assert "JavaScript" in p.explanation and "browser" in p.fix
    assert c.verdict == "warning"  # a warning to look at, never an error: we may simply not see a JS-added link
