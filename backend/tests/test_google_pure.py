"""Pure-logic tests for the Google Search Console modules: crypto, properties, mapping and the API layer.

Nothing here talks to Google or Appwrite: the HTTP layer is replaced with fakes.
"""
import asyncio
import time

import aiohttp
import pytest

from app.core.config import get_settings
from app.features.google import api, crypto
from app.features.google.crypto import CryptoError, NotConfigured
from app.features.google.mapping import (
    INDEXED,
    NOT_INDEXED,
    UNKNOWN,
    display_status,
    map_inspection,
)
from app.features.google.properties import (
    DOMAIN_PREFIX,
    parse_property,
    url_in_property,
)

SECRET_TOKEN = "1//0gSUPER-SECRET-REFRESH-TOKEN-abc123"
ACCESS_TOKEN = "ya29.a0-SECRET-ACCESS-TOKEN"


# ---------------------------------------------------------------------------------------------- crypto

@pytest.fixture
def keys(monkeypatch):
    """Configure TOKEN_ENCRYPTION_KEY for a test and always restore the settings cache afterwards."""

    def set_keys(value: str):
        monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", value)
        get_settings.cache_clear()

    get_settings.cache_clear()
    yield set_keys
    get_settings.cache_clear()


def test_token_round_trip_and_ciphertext_hides_the_token(keys):
    keys(crypto.generate_key())
    blob = crypto.encrypt_token("user-1", SECRET_TOKEN)
    assert crypto.decrypt_token("user-1", blob) == SECRET_TOKEN
    assert SECRET_TOKEN not in blob and "SECRET" not in blob
    assert blob != SECRET_TOKEN


def test_encrypting_twice_gives_different_ciphertexts(keys):
    keys(crypto.generate_key())
    assert crypto.encrypt_token("u", "t") != crypto.encrypt_token("u", "t")  # random IV: no equality leak


def test_token_is_bound_to_the_owning_customer(keys):
    keys(crypto.generate_key())
    blob = crypto.encrypt_token("user-A", SECRET_TOKEN)
    with pytest.raises(CryptoError):
        crypto.decrypt_token("user-B", blob)  # a row copied to another customer is useless to them


def test_tampered_or_garbage_blobs_are_rejected(keys):
    keys(crypto.generate_key())
    blob = crypto.encrypt_token("u", SECRET_TOKEN)
    flipped = blob[:-4] + ("AAAA" if not blob.endswith("AAAA") else "BBBB")
    for bad in (flipped, "", "not-a-fernet-token", blob[:20], "A" * 120):
        with pytest.raises(CryptoError):
            crypto.decrypt_token("u", bad)


def test_decrypting_with_a_different_key_fails(keys):
    keys(crypto.generate_key())
    blob = crypto.encrypt_token("u", "t")
    keys(crypto.generate_key())
    with pytest.raises(CryptoError):
        crypto.decrypt_token("u", blob)


def test_sealed_state_round_trip_and_tamper(keys):
    keys(crypto.generate_key())
    payload = {"u": "user-1", "v": "pkce-verifier", "w": True, "n": "nonce"}
    sealed = crypto.seal_state(payload)
    assert crypto.open_state(sealed) == payload
    assert "pkce-verifier" not in sealed and "user-1" not in sealed  # state is encrypted, not just signed
    with pytest.raises(CryptoError):
        crypto.open_state(sealed[:-3] + "xyz")
    with pytest.raises(CryptoError):
        crypto.open_state("totally-forged")


def test_sealed_state_expires(keys):
    keys(crypto.generate_key())
    sealed = crypto.seal_state({"u": "x"})
    assert crypto.open_state(sealed, max_age_seconds=600) == {"u": "x"}
    time.sleep(1.2)  # Fernet timestamps have one-second resolution
    with pytest.raises(CryptoError):
        crypto.open_state(sealed, max_age_seconds=0)


def test_state_from_another_server_key_is_rejected(keys):
    keys(crypto.generate_key())
    sealed = crypto.seal_state({"u": "x"})
    keys(crypto.generate_key())
    with pytest.raises(CryptoError):
        crypto.open_state(sealed)


