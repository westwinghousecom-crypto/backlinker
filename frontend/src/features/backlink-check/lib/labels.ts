import type { CheckItem, GoogleNote, UrlCheck, Verdict } from "../types";

export const VERDICT_LABEL: Record<Verdict | "pending", string> = {
  eligible: "Eligible",
  warning: "Needs attention",
  blocked: "Blocked",
  unreachable: "Unreachable",
  pending: "Checking…",
};

export const VERDICT_HELP: Record<Verdict, string> = {
  eligible:
    "No technical blockers found. This does not mean Google has indexed the page.",
  warning: "Google can probably index it, but something may reduce the value.",
  blocked: "Something stops Google from indexing this page.",
  unreachable: "We could not load the page at all.",
};

export const VERDICT_CLASS: Record<Verdict | "pending", string> = {
  eligible: "border-emerald-800 bg-emerald-950/60 text-emerald-300",
  warning: "border-amber-800 bg-amber-950/60 text-amber-300",
  blocked: "border-red-900 bg-red-950/60 text-red-300",
  unreachable: "border-slate-700 bg-slate-800/60 text-slate-300",
  pending: "border-slate-700 bg-slate-900 text-slate-400",
};

export function verdictOf(item: CheckItem): Verdict | "pending" {
  return item.result ? item.result.verdict : "pending";
}

export function googlebotLabel(r: UrlCheck): string {
  if (r.status === null) return "Unknown";
  if (r.robots_allowed === true) return "Allowed";
  if (r.robots_allowed === false) return "Blocked";
  return "Unknown";
}

/** A Google search the customer can run themselves. A page that shows up is evidence; a page that does not show up proves nothing. */
export function googleSiteSearchUrl(url: string): string {
  const bare = url.trim().replace(/^https?:\/\//i, "").replace(/#.*$/, "");
  return `https://www.google.com/search?q=${encodeURIComponent(`site:${bare}`)}`;
}

export const GOOGLE_NOTE_LABEL: Record<GoogleNote, string> = {
  appears: "It appeared in my Google search",
  not_found: "I did not find it in my Google search",
};

export function backlinkLabel(r: UrlCheck): string {
  if (r.backlink_found === null) return "—";
  if (!r.backlink_found) return "Not in HTML";
  return "Found";
}

export const LINK_TYPE_LABEL = {
  follow: "Follow",
  nofollow: "Nofollow",
  ugc: "UGC",
  sponsored: "Sponsored",
} as const;
