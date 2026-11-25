"use client";

import { useEffect, useState } from "react";
import { Check, Copy, Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { downloadBatchFile, getSharing, setSharing } from "../api/submit-urls";
import type { SharingState } from "../types";

/** Private feed downloads plus the explicit opt-in for a public feed. Nothing is public unless this is switched on. */
export function SharingControls({ batchId }: { batchId: string }) {
  const [state, setState] = useState<SharingState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getSharing(batchId)
      .then((s) => {
        if (!cancelled) setState(s);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : "Could not load sharing settings.");
      });
    return () => {
      cancelled = true;
    };
  }, [batchId]);

  async function toggle(next: boolean) {
    setSaving(true);
    setError(null);
    try {
      setState(await setSharing(batchId, next));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not change sharing.");
    } finally {
      setSaving(false);
    }
  }

  async function download(kind: "feed" | "sitemap") {
    setError(null);
    try {
      await downloadBatchFile(batchId, kind);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed.");
    }
  }

  async function copy(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard unavailable
    }
  }

  const isPublic = state?.public_feed ?? false;
  return (
    <div className="mt-3 space-y-2 border-t border-slate-800 pt-3 text-xs text-slate-400">
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="outline" size="xs" onClick={() => download("feed")}>
          <Download /> Download feed
        </Button>
        <Button type="button" variant="outline" size="xs" onClick={() => download("sitemap")}>
          <Download /> Download sitemap
        </Button>
      </div>
      <label className="flex items-start gap-2">
        <input
          type="checkbox"
          checked={isPublic}
          disabled={state === null || saving}
          onChange={(e) => toggle(e.target.checked)}
          className="mt-0.5 size-4 accent-emerald-500"
        />
        <span>
          <span className="font-medium text-slate-200">Public feed</span>
          <span className="block">
            Off by default. Turning this on lets anyone with the link read this batch&apos;s URL list.
          </span>
        </span>
      </label>
      {isPublic && state?.public_url && (
        <div className="flex items-center gap-2">
          <code className="truncate rounded bg-slate-950 px-2 py-0.5 font-mono text-emerald-300">
            {state.public_url}
          </code>
          <Button
            type="button"
            variant="ghost"
            size="icon-xs"
            aria-label="Copy public feed link"
            onClick={() => copy(state.public_url!)}
          >
            {copied ? <Check /> : <Copy />}
          </Button>
        </div>
      )}
      {error && (
        <p role="alert" className="text-amber-400">
          {error}
        </p>
      )}
    </div>
  );
}
