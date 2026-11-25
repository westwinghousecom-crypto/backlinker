"use client";

import { useMemo, useState } from "react";
import { Download, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { deleteCheckBatch, markGoogleSearch, recheckUrl } from "../api/check-api";
import { downloadCsv } from "../lib/csv";
import {
  applyFilters,
  DEFAULT_FILTERS,
  hasActiveFilters,
  sortItems,
  type Filters,
  type Sort,
  type SortKey,
} from "../lib/filters";
import type { CheckBatch, GoogleNote } from "../types";
import { GoogleReview } from "./google-review";
import { PublicReportToggle } from "./public-report-toggle";
import { ResultRow, ResultsHeader } from "./result-row";
import { SummaryCards } from "./summary-cards";

const selectClass =
  "h-8 rounded-lg border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 outline-none focus-visible:border-emerald-500 focus-visible:ring-3 focus-visible:ring-emerald-500/30";

export function ResultsView({
  batch,
  onChanged,
  onDeleted,
}: {
  batch: CheckBatch;
  onChanged: () => void;
  onDeleted?: () => void;
}) {
  const [filters, setFilters] = useState<Filters>(DEFAULT_FILTERS);
  const [sort, setSort] = useState<Sort>({ key: "position", dir: "asc" });
  const [rechecking, setRechecking] = useState<Set<string>>(new Set());
  const [marking, setMarking] = useState<Set<string>>(new Set());
  const [actionError, setActionError] = useState<string | null>(null);

  const visible = useMemo(
    () => sortItems(applyFilters(batch.items, filters), sort),
    [batch.items, filters, sort],
  );
  const hasTarget = Boolean(batch.target);

  async function recheck(item: { id: string }) {
    setActionError(null);
    setRechecking((s) => new Set(s).add(item.id));
    try {
      await recheckUrl(batch.batch_id, item.id);
      onChanged();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Could not queue the recheck.");
    } finally {
      setRechecking((s) => {
        const next = new Set(s);
        next.delete(item.id);
        return next;
      });
    }
  }

  async function mark(item: { id: string }, result: GoogleNote | "clear") {
    setActionError(null);
    setMarking((s) => new Set(s).add(item.id));
    try {
      await markGoogleSearch(batch.batch_id, item.id, result);
      onChanged();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Could not save your note.");
      throw e;
    } finally {
      setMarking((s) => {
        const next = new Set(s);
        next.delete(item.id);
        return next;
      });
    }
  }

  async function remove() {
    if (!window.confirm("Delete this batch and all its results? This cannot be undone.")) return;
    setActionError(null);
    try {
      await deleteCheckBatch(batch.batch_id);
      onDeleted?.();
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "Could not delete the batch.");
    }
  }

  function set<K extends keyof Filters>(key: K, value: Filters[K]) {
    setFilters((f) => ({ ...f, [key]: value }));
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-lg font-semibold text-slate-100">Results</h2>
        <p className="text-sm text-slate-400">
          {hasTarget ? (
            <>
              Looking for links to{" "}
              <span className="font-mono text-slate-200">{batch.target}</span>
            </>
          ) : (
            "No website given, so links were not checked."
          )}
        </p>
      </div>

      <SummaryCards summary={batch.summary} hasTarget={hasTarget} />

      <div className="flex flex-wrap items-center gap-2" role="search" aria-label="Filter results">
        <input
          value={filters.search}
          onChange={(e) => set("search", e.target.value)}
          placeholder="Search URL or anchor text"
          aria-label="Search"
          className={`${selectClass} w-full sm:w-56`}
        />
        <select
          aria-label="Filter by result"
          className={selectClass}
          value={filters.verdict}
          onChange={(e) => set("verdict", e.target.value as Filters["verdict"])}
        >
          <option value="all">All results</option>
          <option value="eligible">Eligible</option>
          <option value="warning">Needs attention</option>
          <option value="blocked">Blocked</option>
          <option value="unreachable">Unreachable</option>
          <option value="pending">Still checking</option>
        </select>
        <select
          aria-label="Filter by backlink"
          className={selectClass}
          value={filters.backlink}
          onChange={(e) => set("backlink", e.target.value as Filters["backlink"])}
          disabled={!hasTarget}
          title={hasTarget ? undefined : "Add your website to check for your link"}
        >
          <option value="all">Any backlink</option>
          <option value="found">Link found</option>
          <option value="missing">Link missing</option>
        </select>
        <select
          aria-label="Filter by link type"
          className={selectClass}
          value={filters.linkType}
          onChange={(e) => set("linkType", e.target.value as Filters["linkType"])}
          disabled={!hasTarget}
        >
          <option value="all">Any link type</option>
          <option value="follow">Follow</option>
          <option value="nofollow">Nofollow</option>
          <option value="ugc">UGC</option>
          <option value="sponsored">Sponsored</option>
        </select>
        <select
          aria-label="Sort by"
          className={selectClass}
          value={`${sort.key}:${sort.dir}`}
          onChange={(e) => {
            const [key, dir] = e.target.value.split(":");
            setSort({ key: key as SortKey, dir: dir as Sort["dir"] });
          }}
        >
          <option value="position:asc">Original order</option>
          <option value="verdict:asc">Worst problems first</option>
          <option value="verdict:desc">Best first</option>
          <option value="status:desc">HTTP status (high to low)</option>
          <option value="url:asc">URL (A–Z)</option>
        </select>
        {hasActiveFilters(filters) && (
          <Button type="button" variant="ghost" size="sm" onClick={() => setFilters(DEFAULT_FILTERS)}>
            Clear filters
          </Button>
        )}
        <div className="flex items-center gap-1 sm:ml-auto">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => downloadCsv(visible, `backlink-check-${batch.batch_id.slice(0, 8)}.csv`)}
          disabled={visible.length === 0}
        >
          <Download /> Export CSV ({visible.length.toLocaleString()})
        </Button>
        {onDeleted && (
          <Button type="button" variant="ghost" size="sm" onClick={remove} className="text-red-400">
            <Trash2 /> Delete batch
          </Button>
        )}
        </div>
      </div>

      <PublicReportToggle batchId={batch.batch_id} />

      <GoogleReview items={visible} onMark={mark} />

      {actionError && (
        <p role="alert" className="text-sm text-red-400">
          {actionError}
        </p>
      )}

      {visible.length === 0 ? (
        <p className="rounded-lg border border-slate-800 bg-slate-900/40 p-6 text-center text-sm text-slate-400">
          No URLs match these filters.
        </p>
      ) : (
        <>
          <ResultsHeader />
          <ul className="space-y-2" aria-label="URL results">
            {visible.map((item) => (
              <ResultRow
                key={item.id}
                item={item}
                onRecheck={recheck}
                rechecking={rechecking.has(item.id)}
                onMark={mark}
                marking={marking.has(item.id)}
              />
            ))}
          </ul>
          <p className="text-xs text-slate-500">
            Showing {visible.length.toLocaleString()} of {batch.items.length.toLocaleString()} URLs.
          </p>
        </>
      )}
    </div>
  );
}
