"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { AlertCircle } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { parseUrls } from "@/features/submission/lib/parse-urls";
import { addTargets, recheckTarget, removeTarget } from "../api/google-api";
import { useTargets } from "../hooks/use-targets";
import { classifyError, EVIDENCE_NOTE, OUTSIDE_PROPERTY_NOTE, QUOTA_MESSAGE, skippedReason, STATUS_LABEL } from "../lib/labels";
import type { AddTargetsResult, DisplayStatus, GoogleQuota } from "../types";
import { QuotaMeter } from "./quota-meter";
import { ROW_GRID, TargetRow } from "./target-row";

const MAX_URLS = 200;
const ORDER: DisplayStatus[] = ["indexed", "not_indexed", "unknown", "failed"];

/** The Google Index Status section: add your own URLs, see what Google's URL Inspection says about each. */
export function TargetsPanel({
  property,
  quota,
  onReauth,
  onNeedProperty,
}: {
  property: string;
  quota: GoogleQuota | null;
  onReauth: () => void;
  onNeedProperty: () => void;
}) {
  const { items, error: loadError, refresh } = useTargets(property);
  const [raw, setRaw] = useState("");
  const [busy, setBusy] = useState(false);
  const [working, setWorking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [quotaHit, setQuotaHit] = useState(false);
  const [result, setResult] = useState<AddTargetsResult | null>(null);

  const urls = useMemo(() => parseUrls(raw), [raw]);
  const tooMany = urls.length > MAX_URLS;

  const counts = useMemo(() => {
    const c: Record<DisplayStatus, number> = { indexed: 0, not_indexed: 0, unknown: 0, failed: 0 };
    for (const t of items ?? []) c[t.display_status] += 1;
    return c;
  }, [items]);

  function handleError(e: unknown) {
    const c = classifyError(e);
    if (c.kind === "reauth") onReauth();
    if (c.kind === "property") onNeedProperty();
    if (c.kind === "quota") setQuotaHit(true);
    setError(c.message);
  }

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!urls.length || tooMany) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await addTargets(urls);
      setResult(res);
      if (res.added > 0) setRaw("");
      refresh();
    } catch (err) {
      handleError(err);
    } finally {
      setBusy(false);
    }
  }

  async function act(fn: () => Promise<unknown>) {
    setWorking(true);
    setError(null);
    try {
      await fn();
      refresh();
    } catch (err) {
      handleError(err);
    } finally {
      setWorking(false);
    }
  }

  const exhausted = quotaHit || (quota ? quota.used_today >= quota.per_day_limit : false);

  return (
    <section aria-label="Google Index Status" className="space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-slate-100">Google Index Status</h2>
        <p className="text-sm text-slate-400">
          Add pages on <span className="font-mono text-slate-200">{property.replace(/^sc-domain:/, "")}</span>. We ask
          Google about each one now, then again after 1, 3, 7 and 14 days.
        </p>
        <p className="mt-1 rounded-md border border-slate-800 bg-slate-900/60 p-2 text-xs text-slate-300">
          {EVIDENCE_NOTE}
        </p>
      </div>

      {quota && <QuotaMeter quota={quota} />}
      {exhausted && !quota && <p className="text-sm text-amber-300">{QUOTA_MESSAGE}</p>}

      <form onSubmit={add} className="space-y-2">
        <label htmlFor="gsc-urls" className="block text-sm text-slate-300">
          Your pages to check (one URL per line, up to {MAX_URLS})
        </label>
        <Textarea
          id="gsc-urls"
          value={raw}
          onChange={(e) => setRaw(e.target.value)}
          rows={4}
          spellCheck={false}
          placeholder={"https://your-site.com/page-1\nhttps://your-site.com/blog/post"}
          className="border-slate-700 bg-slate-950 font-mono text-sm text-slate-100 placeholder:text-slate-600 focus-visible:border-emerald-500 focus-visible:ring-emerald-500/30"
        />
        <div className="flex flex-wrap items-center gap-3">
          <Button
            type="submit"
            disabled={busy || urls.length === 0 || tooMany}
            className="bg-emerald-500 font-semibold text-slate-950 hover:bg-emerald-400"
          >
            {busy ? "Adding…" : "Check with Google"}
          </Button>
          <span className={`text-sm ${tooMany ? "text-amber-400" : "text-slate-400"}`}>
            {tooMany
              ? `${urls.length.toLocaleString()} URLs is over the limit of ${MAX_URLS}.`
              : `${urls.length.toLocaleString()} URL${urls.length === 1 ? "" : "s"} detected`}
          </span>
        </div>
      </form>

      {result && (
        <div role="status" className="rounded-md border border-slate-800 bg-slate-900/60 p-3 text-sm">
          <p className="text-slate-200">
            Added {result.added.toLocaleString()} URL{result.added === 1 ? "" : "s"}.
            {result.skipped.length > 0 && ` Skipped ${result.skipped.length.toLocaleString()}:`}
          </p>
          {result.skipped.length > 0 && (
            <ul aria-label="Skipped URLs" className="mt-1 space-y-1">
              {result.skipped.map((s) => (
                <li key={s.url} className="text-xs text-amber-300">
                  <span className="break-all font-mono">{s.url}</span>: {skippedReason(s.reason)}
                </li>
              ))}
            </ul>
          )}
          {result.skipped.some((s) => s.reason === "outside_property") && (
            <p className="mt-2 text-xs text-slate-400">
              {OUTSIDE_PROPERTY_NOTE}{" "}
              <Link href="/dashboard/backlinks" className="underline underline-offset-2">
                Check my backlinks
              </Link>
            </p>
          )}
        </div>
      )}

      {(error || loadError) && (
        <Alert variant="destructive" className="border-red-900 bg-red-950/50">
          <AlertCircle />
          <AlertDescription>{error ?? loadError}</AlertDescription>
        </Alert>
      )}

      <div role="group" aria-label="Status summary" className="grid grid-cols-2 gap-2 md:grid-cols-4">
        {ORDER.map((s) => (
          <div key={s} className="rounded-lg border border-slate-800 bg-slate-900/60 p-3">
            <div className="text-xs uppercase tracking-wide text-slate-400">{STATUS_LABEL[s]}</div>
            <div className="mt-1 text-2xl font-semibold tabular-nums text-slate-100" data-testid={`count-${s}`}>
              {counts[s].toLocaleString()}
            </div>
          </div>
        ))}
      </div>

      {items === null && !loadError && <p className="text-sm text-slate-500">Loading your URLs…</p>}
      {items?.length === 0 && (
        <p className="rounded-lg border border-slate-800 bg-slate-900/40 p-6 text-center text-sm text-slate-400">
          No URLs yet. Add pages above to ask Google about them.
        </p>
      )}
      {items && items.length > 0 && (
        <>
          <div
            aria-hidden
            className={`hidden gap-3 px-3 text-xs uppercase tracking-wide text-slate-500 md:grid ${ROW_GRID}`}
          >
            <span className="pl-5">URL</span>
            <span>Google status</span>
            <span>Evidence</span>
            <span>Inspected</span>
            <span className="w-16" />
          </div>
          <ul aria-label="Tracked URLs" className="space-y-2">
            {items.map((t) => (
              <TargetRow
                key={t.id}
                target={t}
                working={working}
                onRecheck={(x) => act(() => recheckTarget(x.id))}
                onRemove={(x) => {
                  if (window.confirm(`Stop tracking ${x.url}? Its history will be deleted.`)) {
                    void act(() => removeTarget(x.id));
                  }
                }}
              />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
