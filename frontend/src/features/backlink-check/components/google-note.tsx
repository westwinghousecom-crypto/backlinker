"use client";

import { Button } from "@/components/ui/button";
import type { GoogleNote } from "../types";
import { GOOGLE_NOTE_LABEL, googleSiteSearchUrl } from "../lib/labels";

/** "Search this page on Google" plus the customer's own note about what they saw. The note is self-reported: it is stored
 *  and shown with that label, and it never changes a result, a count or the Google index status. */
export function GoogleNoteControls({
  url,
  note,
  at,
  busy,
  onMark,
}: {
  url: string;
  note: GoogleNote | null | undefined;
  at: string | null | undefined;
  busy?: boolean;
  onMark?: (result: GoogleNote | "clear") => void;
}) {
  return (
    <div className="mt-1 space-y-1">
      <a
        href={googleSiteSearchUrl(url)}
        target="_blank"
        rel="noopener noreferrer"
        className="block text-emerald-400 underline underline-offset-2"
      >
        Search this page on Google
      </a>
      <span className="block text-xs text-slate-500">
        If it appears, that is a good sign. If it does not, that proves nothing: Google&apos;s site: search is incomplete.
      </span>
      {onMark && (
        <div className="flex flex-wrap items-center gap-1 pt-1" role="group" aria-label="What did you see on Google?">
          <Button type="button" variant="outline" size="xs" disabled={busy} aria-pressed={note === "appears"} onClick={() => onMark("appears")}>
            It appeared
          </Button>
          <Button type="button" variant="outline" size="xs" disabled={busy} aria-pressed={note === "not_found"} onClick={() => onMark("not_found")}>
            Not found
          </Button>
          {note && (
            <Button type="button" variant="ghost" size="xs" disabled={busy} onClick={() => onMark("clear")}>
              Clear
            </Button>
          )}
        </div>
      )}
      {note && (
        <span className="block text-xs text-slate-300">
          You reported: {GOOGLE_NOTE_LABEL[note]}
          {at ? ` (${new Date(at).toLocaleDateString()})` : ""}. Self-reported, not verified by QuickIndex.
        </span>
      )}
    </div>
  );
}
