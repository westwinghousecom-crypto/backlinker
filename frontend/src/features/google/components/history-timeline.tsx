import { StatusBadge } from "./status-badge";
import { formatTime, STATUS_LABEL } from "../lib/labels";
import type { HistoryEntry } from "../types";

const TRIGGER_LABEL = { initial: "First check", scheduled: "Scheduled recheck", manual: "Manual recheck" } as const;

/** Inspections of one URL, newest first, with a note wherever Google's answer changed. */
export function HistoryTimeline({ items, error }: { items: HistoryEntry[] | null; error: string | null }) {
  if (error) return <p className="text-sm text-amber-400">{error}</p>;
  if (items === null) return <p className="text-sm text-slate-500">Loading history…</p>;
  if (items.length === 0) return <p className="text-sm text-slate-500">No inspections yet.</p>;

  const sorted = [...items].sort((a, b) => b.inspected_at.localeCompare(a.inspected_at));
  // Compare each successful answer with the previous successful one (older entries come later in the list).
  const successes = sorted.filter((e) => e.outcome === "success");

  return (
    <ol aria-label="Inspection history" className="space-y-2 border-l border-slate-800 pl-4">
      {sorted.map((e) => {
        const idx = successes.indexOf(e);
        const previous = idx >= 0 ? successes[idx + 1] : undefined;
        const changed = previous && previous.status !== e.status;
        return (
          <li key={e.id} className="relative text-sm">
            <span className="absolute -left-[1.3rem] top-1.5 size-2 rounded-full bg-slate-600" aria-hidden />
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <time className="text-slate-300">{formatTime(e.inspected_at)}</time>
              <StatusBadge status={e.outcome === "failed" ? "failed" : e.status} />
              <span className="text-xs text-slate-500">{TRIGGER_LABEL[e.trigger]}</span>
            </div>
            {changed && previous && (
              <p className="text-xs text-amber-300">
                Changed from {STATUS_LABEL[previous.status]} to {STATUS_LABEL[e.status]}
              </p>
            )}
            {e.outcome === "failed" && e.error_code && (
              <p className="text-xs text-orange-300">Could not inspect: {e.error_code.replace(/_/g, " ")}</p>
            )}
            {e.inspection?.coverage_state && (
              <p className="text-xs text-slate-400">Google: {e.inspection.coverage_state}</p>
            )}
          </li>
        );
      })}
    </ol>
  );
}
