import type { CheckSummary } from "../types";

function Stat({
  label,
  value,
  tone = "text-slate-100",
  hint,
}: {
  label: string;
  value: string;
  tone?: string;
  hint?: string;
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-3" title={hint}>
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums ${tone}`}>{value}</div>
    </div>
  );
}

export function SummaryCards({
  summary,
  hasTarget,
}: {
  summary: CheckSummary;
  hasTarget: boolean;
}) {
  const pct = summary.total ? Math.round((summary.checked / summary.total) * 100) : 0;
  const n = (v: number) => v.toLocaleString();
  return (
    <section aria-label="Summary" className="space-y-3">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Total URLs" value={n(summary.total)} />
        <Stat label="Checked" value={n(summary.checked)} hint="URLs we have finished checking" />
        <Stat
          label="Eligible"
          value={n(summary.eligible)}
          tone="text-emerald-400"
          hint="No technical blockers found. Not proof of indexing."
        />
        <Stat
          label="With problems"
          value={n(summary.with_problems)}
          tone={summary.with_problems ? "text-amber-400" : "text-slate-100"}
        />
        <Stat
          label="Backlinks found"
          value={hasTarget ? n(summary.backlinks_found) : "—"}
          tone="text-emerald-400"
          hint={hasTarget ? undefined : "Add your website to check for your link"}
        />
        <Stat
          label="Backlinks missing"
          value={hasTarget ? n(summary.backlinks_missing) : "—"}
          tone={hasTarget && summary.backlinks_missing ? "text-red-400" : "text-slate-100"}
          hint={hasTarget ? undefined : "Add your website to check for your link"}
        />
      </div>
      <div
        className="h-2 overflow-hidden rounded-full bg-slate-800"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={pct}
        aria-label="Checking progress"
      >
        <div
          className="h-full bg-emerald-500 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <p className="text-xs text-slate-400">
        {summary.done
          ? "All URLs checked."
          : `Checking… ${n(summary.checked)} of ${n(summary.total)} done.`}{" "}
        Google index status is <strong className="text-slate-200">Unknown</strong>{" "}
        for every page: technical checks cannot prove a page is indexed.
      </p>
    </section>
  );
}
