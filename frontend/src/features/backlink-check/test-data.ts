/** Builders for API-shaped test data (the same JSON shape the FastAPI backend returns). Tests only. */
import type { CheckBatch, CheckItem, Problem, UrlCheck } from "./types";

export function problem(code: string, severity: Problem["severity"], title: string): Problem {
  return { code, severity, title, explanation: `Why: ${title}`, fix: `Fix: ${title}` };
}

export function result(over: Partial<UrlCheck> = {}): UrlCheck {
  return {
    url: "https://blog.example/post",
    final_url: "https://blog.example/post",
    status: 200,
    redirects: [],
    robots_allowed: true,
    noindex: false,
    noindex_source: null,
    canonical: "https://blog.example/post",
    canonical_mismatch: false,
    backlink_found: true,
    backlink_rel: [],
    backlink_type: "follow",
    backlink_anchor: "best tool",
    verdict: "eligible",
    issues: [],
    problems: [],
    google_index_status: "unknown",
    ...over,
  };
}

export function item(position: number, url: string, res: UrlCheck | null): CheckItem {
  return {
    id: `id-${position}`,
    position,
    url,
    state: res ? "done" : "pending",
    result: res ? { ...res, url } : null,
  };
}

export function sampleItems(): CheckItem[] {
  return [
    item(0, "https://good.example/a", result()),
    item(
      1,
      "https://noindex.example/b",
      result({
        verdict: "blocked",
        noindex: true,
        noindex_source: "meta robots tag",
        backlink_found: false,
        backlink_type: null,
        backlink_anchor: null,
        problems: [problem("noindex", "error", "Page is marked noindex (meta robots tag)")],
        issues: ["Page is marked noindex (meta robots tag)"],
      }),
    ),
    item(
      2,
      "https://nofollow.example/c",
      result({
        verdict: "warning",
        backlink_type: "nofollow",
        backlink_rel: ["nofollow"],
        backlink_anchor: "=cmd|' /C calc'!A0",
        problems: [problem("link_qualified", "warning", "Link is marked nofollow")],
        issues: ["Link is marked nofollow"],
      }),
    ),
    item(
      3,
      "https://down.example/d",
      result({
        verdict: "unreachable",
        status: null,
        final_url: null,
        robots_allowed: null,
        backlink_found: null,
        backlink_type: null,
        backlink_anchor: null,
        problems: [problem("host_unreachable", "error", "The site could not be reached")],
        issues: ["The site could not be reached"],
      }),
    ),
    item(4, "https://later.example/e", null),
  ];
}

export function sampleBatch(over: Partial<CheckBatch> = {}): CheckBatch {
  const items = sampleItems();
  return {
    batch_id: "batch-1",
    target: "https://mysite.com",
    created_at: "2026-11-11T08:00:00Z",
    summary: {
      total: 5,
      checked: 4,
      eligible: 1,
      with_problems: 3,
      blocked: 1,
      warnings: 1,
      unreachable: 1,
      backlinks_found: 2,
      backlinks_missing: 1,
      done: false,
    },
    items,
    ...over,
  };
}
