"use client";

import { useCheckHistory } from "../hooks/use-check-history";

export function HistoryList({
  activeId,
  reloadKey,
  onSelect,
}: {
  activeId: string | null;
  /** Changes when the list should be refetched (e.g. a batch finished). */
  reloadKey: string;
  onSelect: (batchId: string) => void;
}) {
  const { rows, error } = useCheckHistory(reloadKey);

  return (
    <section aria-label="Batch history" className="space-y-2">
      <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-400">
        Recent batches
      </h2>
      {error && <p className="text-sm text-amber-400">{error}</p>}
      {rows === null && !error && <p className="text-sm text-slate-500">Loading…</p>}
      {rows?.length === 0 && (
        <p className="text-sm text-slate-500">Nothing yet. Your checks will appear here.</p>
      )}
      <ul className="space-y-1">
        {rows?.map((b) => {
          const active = b.batch_id === activeId;
          const date = b.created_at ? new Date(b.created_at).toLocaleString() : "";
          return (
            <li key={b.batch_id}>
              <button
                type="button"
                onClick={() => onSelect(b.batch_id)}
                aria-current={active ? "true" : undefined}
                className={`w-full rounded-lg border px-3 py-2 text-left text-sm transition-colors ${
                  active
                    ? "border-emerald-700 bg-emerald-950/40"
                    : "border-slate-800 bg-slate-900/40 hover:bg-slate-900"
                }`}
              >
                <span className="block truncate text-slate-100">
                  {b.target ? b.target.replace(/^https?:\/\//, "") : "No website given"}
                </span>
                <span className="block text-xs text-slate-400">
                  {b.checked.toLocaleString()}/{b.total.toLocaleString()} checked
                  {date ? ` · ${date}` : ""}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
