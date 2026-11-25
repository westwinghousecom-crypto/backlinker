/** API-shaped fixtures for TESTS ONLY (the contract's JSON). The shipped UI never contains mock data. */
import type {
  GoogleProperty,
  GoogleStatus,
  HistoryEntry,
  Inspection,
  SitemapList,
  Target,
} from "./types";

export function status(over: Partial<GoogleStatus> = {}): GoogleStatus {
  return {
    configured: true,
    connected: true,
    state: "active",
    email: "owner@example.com",
    can_write: false,
    reauth_required: false,
    selected_property: "sc-domain:mysite.com",
    quota: { property: "sc-domain:mysite.com", per_day_limit: 2000, used_today: 40, per_minute_limit: 600 },
    ...over,
  };
}

export function inspection(over: Partial<Inspection> = {}): Inspection {
  return {
    verdict: "PASS",
    coverage_state: "Submitted and indexed",
    robots_txt_state: "ALLOWED",
    indexing_state: "INDEXING_ALLOWED",
    page_fetch_state: "SUCCESSFUL",
    last_crawl_time: "2026-11-10T08:00:00Z",
    google_canonical: "https://mysite.com/a",
    user_canonical: "https://mysite.com/a",
    crawled_as: "MOBILE",
    sitemaps: ["https://mysite.com/sitemap.xml"],
    referring_urls: 2,
    inspection_link: "https://search.google.com/search-console/inspect?id=1",
    note: "Google reports this URL is indexed (Submitted and indexed).",
    ...over,
  };
}

export function target(over: Partial<Target> = {}): Target {
  return {
    id: "t1",
    url: "https://mysite.com/a",
    property: "sc-domain:mysite.com",
    display_status: "indexed",
    label: "Confirmed Indexed",
    evidence_source: "Google URL Inspection API",
    last_inspected_at: "2026-11-10T09:30:00Z",
    next_check_at: "2026-11-13T09:30:00Z",
    state: "done",
    last_known_status: "indexed",
    error_code: null,
    error_message: null,
    started_at: "2026-11-09T09:30:00Z",
    inspection: inspection(),
    ...over,
  };
}

export const neverInspected = (): Target =>
  target({
    id: "t-new",
    url: "https://mysite.com/new",
    display_status: "unknown",
    label: "Unknown",
    last_inspected_at: null,
    next_check_at: "2026-11-11T09:30:00Z",
    state: "pending",
    last_known_status: null,
    inspection: null,
  });

export const notIndexed = (): Target =>
  target({
    id: "t-no",
    url: "https://mysite.com/excluded",
    display_status: "not_indexed",
    label: "Confirmed Not Indexed",
    last_known_status: "not_indexed",
    inspection: inspection({
      verdict: "NEUTRAL",
      coverage_state: "Crawled - currently not indexed",
      google_canonical: "https://mysite.com/other",
      user_canonical: "https://mysite.com/excluded",
      note: "Google reports this URL is not indexed (Crawled - currently not indexed).",
    }),
  });

export const failed = (): Target =>
  target({
    id: "t-fail",
    url: "https://mysite.com/failed",
    display_status: "failed",
    label: "Inspection Failed",
    last_known_status: "indexed",
    error_code: "permission_denied",
    error_message: "Google refused this inspection",
  });

export const properties = (): GoogleProperty[] => [
  { site_url: "sc-domain:mysite.com", type: "domain", permission: "siteOwner", verified: true, can_write: true, label: "mysite.com" },
  { site_url: "https://www.other.com/blog/", type: "url_prefix", permission: "siteFullUser", verified: true, can_write: true, label: "https://www.other.com/blog/" },
  { site_url: "https://pending.example/", type: "url_prefix", permission: "siteUnverifiedUser", verified: false, can_write: false, label: "https://pending.example/" },
];

export const history = (): HistoryEntry[] => [
  { id: "h1", inspected_at: "2026-11-09T09:30:00Z", outcome: "success", status: "not_indexed", label: "Confirmed Not Indexed", error_code: null, trigger: "initial", inspection: inspection({ verdict: "NEUTRAL", coverage_state: "Discovered - currently not indexed" }) },
  { id: "h2", inspected_at: "2026-11-10T09:30:00Z", outcome: "success", status: "indexed", label: "Confirmed Indexed", error_code: null, trigger: "scheduled", inspection: inspection() },
  { id: "h3", inspected_at: "2026-11-10T12:00:00Z", outcome: "failed", status: "indexed", label: "Inspection Failed", error_code: "quota_exhausted", trigger: "manual", inspection: null },
];

export const sitemaps = (can_write: boolean): SitemapList => ({
  can_write,
  sitemaps: [
    { path: "https://mysite.com/sitemap.xml", last_submitted: "2026-11-01T00:00:00Z", last_downloaded: "2026-11-05T00:00:00Z", is_pending: true, is_sitemaps_index: false, type: "sitemap", warnings: 2, errors: 1 },
  ],
});
