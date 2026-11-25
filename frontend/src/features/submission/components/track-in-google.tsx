"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { addTargets, getStatus } from "@/features/google/api/google-api";
import { classifyError, OUTSIDE_PROPERTY_NOTE, skippedReason } from "@/features/google/lib/labels";
import type { GoogleStatus, SkippedUrl } from "@/features/google/types";

const CHUNK = 200; // the API accepts at most 200 URLs per request

/** One-click hand-off from a submission batch to Google Index Status. Only pages on the customer's own connected Search Console
 *  property can be inspected: the server checks every URL again, so anything else is skipped with a reason, never inspected. */
export function TrackInGoogle({ urls }: { urls: string[] }) {
  const [google, setGoogle] = useState<GoogleStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ added: number; skipped: SkippedUrl[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getStatus()
      .then((s) => {
        if (!cancelled) setGoogle(s);
      })
      .catch(() => {
        // the hand-off is optional: without Google status simply show nothing
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!google?.configured) return null;

  async function track() {
    setBusy(true);
    setError(null);
    const unique = [...new Set(urls)];
    let added = 0;
    const skipped: SkippedUrl[] = [];
    try {
      for (let i = 0; i < unique.length; i += CHUNK) {
        const res = await addTargets(unique.slice(i, i + CHUNK));
        added += res.added;
        skipped.push(...res.skipped);
      }
    } catch (e) {
      setError(classifyError(e).message);
    } finally {
      setDone({ added, skipped });
      setBusy(false);
    }
  }

  const skippedByReason = new Map<string, number>();
  for (const s of done?.skipped ?? []) skippedByReason.set(s.reason, (skippedByReason.get(s.reason) ?? 0) + 1);

  let body;
  if (!google.connected) {
    body = (
      <p>
        Own the site these pages are on? Connect Google Search Console and Google itself can tell you whether they are
        indexed.{" "}
        <Link href="/dashboard/google" className="underline underline-offset-2">
          Connect Google Search Console
        </Link>
      </p>
    );
  } else if (google.reauth_required) {
    body = (
      <p>
        Google access expired or was revoked.{" "}
        <Link href="/dashboard/google" className="underline underline-offset-2">
          Reconnect Google
        </Link>
      </p>
    );
  } else if (!google.selected_property) {
    body = (
      <p>
        Choose a Search Console property first.{" "}
        <Link href="/dashboard/google" className="underline underline-offset-2">
          Open Google Index Status
        </Link>
      </p>
    );
  } else {
    body = (
      <>
        <p>
          For pages on your connected property (<span className="font-mono text-slate-300">{google.selected_property}</span>), we
          ask Google directly whether they are indexed: now, then again after 1, 3, 7 and 14 days. Pages on other sites cannot
          be checked and are skipped.
        </p>
        <Button type="button" variant="outline" size="xs" className="mt-2" onClick={track} disabled={busy || urls.length === 0}>
          {busy ? "Adding…" : "Track in Google Index Status"}
        </Button>
      </>
    );
  }

  return (
    <div className="mt-3 space-y-1 border-t border-slate-800 pt-3 text-xs text-slate-400" aria-label="Google Index Status">
      <div className="font-medium text-slate-200">Google Index Status</div>
      {body}
      {error && (
        <p role="alert" className="text-red-400">
          {error}
        </p>
      )}
      {done && (
        <div role="status" className="space-y-0.5 text-slate-300">
          <p>
            {done.added.toLocaleString()} URL{done.added === 1 ? "" : "s"} added for Google checks.
            {done.skipped.length > 0 && ` ${done.skipped.length.toLocaleString()} skipped.`}
          </p>
          {[...skippedByReason].map(([reason, n]) => (
            <p key={reason} className="text-slate-400">
              {n.toLocaleString()} skipped: {skippedReason(reason)}
            </p>
          ))}
          {skippedByReason.has("outside_property") && (
            <p className="text-slate-400">
              {OUTSIDE_PROPERTY_NOTE}{" "}
              <Link href="/dashboard/backlinks" className="underline underline-offset-2">
                Check my backlinks
              </Link>
            </p>
          )}
          {done.added > 0 && (
            <Link href="/dashboard/google" className="text-emerald-400 underline underline-offset-2">
              See results in Google Index Status
            </Link>
          )}
        </div>
      )}
    </div>
  );
}
