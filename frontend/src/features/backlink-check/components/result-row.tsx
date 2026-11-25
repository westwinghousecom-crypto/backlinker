"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { CheckItem, GoogleNote, Problem } from "../types";
import { GoogleNoteControls } from "./google-note";
import {
  backlinkLabel,
  googlebotLabel,
  LINK_TYPE_LABEL,
  VERDICT_CLASS,
  VERDICT_HELP,
  VERDICT_LABEL,
  verdictOf,
} from "../lib/labels";

export function VerdictBadge({ item }: { item: CheckItem }) {
  const v = verdictOf(item);
  return (
    <span
      title={v === "pending" ? "Waiting to be checked" : VERDICT_HELP[v]}
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${VERDICT_CLASS[v]}`}
    >
      {VERDICT_LABEL[v]}
    </span>
  );
}

function ProblemItem({ p }: { p: Problem }) {
  const tone =
    p.severity === "error"
      ? "border-red-900/70 bg-red-950/30"
      : p.severity === "warning"
        ? "border-amber-900/70 bg-amber-950/30"
        : "border-slate-800 bg-slate-900/40";
  return (
    <li className={`rounded-md border p-2 text-sm ${tone}`}>
      <div className="font-medium text-slate-100">{p.title}</div>
      <p className="mt-0.5 text-slate-300">{p.explanation}</p>
      <p className="mt-0.5 text-slate-400">
        <span className="font-medium text-emerald-400">How to fix: </span>
        {p.fix}
      </p>
    </li>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="break-words text-sm text-slate-200">{children}</dd>
    </div>
  );
}

function linkText(item: CheckItem): string {
  const r = item.result;
  if (!r) return "—";
  const label = backlinkLabel(r);
  if (label !== "Found") return label;
  return r.backlink_type ? `Found · ${LINK_TYPE_LABEL[r.backlink_type]}` : label;
}

/** One checked URL. Renders as a stacked card on phones and a grid row on wider screens. */
export function ResultRow({
  item,
  onRecheck,
  rechecking,
  onMark,
  marking = false,
}: {
  item: CheckItem;
  onRecheck: (item: CheckItem) => void;
  rechecking: boolean;
  onMark?: (item: CheckItem, result: GoogleNote | "clear") => void;
  marking?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const r = item.result;
  const problems = r?.problems.filter((p) => p.severity !== "info") ?? [];
  const info = r?.problems.filter((p) => p.severity === "info") ?? [];
  const redirected = r?.final_url && r.final_url !== item.url;

  return (
    <li className="rounded-lg border border-slate-800 bg-slate-900/50">
      <div className="grid gap-2 p-3 md:grid-cols-[minmax(0,2.2fr)_7.25rem_3rem_5rem_4.25rem_minmax(0,1.6fr)_4.75rem_auto] md:items-center md:gap-3">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="flex min-w-0 items-start gap-1 text-left"
        >
          {open ? (
            <ChevronDown className="mt-0.5 size-4 shrink-0 text-slate-400" />
          ) : (
            <ChevronRight className="mt-0.5 size-4 shrink-0 text-slate-400" />
          )}
          <span className="min-w-0">
            <span className="block truncate font-mono text-sm text-slate-100" title={item.url}>
              {item.url}
            </span>
            {redirected && (
              <span className="block truncate text-xs text-slate-500" title={r?.final_url ?? ""}>
                → {r?.final_url}
              </span>
            )}
          </span>
        </button>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm md:contents">
          <span className="md:block">
            <VerdictBadge item={item} />
          </span>
          <span className="tabular-nums text-slate-300" title="HTTP status">
            <span className="text-xs text-slate-500 md:hidden">HTTP </span>
            {r ? (r.status ?? "—") : "…"}
          </span>
          <span className="text-slate-300" title="Can Googlebot crawl it?">
            <span className="text-xs text-slate-500 md:hidden">Googlebot </span>
            {r ? googlebotLabel(r) : "…"}
          </span>
          <span className={r?.noindex ? "text-red-400" : "text-slate-300"} title="noindex directive">
            <span className="text-xs text-slate-500 md:hidden">noindex </span>
            {r ? (r.noindex ? "Yes" : "No") : "…"}
          </span>
          <span
            className={`min-w-0 truncate ${r?.backlink_found === false ? "text-red-400" : "text-slate-300"}`}
            title={r?.backlink_anchor ? `Anchor: ${r.backlink_anchor}` : undefined}
          >
            <span className="text-xs text-slate-500 md:hidden">Link </span>
            {linkText(item)}
            {r?.backlink_anchor ? (
              <span className="text-slate-500"> “{r.backlink_anchor}”</span>
            ) : null}
          </span>
          <span className="text-slate-400" title="Technical checks cannot confirm Google indexing">
            <span className="text-xs text-slate-500 md:hidden">Google index </span>
            Unknown
          </span>
        </div>

        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          onClick={() => onRecheck(item)}
          disabled={rechecking || item.state !== "done"}
          aria-label={`Recheck ${item.url}`}
          title="Recheck this URL"
          className="justify-self-end"
        >
          <RefreshCw className={rechecking ? "animate-spin" : ""} />
        </Button>
      </div>

      {open && (
        <div className="space-y-3 border-t border-slate-800 p-3">
          {!r ? (
            <p className="text-sm text-slate-400">This URL is waiting to be checked.</p>
          ) : (
            <>
              <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <Field label="Final URL">{r.final_url ?? "—"}</Field>
                <Field label="Redirects">
                  {r.redirects.length ? `${r.redirects.length} hop${r.redirects.length === 1 ? "" : "s"}` : "None"}
                </Field>
                <Field label="Googlebot crawl">{googlebotLabel(r)}</Field>
                <Field label="noindex">
                  {r.noindex ? `Yes (${r.noindex_source ?? "unknown"})` : "No"}
                </Field>
                <Field label="Canonical URL">
                  {r.canonical ?? "Not set"}
                  {r.canonical_mismatch && <span className="text-amber-400"> (points elsewhere)</span>}
                </Field>
                <Field label="Your backlink">{linkText(item)}</Field>
                <Field label="Anchor text">{r.backlink_anchor ?? "—"}</Field>
                <Field label="Google index status">
                  Unknown{" "}
                  <span className="text-slate-500">
                    (only authorized Search Console data can confirm indexing)
                  </span>
                  <GoogleNoteControls
                    url={item.url}
                    note={item.manual_google}
                    at={item.manual_google_at}
                    busy={marking}
                    onMark={onMark ? (res) => onMark(item, res) : undefined}
                  />
                </Field>
              </dl>
              {problems.length > 0 ? (
                <ul className="space-y-2" aria-label="Problems">
                  {problems.map((p) => (
                    <ProblemItem key={p.code} p={p} />
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-emerald-300">
                  No technical problems found. This does not mean the page is indexed.
                </p>
              )}
              {info.length > 0 && (
                <ul className="space-y-2" aria-label="Notes">
                  {info.map((p) => (
                    <ProblemItem key={p.code} p={p} />
                  ))}
                </ul>
              )}
              <p className="text-xs text-slate-500">
                Pages are read as plain HTML. &quot;Not in HTML&quot; means the link is not in what the server sent; it may still
                appear if the page adds links with JavaScript. Open the page to confirm.
              </p>
            </>
          )}
        </div>
      )}
    </li>
  );
}

export function ResultsHeader() {
  return (
    <div
      aria-hidden
      className="hidden gap-3 px-3 text-xs uppercase tracking-wide text-slate-500 md:grid md:grid-cols-[minmax(0,2.2fr)_7.25rem_3rem_5rem_4.25rem_minmax(0,1.6fr)_4.75rem_auto]"
    >
      <span className="pl-5">URL</span>
      <span>Result</span>
      <span>HTTP</span>
      <span>Googlebot</span>
      <span>noindex</span>
      <span>Your link</span>
      <span>Google index</span>
      <span className="w-7" />
    </div>
  );
}
