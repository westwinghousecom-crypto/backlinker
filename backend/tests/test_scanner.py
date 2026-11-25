from app.features.diagnostics import scanner
from app.features.diagnostics.scanner import UrlCheck, analyze_html, evaluate

PAGE = """<html><head>
<meta name="robots" content="index, follow">
<link rel="canonical" href="/post/1">
</head><body>
<a href="https://www.mysite.com/pricing" rel="nofollow ugc">cheap  <b>pricing</b>
 plans</a>
<a href="https://mysite.com/best"><img alt="Best tool" src="x.png"></a>
</body></html>"""


def codes(check: UrlCheck) -> set[str]:
    return {p.code for p in check.problems}


def test_analyze_prefers_follow_link_and_reads_anchor():
    r = analyze_html(PAGE, "https://blog.com/post/1", "https://mysite.com")
    assert r["backlink_found"] and r["backlink_rel"] == [] and r["backlink_anchor"] == "Best tool"
    assert r["canonical"] == "https://blog.com/post/1" and not r["noindex_meta"]


def test_analyze_qualified_link_anchor_text_is_cleaned():
    html = '<a href="https://mysite.com/x" rel="nofollow ugc">cheap  <b>pricing</b>\n plans</a>'
    r = analyze_html(html, "https://blog.com/", "https://mysite.com")
    assert r["backlink_rel"] == ["nofollow", "ugc"] and r["backlink_anchor"] == "cheap pricing plans"
    assert scanner.link_type(r["backlink_rel"]) == "ugc"


def test_analyze_noindex_and_missing_link():
    html = '<meta name="googlebot" content="NOINDEX,nofollow"><a href="/x">a</a>'
    r = analyze_html(html, "https://b.com/", "https://mysite.com")
    assert r["noindex_meta"] and r["backlink_found"] is False


def test_verdicts_and_problem_explanations():
    ok = evaluate(UrlCheck(url="u", status=200, robots_allowed=True, backlink_found=True))
    assert ok.verdict == "eligible" and not ok.issues and ok.backlink_type == "follow"
    assert ok.google_index_status == "unknown"

    noindex = evaluate(UrlCheck(url="u", status=200, robots_allowed=True, noindex=True, noindex_source="meta"))
    assert noindex.verdict == "blocked" and "noindex" in codes(noindex)
    assert all(p.explanation and p.fix for p in noindex.problems)

    assert evaluate(UrlCheck(url="u", status=200, robots_allowed=False)).verdict == "blocked"
    assert "http_error" in codes(evaluate(UrlCheck(url="u", status=404, robots_allowed=True)))
    assert evaluate(UrlCheck(url="u", status=200, robots_allowed=True, backlink_found=False)).verdict == "warning"
    qualified = evaluate(UrlCheck(url="u", status=200, robots_allowed=True, backlink_found=True, backlink_rel=["nofollow"]))
    assert qualified.verdict == "warning" and qualified.backlink_type == "nofollow"
    assert evaluate(UrlCheck(url="u")).verdict == "unreachable"


def test_unreadable_robots_is_info_only():
    c = evaluate(UrlCheck(url="u", status=200, robots_allowed=None))
    assert c.verdict == "eligible" and "robots_unknown" in codes(c) and c.issues == []


async def test_private_addresses_are_refused():
    urls = [
        "http://localhost:8000/health",
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
    ]
    for url in urls:
        res = (await scanner.check_urls([url]))[0]
        assert res.verdict == "unreachable" and "non-public" in res.issues[0], url
        assert res.problems[0].code == "private_address" and res.problems[0].fix


class _FakeStream:
    """Delivers the body in small chunks, like a real network stream."""

    def __init__(self, body: bytes, size: int = 7):
        self._chunks = [body[i : i + size] for i in range(0, len(body), size)]

    async def iter_chunked(self, n):
        for c in self._chunks:
            yield c


async def test_read_limited_returns_whole_body_not_first_chunk():
    from app.core.safe_fetch import read_limited

    body = b"<html>" + b"x" * 5000 + b"</html>"
    data, truncated = await read_limited(_FakeStream(body), 1_000_000)
    assert data == body and not truncated
    data, truncated = await read_limited(_FakeStream(body, size=50), 100)
    assert len(data) == 100 and truncated


async def test_unknown_domain_is_unreachable_not_private():
    res = (await scanner.check_urls(["https://this-domain-does-not-exist-qi-test.invalid/"]))[0]
    assert res.verdict == "unreachable" and res.problems[0].code == "host_unreachable"
