"use client";

import { useBatchStatus } from "../hooks/use-batch-status";
import { SharingControls } from "./sharing-controls";
import { TrackInGoogle } from "./track-in-google";

const COLORS: Record<string, string> = {
  pending: "text-slate-400",
  processing: "text-amber-400",
  submitted: "text-sky-400",
  completed: "text-emerald-400",
  failed: "text-red-400",
};

export function BatchStatusPanel({ batchId }: { batchId: string }) {
  const { status, error } = useBatchStatus(batchId);

  return (
    <div className="mt-3 rounded-md border border-slate-800 bg-slate-950/60 p-3 text-sm">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <span className="font-medium text-slate-200">Progress</span>
        {status &&
          Object.entries(status.counts).map(([k, v]) => (
            <span key={k} className={COLORS[k]}>
              {k}: {v}
            </span>
          ))}
        {status && (
          <span className="text-slate-500">
            {status.done ? "done" : "updating..."}
          </span>
        )}
      </div>
      {error && <p className="mt-1 text-amber-400">{error}</p>}
      {status && (
        <ul className="mt-2 max-h-40 space-y-1 overflow-y-auto font-mono text-xs">
          {status.urls.map((u) => (
            <li key={u.url} className="flex justify-between gap-3">
              <span className="truncate text-slate-300">{u.url}</span>
              <span className={COLORS[u.status]}>{u.status}</span>
            </li>
          ))}
        </ul>
      )}
      <SharingControls batchId={batchId} />
      {status && <TrackInGoogle urls={status.urls.map((u) => u.url)} />}
    </div>
  );
}