def test_key_rotation_old_blobs_still_decrypt(keys):
    old, new = crypto.generate_key(), crypto.generate_key()
    keys(old)
    old_blob = crypto.encrypt_token("u", SECRET_TOKEN)
    old_state = crypto.seal_state({"u": "x"})
    keys(f"{new},{old}")  # the first key encrypts, every key can decrypt
    assert crypto.decrypt_token("u", old_blob) == SECRET_TOKEN
    assert crypto.open_state(old_state) == {"u": "x"}
    new_blob = crypto.encrypt_token("u", "fresh")
    keys(new)  # the old key can be retired once data has been re-encrypted
    assert crypto.decrypt_token("u", new_blob) == "fresh"
    with pytest.raises(CryptoError):
        crypto.decrypt_token("u", old_blob)


@pytest.mark.parametrize("bad_key", ["", "   ", ",", "not-a-valid-fernet-key", "short"])
def test_missing_or_invalid_key_is_not_configured(keys, bad_key):
    keys(bad_key)
    with pytest.raises(NotConfigured):
        crypto.encrypt_token("u", "t")
    with pytest.raises(NotConfigured):
        crypto.seal_state({"a": 1})


# ---------------------------------------------------------------------------------------------- properties

@pytest.mark.parametrize(
    "entry, type_, verified, can_write",
    [
        ({"siteUrl": "sc-domain:example.com", "permissionLevel": "siteOwner"}, "domain", True, True),
        ({"siteUrl": "https://www.example.com/", "permissionLevel": "siteFullUser"}, "url_prefix", True, True),
        ({"siteUrl": "https://example.com/blog/", "permissionLevel": "siteRestrictedUser"}, "url_prefix", True, False),
        ({"siteUrl": "sc-domain:example.org", "permissionLevel": "siteUnverifiedUser"}, "domain", False, False),
        ({"siteUrl": "http://example.net/", "permissionLevel": ""}, "url_prefix", False, False),
        ({"siteUrl": "https://odd.example/"}, "url_prefix", False, False),
    ],
)
def test_parse_property_type_and_permissions(entry, type_, verified, can_write):
    p = parse_property(entry)
    assert (p.type, p.verified, p.can_write) == (type_, verified, can_write)
    assert p.site_url == entry["siteUrl"]


def test_property_labels_distinguish_domain_and_prefix():
    d = parse_property({"siteUrl": "sc-domain:example.com", "permissionLevel": "siteOwner"}).as_dict()
    u = parse_property({"siteUrl": "https://example.com/", "permissionLevel": "siteOwner"}).as_dict()
    assert d["type"] == "domain" and d["label"] == "example.com" and d["site_url"] == "sc-domain:example.com"
    assert u["type"] == "url_prefix" and u["label"] == "https://example.com/"
    assert set(d) == {"site_url", "type", "permission", "verified", "can_write", "label"}


DOMAIN = "sc-domain:example.com"
PREFIX = "https://www.example.com/"
BLOG = "https://example.com/blog/"

