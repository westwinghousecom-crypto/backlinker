export type IndexStatus = "indexed" | "not_indexed" | "unknown";
export type DisplayStatus = IndexStatus | "failed";

export interface GoogleQuota {
  property: string;
  per_day_limit: number;
  used_today: number;
  per_minute_limit: number;
}

export interface GoogleStatus {
  configured: boolean;
  connected: boolean;
  state: "active" | "revoked" | null;
  email: string | null;
  can_write: boolean;
  reauth_required: boolean;
  selected_property: string | null;
  quota: GoogleQuota | null;
}

export interface GoogleProperty {
  site_url: string;
  type: "domain" | "url_prefix";
  permission: string;
  verified: boolean;
  can_write: boolean;
  label: string;
}

export interface Inspection {
  verdict: string | null;
  coverage_state: string | null;
  robots_txt_state: string | null;
  indexing_state: string | null;
  page_fetch_state: string | null;
  last_crawl_time: string | null;
  google_canonical: string | null;
  user_canonical: string | null;
  crawled_as: string | null;
  sitemaps: string[];
  referring_urls: number;
  inspection_link: string | null;
  note: string | null;
}

export interface Target {
  id: string;
  url: string;
  property: string;
  display_status: DisplayStatus;
  label: string;
  evidence_source: string;
  last_inspected_at: string | null;
  next_check_at: string | null;
  state: "pending" | "processing" | "done" | "paused";
  last_known_status: IndexStatus | null;
  error_code: string | null;
  error_message: string | null;
  started_at: string;
  inspection: Inspection | null;
}

export interface HistoryEntry {
  id: string;
  inspected_at: string;
  outcome: "success" | "failed";
  status: IndexStatus;
  label: string;
  error_code: string | null;
  trigger: "initial" | "scheduled" | "manual";
  inspection: Inspection | null;
}

export interface SkippedUrl {
  url: string;
  reason: string;
}

export interface AddTargetsResult {
  added: number;
  skipped: SkippedUrl[];
}

export interface SitemapEntry {
  path: string;
  last_submitted: string | null;
  last_downloaded: string | null;
  is_pending: boolean;
  is_sitemaps_index: boolean;
  type: string | null;
  warnings: number;
  errors: number;
}

export interface SitemapList {
  sitemaps: SitemapEntry[];
  can_write: boolean;
}
