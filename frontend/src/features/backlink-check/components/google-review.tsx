"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import type { CheckItem, GoogleNote } from "../types";
import { googleSiteSearchUrl } from "../lib/labels";

/** Walk through checked pages one at a time: open the Google search, say what you saw, move on. Every search opens from a
 *  click of yours, so the browser never blocks it. Notes are self-reported and never change a result. */
export function GoogleReview({
  items,
  onMark,
}: {
  items: CheckItem[];
  onMark: (item: CheckItem, result: GoogleNote | "clear") => Promise<void>;
}) {
  const [queue, setQueue] = useState<CheckItem[] | null>(null);
  const [pos, setPos] = useState(0);
  const [busy, setBusy] = useState(false);

  const waiting = items.filter((i) => i.state === "done" && !i.manual_google);

  if (!queue) {
    return (
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={waiting.length === 0}
        onClick={() => {
          setQueue(waiting);
          setPos(0);
        }}
      >
        Review on Google ({waiting.length.toLocaleString()})
      </Button>
    );
  }

  const current = queue[pos];

  async function answer(result: GoogleNote) {
    if (!current) return;
    setBusy(true);
    try {
      await onMark(current, result);
      setPos((p) => p + 1);
    } catch {
      // the error is shown by the results view; stay on this page so the answer can be tried again
    } finally {
      setBusy(false);
    }
  }

  return (
    <section aria-label="Review on Google" className="w-full rounded-lg border border-slate-800 bg-slate-900/60 p-3 text-sm">
      {current ? (
        <div className="space-y-2">
          <p className="text-xs text-slate-400">
            Page {pos + 1} of {queue.length.toLocaleString()}
          </p>
          <p className="break-all font-mono text-slate-100">{current.url}</p>
          <a
            href={googleSiteSearchUrl(current.url)}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-block text-emerald-400 underline underline-offset-2"
          >
            Open Google search
          </a>
          <p className="text-xs text-slate-500">
            Finding it is a good sign. Not finding it proves nothing. Your answer is saved as self-reported.
          </p>
          <div className="flex flex-wrap gap-2">
            <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => answer("appears")}>
              It appeared
            </Button>
            <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => answer("not_found")}>
              Not found
            </Button>
            <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setPos((p) => p + 1)}>
              Skip
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => setQueue(null)}>
              Stop
            </Button>
          </div>
        </div>
      ) : (
        <div className="flex items-center justify-between gap-2">
          <p className="text-slate-300">All {queue.length.toLocaleString()} reviewed.</p>
          <Button type="button" size="sm" variant="ghost" onClick={() => setQueue(null)}>
            Close
          </Button>
        </div>
      )}
    </section>
  );
}