OWNERSHIP_CASES = [
    # ---- domain property: apex, subdomains, both schemes
    (DOMAIN, "https://example.com/", True),
    (DOMAIN, "http://example.com/page", True),
    (DOMAIN, "https://www.example.com/a/b?x=1#frag", True),
    (DOMAIN, "https://a.b.c.example.com/", True),
    (DOMAIN, "  https://example.com/padded  ", True),
    (DOMAIN, "https://EXAMPLE.COM/Upper", True),
    (DOMAIN, "https://example.com./", True),  # trailing-dot FQDN
    (DOMAIN, "https://example.com:8443/x", True),  # a domain property covers every port
    ("sc-domain:EXAMPLE.COM", "https://example.com/", True),  # property written in upper case
    # ---- domain property: look-alikes and other sites
    (DOMAIN, "https://example.com.evil.com/", False),
    (DOMAIN, "https://notexample.com/", False),
    (DOMAIN, "https://evilexample.com/", False),
    (DOMAIN, "https://example.org/", False),
    (DOMAIN, "https://example.co/", False),
    (DOMAIN, "https://com/", False),
    (DOMAIN, "https://evil.com/?u=https://example.com/", False),
    (DOMAIN, "https://evil.com/example.com/", False),
    (DOMAIN, "https://example.com@evil.com/", False),  # userinfo trick: the real host is evil.com
    (DOMAIN, "https://user:pw@example.com/", False),
    (DOMAIN, "https://user@example.com/", False),
    (DOMAIN, "https://example.com:99999/", False),  # malformed port
    (DOMAIN, "https://example.com:abc/", False),
    ("sc-domain:", "https://example.com/", False),
    ("sc-domain:", "https:///", False),
    # ---- url-prefix property: scheme, host (www matters), port
    (PREFIX, "https://www.example.com/", True),
    (PREFIX, "https://www.example.com/anything/here?q=1", True),
    (PREFIX, "https://WWW.Example.COM/Caps", True),
    (PREFIX, "https://www.example.com:443/x", True),  # default port is the same port
    (PREFIX, "http://www.example.com/", False),  # scheme differs
    (PREFIX, "https://example.com/", False),  # www differs
    (PREFIX, "https://blog.www.example.com/", False),  # subdomains are not covered by a prefix property
    (PREFIX, "https://www.example.com:8443/", False),
    (PREFIX, "https://www.example.com.evil.com/", False),
    ("http://example.com/", "http://example.com:80/x", True),
    ("http://example.com/", "http://example.com:8080/x", False),
    ("https://example.com:8443/", "https://example.com:8443/x", True),
    ("https://example.com:8443/", "https://example.com/x", False),
    # ---- url-prefix property: path boundary
    (BLOG, "https://example.com/blog/", True),
    (BLOG, "https://example.com/blog/a", True),
    (BLOG, "https://example.com/blog/a/b/c?x=1", True),
    (BLOG, "https://example.com/blog", False),  # no trailing slash: outside the /blog/ prefix
    (BLOG, "https://example.com/blog-evil/", False),
    (BLOG, "https://example.com/blogger/", False),
    (BLOG, "https://example.com/", False),
    (BLOG, "https://example.com/other/blog/", False),
    (BLOG, "https://example.com/BLOG/a", False),  # paths are case-sensitive
    ("https://example.com/blog", "https://example.com/blog/a", True),  # prefix given without trailing slash
    ("https://example.com/blog", "https://example.com/blogger/", False),
    # ---- never inspect non-web or credential-carrying URLs
    (PREFIX, "https://user:pass@www.example.com/", False),
    (PREFIX, "https://user@www.example.com/", False),
    (PREFIX, "ftp://www.example.com/", False),
    (DOMAIN, "ftp://example.com/", False),
    (PREFIX, "javascript:alert(1)", False),
    (DOMAIN, "javascript:alert(1)//example.com", False),
    (DOMAIN, "file:///etc/passwd", False),
    (DOMAIN, "data:text/html,example.com", False),
    (DOMAIN, "//example.com/page", False),  # scheme-relative
    (DOMAIN, "example.com/page", False),  # no scheme
    (DOMAIN, "", False),
    (DOMAIN, "   ", False),
    (PREFIX, "not a url", False),
    # ---- junk property values never match
    ("not a url", "https://example.com/", False),
    ("", "https://example.com/", False),
    ("ftp://example.com/", "ftp://example.com/", False),
    ("https:///path", "https://example.com/path", False),
]


@pytest.mark.parametrize("site_url, url, expected", OWNERSHIP_CASES)
def test_url_in_property(site_url, url, expected):
    assert url_in_property(url, site_url) is expected, f"{url!r} in {site_url!r}"


def test_idn_hosts_are_normalised_to_punycode():
    assert url_in_property("https://BÜCHER.example/seite", "sc-domain:xn--bcher-kva.example")
    assert url_in_property("https://xn--bcher-kva.example/", "sc-domain:bücher.example")
    assert url_in_property("https://shop.bücher.example/", "sc-domain:bücher.example")
    assert url_in_property("https://bücher.example/a", "https://xn--bcher-kva.example/")
    assert not url_in_property("https://bucher.example/", "sc-domain:bücher.example")


def test_domain_prefix_constant_matches_google_format():
    assert DOMAIN_PREFIX == "sc-domain:"


# ---------------------------------------------------------------------------------------------- mapping

