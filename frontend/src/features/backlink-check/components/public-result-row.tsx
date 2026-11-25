"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { CheckItem, Problem } from "../types";
import {
  backlinkLabel,
  googlebotLabel,
  LINK_TYPE_LABEL,
  VERDICT_CLASS,
  VERDICT_HELP,
  VERDICT_LABEL,
  verdictOf,
} from "../lib/labels";

function linkText(item: CheckItem): string {
  const r = item.result;
  if (!r) return "—";
  const label = backlinkLabel(r);
  if (label !== "Found") return label;
  return r.backlink_type ? `Found · ${LINK_TYPE_LABEL[r.backlink_type]}` : label;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
      <dd className="break-words text-sm text-slate-200">{children}</dd>
    </div>
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

/** Read-only row for the public client report. No recheck button, no delete button, no Google-note controls: a
 *  visitor has no QuickIndex session to act with, and the page must never invite them to try. */
export function PublicResultRow({ item }: { item: CheckItem }) {
  const [open, setOpen] = useState(false);
  const r = item.result;
  const problems = r?.problems.filter((p) => p.severity !== "info") ?? [];
  const info = r?.problems.filter((p) => p.severity === "info") ?? [];
  const redirected = r?.final_url && r.final_url !== item.url;
  const v = verdictOf(item);

  return (
    <li className="rounded-lg border border-slate-800 bg-slate-900/50">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full min-w-0 items-start gap-2 p-3 text-left"
      >
        {open ? (
          <ChevronDown className="mt-0.5 size-4 shrink-0 text-slate-400" />
        ) : (
          <ChevronRight className="mt-0.5 size-4 shrink-0 text-slate-400" />
        )}
        <span className="min-w-0 flex-1">
          <span className="block truncate font-mono text-sm text-slate-100" title={item.url}>
            {item.url}
          </span>
          {redirected && (
            <span className="block truncate text-xs text-slate-500" title={r?.final_url ?? ""}>
              → {r?.final_url}
            </span>
          )}
        </span>
        <span
          title={v === "pending" ? "Waiting to be checked" : VERDICT_HELP[v]}
          className={`inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-xs font-medium ${VERDICT_CLASS[v]}`}
        >
          {VERDICT_LABEL[v]}
        </span>
      </button>

      {open && (
        <div className="space-y-3 border-t border-slate-800 p-3">
          {!r ? (
            <p className="text-sm text-slate-400">This URL is still being checked.</p>
          ) : (
            <>
              <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                <Field label="HTTP status">{r.status ?? "—"}</Field>
                <Field label="Googlebot crawl">{googlebotLabel(r)}</Field>
                <Field label="noindex">{r.noindex ? `Yes (${r.noindex_source ?? "unknown"})` : "No"}</Field>
                <Field label="Canonical URL">
                  {r.canonical ?? "Not set"}
                  {r.canonical_mismatch && <span className="text-amber-400"> (points elsewhere)</span>}
                </Field>
                <Field label="Backlink">{linkText(item)}</Field>
                <Field label="Anchor text">{r.backlink_anchor ?? "—"}</Field>
                <Field label="Google index status">
                  Unknown{" "}
                  <span className="text-slate-500">(only authorized Search Console data can confirm indexing)</span>
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
            </>
          )}
        </div>
      )}
    </li>
  );
}
