"""Turn a Google URL Inspection API response into a QuickIndex status.

THE RULE: a page is reported as indexed or not indexed only because Google's own URL Inspection API said so for this
exact URL, on a property the customer controls. Nothing else (HTTP checks, IndexNow, WebSub, sitemaps, Common Crawl,
social posts) can produce these statuses. This module only ever receives a Google inspection response.

Google's ``indexStatusResult.verdict`` (https://developers.google.com/webmaster-tools/v1/urlInspection.index/inspect):
  PASS     -> the URL is on Google              => Confirmed Indexed
  FAIL     -> an error stops indexing           => Confirmed Not Indexed
  NEUTRAL  -> excluded (noindex, duplicate, "crawled - currently not indexed", ...) => Confirmed Not Indexed
  PARTIAL / VERDICT_UNSPECIFIED / missing      => Unknown (we will not guess)
"""
from dataclasses import asdict, dataclass, field

INDEXED = "indexed"
NOT_INDEXED = "not_indexed"
UNKNOWN = "unknown"

LABELS = {
    INDEXED: "Confirmed Indexed",
    NOT_INDEXED: "Confirmed Not Indexed",
    UNKNOWN: "Unknown",
    "failed": "Inspection Failed",
}


@dataclass
class Inspection:
    status: str  # indexed | not_indexed | unknown
    verdict: str | None = None
    coverage_state: str | None = None
    robots_txt_state: str | None = None
    indexing_state: str | None = None
    page_fetch_state: str | None = None
    last_crawl_time: str | None = None
    google_canonical: str | None = None
    user_canonical: str | None = None
    crawled_as: str | None = None
    sitemaps: list[str] = field(default_factory=list)
    referring_urls: int = 0
    inspection_link: str | None = None
    note: str | None = None  # plain-English reason for the status

    def to_dict(self) -> dict:
        """The evidence Google returned. The status itself is stored and sent separately."""
        d = asdict(self)
        d.pop("status")
        return d


def _s(v) -> str | None:
    return str(v) if v not in (None, "") else None


def map_inspection(response: dict) -> Inspection:
    """`response` is the JSON body of Google's index:inspect call."""
    result = (response or {}).get("inspectionResult") or {}
    idx = result.get("indexStatusResult") or {}
    verdict = _s(idx.get("verdict"))
    insp = Inspection(
        status=UNKNOWN,
        verdict=verdict,
        coverage_state=_s(idx.get("coverageState")),
        robots_txt_state=_s(idx.get("robotsTxtState")),
        indexing_state=_s(idx.get("indexingState")),
        page_fetch_state=_s(idx.get("pageFetchState")),
        last_crawl_time=_s(idx.get("lastCrawlTime")),
        google_canonical=_s(idx.get("googleCanonical")),
        user_canonical=_s(idx.get("userCanonical")),
        crawled_as=_s(idx.get("crawledAs")),
        sitemaps=[str(x) for x in (idx.get("sitemap") or [])][:20],
        referring_urls=len(idx.get("referringUrls") or []),
        inspection_link=_s(result.get("inspectionResultLink")),
    )
    cov = insp.coverage_state or "no coverage detail"
    if verdict == "PASS":
        insp.status = INDEXED
        insp.note = f"Google reports this URL is indexed ({cov})."
        gc, uc = (insp.google_canonical or "").rstrip("/"), (insp.user_canonical or "").rstrip("/")
        if gc and uc and gc != uc:
            insp.note += " Google chose a different canonical URL than the one you declared, so check which address appears in search."
    elif verdict in ("FAIL", "NEUTRAL"):
        insp.status = NOT_INDEXED
        insp.note = f"Google reports this URL is not indexed ({cov})."
    elif verdict == "PARTIAL":
        insp.note = "Google reports a partial result, so we cannot say whether the page is indexed."
    else:
        insp.note = "Google did not return an indexing verdict for this URL."
    return insp


def display_status(latest_status: str | None, latest_outcome: str | None) -> str:
    """What the dashboard shows: the latest attempt failed -> 'failed'; never inspected -> 'unknown'."""
    if latest_outcome == "failed":
        return "failed"
    return latest_status if latest_status in (INDEXED, NOT_INDEXED) else UNKNOWN