def inspection(**idx):
    return {"inspectionResult": {"inspectionResultLink": "https://search.google.com/search-console/inspect?x=1",
                                 "indexStatusResult": idx}}


@pytest.mark.parametrize(
    "idx, expected",
    [
        (dict(verdict="PASS", coverageState="Submitted and indexed", indexingState="INDEXING_ALLOWED"), INDEXED),
        (dict(verdict="PASS", coverageState="Indexed, not submitted in sitemap"), INDEXED),
        (dict(verdict="NEUTRAL", coverageState="Crawled - currently not indexed"), NOT_INDEXED),
        (dict(verdict="NEUTRAL", coverageState="Excluded by 'noindex' tag", indexingState="BLOCKED_BY_META_TAG"), NOT_INDEXED),
        (dict(verdict="NEUTRAL", coverageState="Duplicate, Google chose different canonical than user"), NOT_INDEXED),
        (dict(verdict="NEUTRAL", coverageState="Discovered - currently not indexed"), NOT_INDEXED),
        (dict(verdict="FAIL", coverageState="Server error (5xx)", pageFetchState="SERVER_ERROR"), NOT_INDEXED),
        (dict(verdict="FAIL", coverageState="Not found (404)", pageFetchState="NOT_FOUND"), NOT_INDEXED),
        (dict(verdict="PARTIAL", coverageState="Indexed with problems"), UNKNOWN),
        (dict(verdict="VERDICT_UNSPECIFIED", coverageState="URL is unknown to Google"), UNKNOWN),
        (dict(coverageState="Something new Google added"), UNKNOWN),
        (dict(), UNKNOWN),
    ],
)
def test_verdict_to_status_mapping(idx, expected):
    assert map_inspection(inspection(**idx)).status == expected


@pytest.mark.parametrize("body", [{}, None, {"inspectionResult": {}}, {"inspectionResult": None},
                                  {"inspectionResult": {"indexStatusResult": None}}, {"other": 1}])
def test_empty_or_malformed_responses_are_unknown_not_errors(body):
    r = map_inspection(body)
    assert r.status == UNKNOWN and r.verdict is None and r.note


def test_unrecognised_verdicts_are_not_guessed():
    for v in ("pass", "Pass", "ok", "indexed", "true", "1", " PASS", "PASS "):
        assert map_inspection(inspection(verdict=v)).status == UNKNOWN, v


def test_field_extraction_from_a_full_google_response():
    body = {
        "inspectionResult": {
            "inspectionResultLink": "https://search.google.com/search-console/inspect?resource_id=sc-domain%3Aexample.com",
            "indexStatusResult": {
                "verdict": "NEUTRAL",
                "coverageState": "Excluded by 'noindex' tag",
                "robotsTxtState": "ALLOWED",
                "indexingState": "BLOCKED_BY_META_TAG",
                "pageFetchState": "SUCCESSFUL",
                "lastCrawlTime": "2026-11-01T08:15:30Z",
                "googleCanonical": "https://example.com/canonical",
                "userCanonical": "https://example.com/declared",
                "crawledAs": "MOBILE",
                "sitemap": ["https://example.com/sitemap.xml", "https://example.com/sitemap-2.xml"],
                "referringUrls": ["https://example.com/a", "https://example.com/b", "https://example.com/c"],
            },
        }
    }
    r = map_inspection(body)
    assert r.status == NOT_INDEXED and r.verdict == "NEUTRAL"
    assert r.coverage_state == "Excluded by 'noindex' tag"
    assert r.robots_txt_state == "ALLOWED"
    assert r.indexing_state == "BLOCKED_BY_META_TAG"
    assert r.page_fetch_state == "SUCCESSFUL"
    assert r.last_crawl_time == "2026-11-01T08:15:30Z"
    assert r.google_canonical == "https://example.com/canonical"
    assert r.user_canonical == "https://example.com/declared"
    assert r.google_canonical != r.user_canonical  # a mismatch is visible to the dashboard
    assert r.crawled_as == "MOBILE"
    assert r.sitemaps == ["https://example.com/sitemap.xml", "https://example.com/sitemap-2.xml"]
    assert r.referring_urls == 3
    assert r.inspection_link.startswith("https://search.google.com/search-console/inspect")
    assert "not indexed" in r.note and "noindex" in r.note
    d = r.to_dict()
    assert r.status == NOT_INDEXED and "status" not in d and d["referring_urls"] == 3 and d["sitemaps"][0].endswith("sitemap.xml")


