import type { GoogleQuota } from "../types";
import { QUOTA_MESSAGE } from "../lib/labels";

/** Today's URL Inspection usage for the chosen property (Google limits each property to a daily and a per-minute total). */
export function QuotaMeter({ quota }: { quota: GoogleQuota }) {
  const pct = quota.per_day_limit ? Math.min(100, Math.round((quota.used_today / quota.per_day_limit) * 100)) : 0;
  const exhausted = quota.used_today >= quota.per_day_limit;
  const near = !exhausted && pct >= 80;
  const bar = exhausted ? "bg-red-500" : near ? "bg-amber-500" : "bg-emerald-500";
  return (
    <section aria-label="Inspection quota" className="space-y-1">
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
        <span className="text-slate-300">Google inspections today</span>
        <span className="tabular-nums text-slate-400">
          {quota.used_today.toLocaleString()} / {quota.per_day_limit.toLocaleString()} (max{" "}
          {quota.per_minute_limit.toLocaleString()} per minute)
        </span>
      </div>
      <div
        className="h-2 overflow-hidden rounded-full bg-slate-800"
        role="progressbar"
        aria-label="Daily inspection quota"
        aria-valuemin={0}
        aria-valuemax={quota.per_day_limit}
        aria-valuenow={quota.used_today}
      >
        <div className={`h-full transition-all ${bar}`} style={{ width: `${pct}%` }} />
      </div>
      {exhausted && <p className="text-xs text-red-300">{QUOTA_MESSAGE}</p>}
      {near && (
        <p className="text-xs text-amber-300">
          You have used {pct}% of today&apos;s Google limit for this property.
        </p>
      )}
    </section>
  );
}
