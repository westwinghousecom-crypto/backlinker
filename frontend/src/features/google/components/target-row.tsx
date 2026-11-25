"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, ExternalLink, RefreshCw, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useHistory } from "../hooks/use-history";
import { formatTime, STATUS_LABEL } from "../lib/labels";
import type { Target } from "../types";
import { HistoryTimeline } from "./history-timeline";
import { StatusBadge } from "./status-badge";

export const ROW_GRID =
  "md:grid-cols-[minmax(0,2.4fr)_9.5rem_minmax(0,1.3fr)_minmax(0,1.3fr)_auto]";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="break-words text-sm text-slate-200">{children}</dd>
    </div>
  );
}

const norm = (u: string | null) => (u ?? "").replace(/#.*$/, "").replace(/\/$/, "");

export function TargetRow({
  target,
  onRecheck,
  onRemove,
  working,
}: {
  target: Target;
  onRecheck: (t: Target) => void;
  onRemove: (t: Target) => void;
  working: boolean;
}) {
  const [open, setOpen] = useState(false);
  const { items, error } = useHistory(target.id, open, target.last_inspected_at);
  const insp = target.inspection;
  const inFlight = target.state === "pending" || target.state === "processing";
  const canonicalMismatch = Boolean(
    insp?.google_canonical && insp.user_canonical && norm(insp.google_canonical) !== norm(insp.user_canonical),
  );

  return (
    <li className="rounded-lg border border-slate-800 bg-slate-900/50">
      <div className={`grid gap-2 p-3 md:items-center md:gap-3 ${ROW_GRID}`}>
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="flex min-w-0 items-start gap-1 text-left"
        >
          {open ? (
            <ChevronDown className="mt-0.5 size-4 shrink-0 text-slate-400" />
          ) : (
            <ChevronRight className="mt-0.5 size-4 shrink-0 text-slate-400" />
          )}
          <span className="block min-w-0 truncate font-mono text-sm text-slate-100" title={target.url}>
            {target.url}
          </span>
        </button>

        <div className="flex flex-wrap items-center gap-2 md:contents">
          <span>
            <StatusBadge status={target.display_status} />
            {inFlight && <span className="ml-2 text-xs text-slate-500">checking…</span>}
          </span>
          <span className="text-xs text-slate-400" title="Where this status comes from">
            <span className="text-slate-500 md:hidden">Source </span>
            {target.evidence_source}
          </span>
          <span className="text-xs text-slate-400">
            <span className="block">
              {target.last_inspected_at ? (
                <>Last inspected {formatTime(target.last_inspected_at)}</>
              ) : (
                "Not inspected yet"
              )}
            </span>
            {target.next_check_at && <span className="block text-slate-500">Next check {formatTime(target.next_check_at)}</span>}
          </span>
        </div>

        <div className="flex items-center gap-1 justify-self-end">
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            disabled={inFlight || working}
            onClick={() => onRecheck(target)}
            aria-label={`Recheck ${target.url}`}
            title="Recheck with Google now"
          >
            <RefreshCw className={inFlight ? "animate-spin" : ""} />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon-sm"
            disabled={working}
            onClick={() => onRemove(target)}
            aria-label={`Remove ${target.url}`}
            title="Stop tracking this URL"
          >
            <Trash2 />
          </Button>
        </div>
      </div>

      {open && (
        <div className="space-y-4 border-t border-slate-800 p-3">
          {target.display_status === "failed" && (
            <div role="note" className="rounded-md border border-orange-900/70 bg-orange-950/30 p-2 text-sm">
              <p className="font-medium text-orange-200">
                Inspection failed{target.error_message ? `: ${target.error_message}` : target.error_code ? `: ${target.error_code.replace(/_/g, " ")}` : ""}
              </p>
              <p className="text-slate-300">
                Last known status:{" "}
                <strong>
                  {target.last_known_status ? STATUS_LABEL[target.last_known_status] : "Unknown"}
                </strong>
              </p>
            </div>
          )}

          {insp ? (
            <>
              {insp.note && <p className="text-sm text-slate-300">{insp.note}</p>}
              <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <Field label="Google verdict">{insp.verdict ?? "—"}</Field>
                <Field label="Coverage state">{insp.coverage_state ?? "—"}</Field>
                <Field label="Last crawl by Google">{formatTime(insp.last_crawl_time)}</Field>
                <Field label="robots.txt">{insp.robots_txt_state ?? "—"}</Field>
                <Field label="Indexing allowed?">{insp.indexing_state ?? "—"}</Field>
                <Field label="Page fetch">{insp.page_fetch_state ?? "—"}</Field>
                <Field label="Google-selected canonical">
                  {insp.google_canonical ?? "—"}
                  {canonicalMismatch && <span className="text-amber-400"> (differs from your declared canonical)</span>}
                </Field>
                <Field label="Your declared canonical">{insp.user_canonical ?? "—"}</Field>
                <Field label="Found via sitemaps">
                  {insp.sitemaps.length ? insp.sitemaps.join(", ") : "None reported"}
                </Field>
              </dl>
              {insp.inspection_link && (
                <a
                  href={insp.inspection_link}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 text-sm text-emerald-400 underline underline-offset-2"
                >
                  View in Search Console <ExternalLink className="size-3.5" />
                </a>
              )}
            </>
          ) : (
            <p className="text-sm text-slate-400">
              {inFlight ? "Waiting for Google's answer…" : "Google has not inspected this URL yet."}
            </p>
          )}

          <div>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">History</h3>
            <HistoryTimeline items={items} error={error} />
          </div>
        </div>
      )}
    </li>
  );
}