def test_robots_blocked_page_fields():
    r = map_inspection(inspection(verdict="NEUTRAL", coverageState="Blocked by robots.txt",
                                  robotsTxtState="DISALLOWED", indexingState="BLOCKED_BY_ROBOTS_TXT",
                                  pageFetchState="BLOCKED_ROBOTS_TXT"))
    assert (r.status, r.robots_txt_state, r.indexing_state) == (NOT_INDEXED, "DISALLOWED", "BLOCKED_BY_ROBOTS_TXT")


def test_blank_values_become_none_and_lists_are_bounded():
    r = map_inspection(inspection(verdict="PASS", coverageState="", googleCanonical="", sitemap=[f"https://e.com/s{i}.xml" for i in range(50)]))
    assert r.coverage_state is None and r.google_canonical is None and len(r.sitemaps) == 20


def test_non_google_evidence_can_never_create_an_indexed_status():
    """HTTP eligibility, IndexNow, WebSub, Common Crawl and social posts are not Google inspection results."""
    fake_evidence = {"indexnow": "ok", "websub": "ok", "http_status": 200, "eligible": True, "common_crawl": True,
                     "social": "posted", "status": "indexed", "verdict": "PASS"}
    r = map_inspection(fake_evidence)
    assert r.status == UNKNOWN and r.verdict is None
    # a PASS verdict outside Google's inspectionResult envelope is also ignored
    assert map_inspection({"indexStatusResult": {"verdict": "PASS"}}).status == UNKNOWN
    assert map_inspection({"inspectionResult": {"verdict": "PASS"}}).status == UNKNOWN


def test_display_status_rules():
    assert display_status("indexed", "failed") == "failed"  # a failed latest attempt wins over the last known status
    assert display_status("not_indexed", "failed") == "failed"
    assert display_status(None, "failed") == "failed"
    assert display_status(None, None) == UNKNOWN  # never inspected
    assert display_status("indexed", "success") == INDEXED
    assert display_status("not_indexed", None) == NOT_INDEXED
    assert display_status("unknown", "success") == UNKNOWN
    assert display_status("bogus", "success") == UNKNOWN
    assert display_status("", "") == UNKNOWN


# ---------------------------------------------------------------------------------------------- api layer

class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def __call__(self, method, url, *, headers=None, data=None, json_body=None):
        self.calls.append({"method": method, "url": url, "headers": headers or {}, "data": data, "json": json_body})
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.fixture
def transport():
    def install(*responses):
        t = FakeTransport(*responses)
        api.set_transport(t)
        return t

    yield install
    api.set_transport(None)  # always restore the real transport


def resp(status, body=None, **headers):
    return api.Response(status, body, {k.lower().replace("_", "-"): v for k, v in headers.items()})


def google_error(code, status, message="boom", reason=None):
    err = {"code": code, "message": message, "status": status}
    if reason:
        err["errors"] = [{"reason": reason, "message": message}]
    return {"error": err}


async def error_of(coro) -> api.GoogleApiError:
    with pytest.raises(api.GoogleApiError) as exc:
        await coro
    return exc.value


