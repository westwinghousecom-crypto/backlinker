"use client";

import { useEffect, useState } from "react";
import { getBatchStatus } from "../api/submit-urls";
import type { BatchStatus } from "../types";

const POLL_MS = 3000;

/** Polls batch status until every URL is completed or failed. */
export function useBatchStatus(batchId: string | null) {
  const [status, setStatus] = useState<BatchStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!batchId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    async function tick() {
      try {
        const s = await getBatchStatus(batchId!);
        if (cancelled) return;
        setStatus(s);
        setError(null);
        if (s.done) return;
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Could not load status.");
      }
      timer = setTimeout(tick, POLL_MS);
    }
    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [batchId]);

  return { status: batchId ? status : null, error: batchId ? error : null };
}
