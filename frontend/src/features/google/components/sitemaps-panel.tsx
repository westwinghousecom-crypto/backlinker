"use client";

import { useEffect, useState } from "react";
import { AlertCircle, CheckCircle2 } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { beginConnect, listSitemaps, submitSitemap } from "../api/google-api";
import { classifyError, formatTime } from "../lib/labels";
import type { SitemapList } from "../types";

export function SitemapsPanel({ property, onReauth }: { property: string; onReauth: () => void }) {
  const [data, setData] = useState<SitemapList | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [needWrite, setNeedWrite] = useState(false);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    listSitemaps()
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setError(null);
      })
      .catch((e) => {
        if (cancelled) return;
        const c = classifyError(e);
        if (c.kind === "reauth") onReauth();
        setError(c.message);
      });
    return () => {
      cancelled = true;
    };
  }, [onReauth, property, version]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!url.trim()) return;
    setBusy(true);
    setError(null);
    setDone(false);
    try {
      await submitSitemap(url.trim());
      setDone(true);
      setUrl("");
      setVersion((v) => v + 1);
    } catch (err) {
      const c = classifyError(err);
      if (c.kind === "write") setNeedWrite(true);
      if (c.kind === "reauth") onReauth();
      setError(c.kind === "write" ? null : c.message);
    } finally {
      setBusy(false);
    }
  }

  async function grant() {
    setError(null);
    try {
      await beginConnect(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the request.");
    }
  }

  const readOnly = needWrite || (data !== null && !data.can_write);

  return (
    <section aria-label="Sitemaps" className="space-y-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4">
      <div>
        <h2 className="text-lg font-semibold text-slate-100">Sitemaps</h2>
        <p className="text-sm text-slate-400">Sitemaps Google already knows for this property.</p>
      </div>

      {error && (
        <Alert variant="destructive" className="border-red-900 bg-red-950/50">
          <AlertCircle />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}

      {data === null && !error && <p className="text-sm text-slate-500">Loading sitemaps…</p>}
      {data && data.sitemaps.length === 0 && <p className="text-sm text-slate-400">No sitemaps submitted yet.</p>}
      {data && data.sitemaps.length > 0 && (
        <ul aria-label="Known sitemaps" className="space-y-2">
          {data.sitemaps.map((s) => (
            <li key={s.path} className="rounded-md border border-slate-800 bg-slate-950/60 p-2 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <span className="break-all font-mono text-slate-100">{s.path}</span>
                {s.is_pending && (
                  <span className="rounded-full border border-amber-800 px-2 py-0.5 text-xs text-amber-300">Pending</span>
                )}
                {s.is_sitemaps_index && (
                  <span className="rounded-full border border-slate-700 px-2 py-0.5 text-xs text-slate-300">Index</span>
                )}
              </div>
              <p className="text-xs text-slate-400">
                Submitted {formatTime(s.last_submitted)} · Last read by Google {formatTime(s.last_downloaded)}
              </p>
              <p className="text-xs">
                <span className={s.errors ? "text-red-400" : "text-slate-400"}>
                  {s.errors} error{s.errors === 1 ? "" : "s"}
                </span>
                <span className="text-slate-600"> · </span>
                <span className={s.warnings ? "text-amber-300" : "text-slate-400"}>
                  {s.warnings} warning{s.warnings === 1 ? "" : "s"}
                </span>
              </p>
            </li>
          ))}
        </ul>
      )}

      {readOnly ? (
        <div role="note" className="rounded-md border border-slate-700 bg-slate-950/60 p-3 text-sm text-slate-300">
          <p>
            Submitting needs extra permission. Your connection is read-only; to submit a sitemap, Google must ask you
            to allow Search Console changes.
          </p>
          <Button type="button" size="sm" className="mt-2" onClick={grant}>
            Grant write access
          </Button>
        </div>
      ) : (
        <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row">
          <input
            aria-label="Sitemap URL"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://your-site.com/sitemap.xml"
            inputMode="url"
            className="h-9 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100 placeholder:text-slate-600 outline-none focus-visible:border-emerald-500 focus-visible:ring-3 focus-visible:ring-emerald-500/30"
          />
          <Button type="submit" disabled={busy || !url.trim()} className="shrink-0">
            {busy ? "Submitting…" : "Submit sitemap"}
          </Button>
        </form>
      )}
      {done && (
        <p role="status" className="flex items-center gap-1 text-sm text-emerald-300">
          <CheckCircle2 className="size-4" /> Sitemap submitted to Google.
        </p>
      )}
    </section>
  );
}