@pytest.mark.parametrize(
    "response, kind",
    [
        (resp(401, google_error(401, "UNAUTHENTICATED", "Invalid Credentials")), "auth"),
        (resp(403, google_error(403, "PERMISSION_DENIED", "User does not have sufficient permission for site", "forbidden")), "permission"),
        (resp(403, google_error(403, "PERMISSION_DENIED", "Quota exceeded", "quotaExceeded")), "quota"),
        (resp(403, google_error(403, "PERMISSION_DENIED", "Daily Limit Exceeded", "dailyLimitExceeded")), "quota"),
        (resp(403, google_error(403, "PERMISSION_DENIED", "Rate Limit Exceeded", "rateLimitExceeded")), "quota"),
        (resp(403, google_error(403, "RESOURCE_EXHAUSTED", "Quota exceeded")), "quota"),
        (resp(429, google_error(429, "RESOURCE_EXHAUSTED", "Quota exceeded for quota metric")), "quota"),
        (resp(404, google_error(404, "NOT_FOUND", "Not found")), "not_found"),
        (resp(400, google_error(400, "INVALID_ARGUMENT", "URL not in property")), "bad_request"),
        (resp(422, None), "bad_request"),
        (resp(500, google_error(500, "INTERNAL", "Internal error")), "transient"),
        (resp(503, google_error(503, "UNAVAILABLE", "The service is currently unavailable")), "transient"),
        (resp(502, None), "transient"),
        (resp(504, None), "transient"),
    ],
)
async def test_error_classification(transport, response, kind):
    transport(response)
    err = await error_of(api.call("GET", api.SITES_URL, ACCESS_TOKEN))
    assert err.kind == kind and err.status == response.status


async def test_quota_error_carries_retry_after(transport):
    transport(resp(429, google_error(429, "RESOURCE_EXHAUSTED", "Quota exceeded"), retry_after="30"))
    err = await error_of(api.call("POST", api.INSPECT_URL, ACCESS_TOKEN, json_body={}))
    assert err.kind == "quota" and err.retry_after == 30.0


async def test_unparseable_retry_after_is_ignored(transport):
    transport(resp(429, None, retry_after="Wed, 21 Oct 2026 07:28:00 GMT"))
    err = await error_of(api.call("GET", api.SITES_URL, ACCESS_TOKEN))
    assert err.kind == "quota" and err.retry_after is None


async def test_oauth_invalid_grant_is_a_bad_request_with_its_code(transport):
    transport(resp(400, {"error": "invalid_grant", "error_description": "Token has been expired or revoked."}))
    err = await error_of(api.call("POST", api.TOKEN_URL, data={"grant_type": "refresh_token"}))
    assert err.kind == "bad_request" and err.code == "invalid_grant"
    assert err.message == "Token has been expired or revoked."


async def test_network_failures_are_transient(transport):
    for exc in (aiohttp.ClientError("connection reset"), aiohttp.ClientConnectionError("down"),
                asyncio.TimeoutError(), TimeoutError("slow"), OSError("network unreachable")):
        transport(exc)
        err = await error_of(api.call("GET", api.SITES_URL, ACCESS_TOKEN))
        assert err.kind == "transient" and err.status == 0


async def test_error_messages_never_contain_the_access_token(transport):
    transport(aiohttp.ClientError(f"request failed for token {ACCESS_TOKEN}"))
    err = await error_of(api.call("GET", api.SITES_URL, ACCESS_TOKEN))
    assert ACCESS_TOKEN not in str(err) and ACCESS_TOKEN not in err.message
    transport(resp(401, google_error(401, "UNAUTHENTICATED", "Invalid Credentials")))
    err = await error_of(api.call("GET", api.SITES_URL, ACCESS_TOKEN))
    assert ACCESS_TOKEN not in str(err) and ACCESS_TOKEN not in repr(err.args)


async def test_long_google_messages_are_truncated(transport):
    transport(resp(400, google_error(400, "INVALID_ARGUMENT", "x" * 5000)))
    err = await error_of(api.call("GET", api.SITES_URL, ACCESS_TOKEN))
    assert len(err.message) <= 200


async def test_success_with_empty_body_returns_empty_dict(transport):
    t = transport(resp(200, None))
    assert await api.call("PUT", api.SITES_URL, ACCESS_TOKEN) == {}
    assert t.calls[0]["headers"] == {"Authorization": f"Bearer {ACCESS_TOKEN}"}


async def test_oauth_calls_send_no_authorization_header(transport):
    t = transport(resp(200, {"access_token": "new"}))
    await api.call("POST", api.TOKEN_URL, data={"grant_type": "refresh_token"})
    assert t.calls[0]["headers"] == {} and t.calls[0]["data"] == {"grant_type": "refresh_token"}


