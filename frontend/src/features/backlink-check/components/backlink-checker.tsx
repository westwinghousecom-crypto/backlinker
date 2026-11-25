"use client";

import { useCallback } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertCircle } from "lucide-react";
import { useCheckBatch } from "../hooks/use-check-batch";
import { CheckForm } from "./check-form";
import { HistoryList } from "./history-list";
import { ResultsView } from "./results-view";

/** The selected batch lives in the URL (?batch=...), so results can be bookmarked and survive a reload. */
export function BacklinkChecker() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const batchId = params.get("batch");
  const { batch, error, refresh } = useCheckBatch(batchId);

  const select = useCallback(
    (id: string | null) => {
      router.replace(id ? `${pathname}?batch=${encodeURIComponent(id)}` : pathname);
    },
    [router, pathname],
  );

  return (
    <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_18rem]">
      <div className="min-w-0 space-y-6">
        <CheckForm onCreated={select} />
        {batchId && error && !batch && (
          <Alert variant="destructive" className="border-red-900 bg-red-950/50">
            <AlertCircle />
            <AlertTitle>Could not load this batch</AlertTitle>
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {batchId && !batch && !error && <p className="text-sm text-slate-400">Loading results…</p>}
        {batch && <ResultsView key={batch.batch_id} batch={batch} onChanged={refresh} onDeleted={() => select(null)} />}
      </div>
      <aside className="lg:sticky lg:top-6 lg:self-start">
        <HistoryList activeId={batchId} reloadKey={`${batchId}:${batch?.summary.done ? "done" : "running"}`} onSelect={select} />
      </aside>
    </div>
  );
}
