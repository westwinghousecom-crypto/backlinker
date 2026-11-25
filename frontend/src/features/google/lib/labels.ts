import { ApiError } from "@/lib/api";
import type { DisplayStatus } from "../types";

/** The only four statuses the dashboard ever shows. */
export const STATUS_LABEL: Record<DisplayStatus, string> = {
  indexed: "Confirmed Indexed",
  not_indexed: "Confirmed Not Indexed",
  unknown: "Unknown",
  failed: "Inspection Failed",
};

export const STATUS_CLASS: Record<DisplayStatus, string> = {
  indexed: "border-emerald-800 bg-emerald-950/60 text-emerald-300",
  not_indexed: "border-red-900 bg-red-950/60 text-red-300",
  unknown: "border-slate-700 bg-slate-800/60 text-slate-300",
  failed: "border-orange-800 bg-orange-950/60 text-orange-300",
};

export const STATUS_HELP: Record<DisplayStatus, string> = {
  indexed: "Google's URL Inspection reports this URL is on Google.",
  not_indexed: "Google's URL Inspection reports this URL is not on Google.",
  unknown: "Google has not confirmed either way yet.",
  failed: "The last inspection could not be completed. See the details for why.",
};

export const EVIDENCE_NOTE =
  "Only Google's own URL Inspection can confirm indexing. HTTP checks, IndexNow, WebSub, sitemaps and social shares never do.";

export const QUOTA_MESSAGE =
  "Google's daily inspection limit for this property was reached; checks resume automatically.";

export const SKIPPED_REASON: Record<string, string> = {
  outside_property: "Not on your Search Console property, so Google cannot report on it",
  duplicate: "Already being tracked",
  invalid_url: "Not a valid http(s) address",
  too_long: "Address is too long",
  limit_reached: "Tracking limit reached",
};

/** Shown whenever some URLs were skipped because Google can only report on properties the customer owns. */
export const OUTSIDE_PROPERTY_NOTE =
  "Google only reports on sites you have verified in Search Console. Pages on other sites, and social media posts, cannot be checked this way. Use Check my backlinks to see whether they are reachable, crawlable and contain your link.";

export function skippedReason(reason: string): string {
  return SKIPPED_REASON[reason] ?? reason.replace(/_/g, " ");
}

export const CALLBACK_MESSAGES: Record<string, { tone: "success" | "error"; text: string }> = {
  connected: { tone: "success", text: "Google Search Console is connected." },
  access_denied: {
    tone: "error",
    text: "You did not grant access, so nothing was connected. You can try again whenever you like.",
  },
  scope_missing: {
    tone: "error",
    text: "Search Console permission was not granted. Tick the Search Console box on Google's screen and try again.",
  },
  invalid_state: {
    tone: "error",
    text: "That sign-in link was invalid or had expired. Please start the connection again.",
  },
  exchange_failed: {
    tone: "error",
    text: "Google did not complete the connection. Please try again in a moment.",
  },
  not_configured: {
    tone: "error",
    text: "Google integration is not set up on this server yet.",
  },
};

export function formatTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export type ErrorKind = "reauth" | "property" | "quota" | "write" | "other";

/** Map an API error to something the UI can act on. */
export function classifyError(e: unknown): { kind: ErrorKind; message: string } {
  const message = e instanceof Error ? e.message : "Something went wrong. Please try again.";
  if (e instanceof ApiError) {
    if (e.code === "google_reauth_required") return { kind: "reauth", message };
    if (e.code === "property_not_selected") return { kind: "property", message };
    if (e.code === "quota_exhausted") return { kind: "quota", message: QUOTA_MESSAGE };
    if (e.code === "write_permission_required") return { kind: "write", message };
  }
  return { kind: "other", message };
}
