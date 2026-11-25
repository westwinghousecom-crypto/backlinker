"use client";

import { useEffect, useState } from "react";
import { getPublicCheckBatch, PublicReportError } from "../api/public-report";
import type { CheckBatch } from "../types";
import { PublicResultRow } from "./public-result-row";
import { SummaryCards } from "./summary-cards";

/**
 * The actual content of `/report/[batchId]`, split out so it can be tested directly with a plain `batchId` string.
 * The real route (`src/app/report/[batchId]/page.tsx`) is a thin wrapper that unwraps Next's `params` Promise with
 * `use()` and renders this. It has no AuthGate and no dashboard chrome: visitors here have no QuickIndex account at
 * all, so this never sends or expects a sign-in token.
 */
export function PublicReportPageContent({ batchId }: { batchId: string }) {
  const [batch, setBatch] = useState<CheckBatch | null>(null);
  const [error, setError] = useState<{ status: number; message: string } | null>(null);

  useEffect(() => {
    let cancelled = false;
    // Deliberately no setBatch(null)/setError(null) reset here (lint forbids setState as the first effect action):
    // the previous batch stays on screen until the new fetch resolves. Fine for a page keyed by one static link.
    getPublicCheckBatch(batchId)
      .then((b) => {
        if (!cancelled) setBatch(b);
      })
      .catch((e) => {
        if (cancelled) return;
        if (e instanceof PublicReportError) setError({ status: e.status, message: e.message });
        else setError({ status: 0, message: "Something went wrong. Please try again." });
      });
    return () => {
      cancelled = true;
    };
  }, [batchId]);

  if (error) {
    return (
      <main className="mx-auto max-w-2xl px-4 py-16 text-center">
        <h1 className="text-lg font-semibold text-slate-100">
          {error.status === 404 ? "Report not found" : "Something went wrong"}
        </h1>
        <p className="mt-2 text-sm text-slate-400">{error.message}</p>
      </main>
    );
  }

  if (!batch) {
    return (
      <main className="mx-auto max-w-2xl px-4 py-16 text-center">
        <p role="status" className="text-sm text-slate-400">
          Loading…
        </p>
      </main>
    );
  }

  const hasTarget = Boolean(batch.target);

  return (
    <main className="mx-auto max-w-4xl space-y-4 px-4 py-10">
      <div>
        <p className="text-xs uppercase tracking-wide text-emerald-400">QuickIndex · Backlink check report</p>
        <h1 className="mt-1 text-lg font-semibold text-slate-100">
          {hasTarget ? (
            <>
              Looking for links to <span className="font-mono text-slate-300">{batch.target}</span>
            </>
          ) : (
            "Backlink check results"
          )}
        </h1>
        <p className="mt-1 text-xs text-slate-500">
          Read-only report shared by the account owner. No sign-in is needed to view it.
        </p>
      </div>

      <SummaryCards summary={batch.summary} hasTarget={hasTarget} />

      {batch.items.length === 0 ? (
        <p className="rounded-lg border border-slate-800 bg-slate-900/40 p-6 text-center text-sm text-slate-400">
          No URLs in this batch.
        </p>
      ) : (
        <ul className="space-y-2" aria-label="URL results">
          {batch.items.map((item) => (
            <PublicResultRow key={item.id} item={item} />
          ))}
        </ul>
      )}
    </main>
  );
}
