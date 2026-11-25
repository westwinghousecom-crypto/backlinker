import { describe, expect, it } from "vitest";
import { sampleItems } from "../test-data";
import { csvCell, toCsv } from "./csv";
import { applyFilters, DEFAULT_FILTERS, sortItems } from "./filters";
import { backlinkLabel, googlebotLabel, verdictOf } from "./labels";

describe("filters", () => {
  const items = sampleItems();

  it("filters by verdict, including unchecked URLs", () => {
    const ids = (v: string) =>
      applyFilters(items, { ...DEFAULT_FILTERS, verdict: v as never }).map((i) => i.position);
    expect(ids("eligible")).toEqual([0]);
    expect(ids("blocked")).toEqual([1]);
    expect(ids("unreachable")).toEqual([3]);
    expect(ids("pending")).toEqual([4]);
  });

  it("filters by backlink presence and link type", () => {
    const f = (over: object) => applyFilters(items, { ...DEFAULT_FILTERS, ...over }).map((i) => i.position);
    expect(f({ backlink: "found" })).toEqual([0, 2]);
    expect(f({ backlink: "missing" })).toEqual([1]);
    expect(f({ linkType: "nofollow" })).toEqual([2]);
    expect(f({ linkType: "follow" })).toEqual([0]);
  });

  it("searches URL and anchor text, case-insensitively", () => {
    const f = (search: string) => applyFilters(items, { ...DEFAULT_FILTERS, search }).map((i) => i.position);
    expect(f("NOINDEX.example")).toEqual([1]);
    expect(f("best tool")).toEqual([0]);
    expect(f("nothing matches")).toEqual([]);
  });

  it("sorts worst problems first and keeps ties in original order", () => {
    const order = sortItems(items, { key: "verdict", dir: "asc" }).map((i) => i.position);
    expect(order).toEqual([1, 3, 2, 0, 4]);
    expect(sortItems(items, { key: "url", dir: "asc" }).map((i) => i.position)[0]).toBe(3);
    expect(sortItems(items, { key: "position", dir: "desc" }).map((i) => i.position)).toEqual([4, 3, 2, 1, 0]);
  });
});

describe("labels", () => {
  const [good, , , down, later] = sampleItems();
  it("describes crawl and backlink state without overclaiming", () => {
    expect(googlebotLabel(good.result!)).toBe("Allowed");
    expect(googlebotLabel(down.result!)).toBe("Unknown");
    expect(backlinkLabel(good.result!)).toBe("Found");
    expect(backlinkLabel(down.result!)).toBe("—");
    expect(verdictOf(later)).toBe("pending");
  });
});

describe("csv", () => {
  it("quotes cells and neutralizes spreadsheet formulas", () => {
    expect(csvCell('say "hi", ok')).toBe('"say ""hi"", ok"');
    expect(csvCell("=HYPERLINK(1)")).toBe("'=HYPERLINK(1)");
    expect(csvCell("+1")).toBe("'+1");
    expect(csvCell("@x")).toBe("'@x");
    expect(csvCell(null)).toBe("");
    expect(csvCell(404)).toBe("404");
  });

  it("exports one row per URL with problems, fixes and Unknown index status", () => {
    const lines = toCsv(sampleItems()).split("\r\n");
    expect(lines).toHaveLength(6);
    expect(lines[0]).toContain("google_index_status");
    expect(lines[2]).toContain("noindex.example");
    expect(lines[2]).toContain("Page is marked noindex");
    expect(lines[2]).toContain("Fix: Page is marked noindex");
    expect(lines[3]).toContain("'=cmd"); // anchor text from a hostile page is neutralized
    expect(lines[5]).toContain("Not checked yet");
    // no row ever claims Google indexed the page
    expect(toCsv(sampleItems()).toLowerCase()).not.toMatch(/\bindexed\b/);
  });
});

describe("csv self-reported Google note", () => {
  it("exports the customer's own Google note in its own column, apart from the index status", () => {
    const items = sampleItems();
    items[0] = { ...items[0], manual_google: "appears" };
    items[1] = { ...items[1], manual_google: "not_found" };
    const lines = toCsv(items).split("\r\n");
    expect(lines[0]).toContain("google_search_self_reported");
    expect(lines[1]).toContain("Appeared (self-reported)");
    expect(lines[2]).toContain("Not found (self-reported)");
    expect(lines[3]).not.toContain("self-reported");
    expect(toCsv(items).toLowerCase()).not.toMatch(/\bindexed\b/);
  });
});
