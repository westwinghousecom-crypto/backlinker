export type Verdict = "eligible" | "warning" | "blocked" | "unreachable";
export type LinkType = "follow" | "nofollow" | "ugc" | "sponsored";
export type ItemState = "pending" | "processing" | "done";

export interface Problem {
  code: string;
  severity: "error" | "warning" | "info";
  title: string;
  explanation: string;
  fix: string;
}

export interface UrlCheck {
  url: string;
  final_url: string | null;
  status: number | null;
  redirects: string[];
  robots_allowed: boolean | null;
  noindex: boolean;
  noindex_source: string | null;
  canonical: string | null;
  canonical_mismatch: boolean;
  backlink_found: boolean | null;
  backlink_rel: string[];
  backlink_type: LinkType | null;
  backlink_anchor: string | null;
  verdict: Verdict;
  issues: string[];
  problems: Problem[];
  /** Always "unknown": technical checks cannot prove Google indexing. */
  google_index_status: "unknown";
}

/** What the customer saw when they searched Google themselves. Self-reported: never verified, never changes a verdict. */
export type GoogleNote = "appears" | "not_found";

export interface CheckItem {
  id: string;
  position: number;
  url: string;
  state: ItemState;
  result: UrlCheck | null;
  manual_google?: GoogleNote | null;
  manual_google_at?: string | null;
}

export interface CheckSummary {
  total: number;
  checked: number;
  eligible: number;
  with_problems: number;
  blocked: number;
  warnings: number;
  unreachable: number;
  backlinks_found: number;
  backlinks_missing: number;
  done: boolean;
}

export interface CheckBatch {
  batch_id: string;
  target: string | null;
  created_at: string | null;
  summary: CheckSummary;
  items: CheckItem[];
}

export interface CheckBatchRow {
  batch_id: string;
  target: string | null;
  created_at: string | null;
  total: number;
  checked: number;
}

export interface CreateCheckBatchRequest {
  urls: string[];
  target?: string;
}

export interface CreateCheckBatchResponse {
  batch_id: string;
  total: number;
}

/** Whether the owner has opted in to a public, read-only report link for this batch. Private by default. */
export interface ReportSharingState {
  public_report: boolean;
  public_url: string | null;
}
