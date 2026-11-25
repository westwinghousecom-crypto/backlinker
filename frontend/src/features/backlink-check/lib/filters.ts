import type { CheckItem, LinkType, Verdict } from "../types";
import { verdictOf } from "./labels";

export interface Filters {
  verdict: "all" | Verdict | "pending";
  backlink: "all" | "found" | "missing";
  linkType: "all" | LinkType;
  search: string;
}

export const DEFAULT_FILTERS: Filters = {
  verdict: "all",
  backlink: "all",
  linkType: "all",
  search: "",
};

export type SortKey = "position" | "verdict" | "status" | "url";
export interface Sort {
  key: SortKey;
  dir: "asc" | "desc";
}

const VERDICT_RANK: Record<Verdict | "pending", number> = {
  blocked: 0,
  unreachable: 1,
  warning: 2,
  eligible: 3,
  pending: 4,
};

export function applyFilters(items: CheckItem[], f: Filters): CheckItem[] {
  const q = f.search.trim().toLowerCase();
  return items.filter((item) => {
    if (f.verdict !== "all" && verdictOf(item) !== f.verdict) return false;
    const r = item.result;
    if (f.backlink !== "all") {
      if (!r || r.backlink_found === null) return false;
      if (f.backlink === "found" && !r.backlink_found) return false;
      if (f.backlink === "missing" && r.backlink_found) return false;
    }
    if (f.linkType !== "all" && r?.backlink_type !== f.linkType) return false;
    if (q) {
      const hay = [item.url, r?.final_url, r?.backlink_anchor]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

export function sortItems(items: CheckItem[], s: Sort): CheckItem[] {
  const sign = s.dir === "asc" ? 1 : -1;
  const value = (i: CheckItem): number | string => {
    switch (s.key) {
      case "verdict":
        return VERDICT_RANK[verdictOf(i)];
      case "status":
        return i.result?.status ?? 9999; // unchecked/unreachable last when ascending
      case "url":
        return i.url.toLowerCase();
      default:
        return i.position;
    }
  };
  return [...items].sort((a, b) => {
    const va = value(a);
    const vb = value(b);
    const cmp = va < vb ? -1 : va > vb ? 1 : a.position - b.position;
    return cmp * sign;
  });
}

export function hasActiveFilters(f: Filters): boolean {
  return (
    f.verdict !== "all" ||
    f.backlink !== "all" ||
    f.linkType !== "all" ||
    f.search.trim() !== ""
  );
}
