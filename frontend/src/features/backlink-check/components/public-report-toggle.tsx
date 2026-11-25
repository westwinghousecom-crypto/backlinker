"use client";

import { useEffect, useState } from "react";
import { Check, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getSharing, setSharing } from "../api/check-api";
import type { ReportSharingState } from "../types";

/** Explicit opt-in to a public, read-only link for this batch's results (e.g. for an agency to show a client, with no
 *  login needed). Nothing is public unless this is switched on, and the link never carries the owner's own Google
 *  search notes — those are private, self-reported, and stay that way. */
export function PublicReportToggle({ batchId }: { batchId: string }) {
  const [state, setState] = useState<ReportSharingState | null>(null);
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

  async function copy(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard unavailable
    }
  }

  const isPublic = state?.public_report ?? false;
  return (
    <div className="mt-3 space-y-2 border-t border-slate-800 pt-3 text-xs text-slate-400">
      <label className="flex items-start gap-2">
        <input
          type="checkbox"
          checked={isPublic}
          disabled={state === null || saving}
          onChange={(e) => toggle(e.target.checked)}
          className="mt-0.5 size-4 accent-emerald-500"
        />
        <span>
          <span className="font-medium text-slate-200">Public report</span>
          <span className="block">
            Off by default. Turning this on lets anyone with the link see these results — not your account, and never
            your own Google search notes, which stay private.
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
            aria-label="Copy public report link"
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