async def test_list_sites_request_and_result(transport):
    entries = [{"siteUrl": "sc-domain:example.com", "permissionLevel": "siteOwner"}]
    t = transport(resp(200, {"siteEntry": entries}))
    assert await api.list_sites(ACCESS_TOKEN) == entries
    c = t.calls[0]
    assert (c["method"], c["url"]) == ("GET", "https://www.googleapis.com/webmasters/v3/sites")
    assert c["headers"]["Authorization"] == f"Bearer {ACCESS_TOKEN}"


async def test_list_sites_handles_an_account_without_properties(transport):
    transport(resp(200, {}))
    assert await api.list_sites(ACCESS_TOKEN) == []


@pytest.mark.parametrize(
    "site, encoded",
    [
        ("sc-domain:example.com", "sc-domain%3Aexample.com"),
        ("https://example.com/", "https%3A%2F%2Fexample.com%2F"),
        ("https://www.example.com/blog/", "https%3A%2F%2Fwww.example.com%2Fblog%2F"),
    ],
)
async def test_site_urls_are_fully_percent_encoded_in_paths(transport, site, encoded):
    t = transport(resp(200, {"sitemap": [{"path": f"{site}sitemap.xml"}]}))
    out = await api.list_sitemaps(ACCESS_TOKEN, site)
    assert out == [{"path": f"{site}sitemap.xml"}]
    c = t.calls[0]
    assert c["method"] == "GET"
    assert c["url"] == f"https://www.googleapis.com/webmasters/v3/sites/{encoded}/sitemaps"
    assert c["headers"]["Authorization"] == f"Bearer {ACCESS_TOKEN}"


async def test_submit_sitemap_uses_put_and_encodes_both_site_and_feedpath(transport):
    t = transport(resp(204, None))
    await api.submit_sitemap(ACCESS_TOKEN, "https://example.com/", "https://example.com/sitemap.xml?x=1&y=2")
    c = t.calls[0]
    assert c["method"] == "PUT"
    assert c["url"] == ("https://www.googleapis.com/webmasters/v3/sites/https%3A%2F%2Fexample.com%2F/sitemaps/"
                        "https%3A%2F%2Fexample.com%2Fsitemap.xml%3Fx%3D1%26y%3D2")
    assert c["headers"]["Authorization"] == f"Bearer {ACCESS_TOKEN}"
    assert "/sitemaps/https://" not in c["url"]  # a raw URL would break out of the path segment


async def test_submit_sitemap_domain_property(transport):
    t = transport(resp(200, None))
    await api.submit_sitemap(ACCESS_TOKEN, "sc-domain:example.com", "https://example.com/sitemap.xml")
    assert t.calls[0]["url"].startswith("https://www.googleapis.com/webmasters/v3/sites/sc-domain%3Aexample.com/sitemaps/https%3A")


async def test_inspect_url_request_shape(transport):
    body = inspection(verdict="PASS", coverageState="Submitted and indexed")
    t = transport(resp(200, body))
    out = await api.inspect_url(ACCESS_TOKEN, "https://example.com/page", "sc-domain:example.com")
    assert out == body
    c = t.calls[0]
    assert (c["method"], c["url"]) == ("POST", "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect")
    assert c["headers"]["Authorization"] == f"Bearer {ACCESS_TOKEN}"
    assert c["json"] == {"inspectionUrl": "https://example.com/page", "siteUrl": "sc-domain:example.com", "languageCode": "en-US"}
    assert map_inspection(out).status == INDEXED


async def test_api_errors_propagate_from_each_helper(transport):
    transport(resp(403, google_error(403, "PERMISSION_DENIED", "No access", "forbidden")))
    for coro in (api.list_sites(ACCESS_TOKEN), api.list_sitemaps(ACCESS_TOKEN, "sc-domain:e.com"),
                 api.inspect_url(ACCESS_TOKEN, "https://e.com/", "sc-domain:e.com"),
                 api.submit_sitemap(ACCESS_TOKEN, "sc-domain:e.com", "https://e.com/s.xml")):
        assert (await error_of(coro)).kind == "permission"


def test_set_transport_none_restores_the_real_transport():
    api.set_transport(FakeTransport(resp(200, {})))
    assert api.transport is not api._aiohttp_transport
    api.set_transport(None)
    assert api.transport is api._aiohttp_transport
