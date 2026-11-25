import type { CheckItem } from "../types";
import { backlinkLabel, googlebotLabel, VERDICT_LABEL, verdictOf } from "./labels";

const HEADERS = [
  "url",
  "result",
  "http_status",
  "final_url",
  "googlebot_can_crawl",
  "noindex",
  "canonical_url",
  "canonical_mismatch",
  "backlink",
  "link_type",
  "anchor_text",
  "google_index_status",
  "google_search_self_reported",
  "problems",
  "suggested_fixes",
] as const;

/** Quote a CSV cell. Cells starting with = + - @ are prefixed so spreadsheets never run them as formulas. */
export function csvCell(value: string | number | boolean | null | undefined): string {
  let s = value === null || value === undefined ? "" : String(value);
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCsv(items: CheckItem[]): string {
  const lines = [HEADERS.join(",")];
  for (const item of items) {
    const r = item.result;
    const row = r
      ? [
          item.url,
          VERDICT_LABEL[verdictOf(item)],
          r.status,
          r.final_url,
          googlebotLabel(r),
          r.noindex ? `yes (${r.noindex_source ?? "unknown"})` : "no",
          r.canonical,
          r.canonical_mismatch ? "yes" : "no",
          backlinkLabel(r),
          r.backlink_type,
          r.backlink_anchor,
          "Unknown",
          item.manual_google === "appears" ? "Appeared (self-reported)" : item.manual_google === "not_found" ? "Not found (self-reported)" : "",
          r.problems
            .filter((p) => p.severity !== "info")
            .map((p) => p.title)
            .join(" | "),
          r.problems
            .filter((p) => p.severity !== "info")
            .map((p) => p.fix)
            .join(" | "),
        ]
      : [item.url, "Not checked yet", ...Array(HEADERS.length - 2).fill("")];
    lines.push(row.map(csvCell).join(","));
  }
  return lines.join("\r\n");
}

export function downloadCsv(items: CheckItem[], filename: string): void {
  const blob = new Blob(["﻿" + toCsv(items)], {
    type: "text/csv;charset=utf-8",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
