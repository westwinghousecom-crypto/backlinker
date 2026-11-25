"use client";

import { useCallback, useEffect, useState } from "react";
import { getCheckBatch } from "../api/check-api";
import type { CheckBatch } from "../types";

const POLL_MS = 2500;

/** Loads a batch and polls until every URL has been checked. `refresh` restarts polling (e.g. after a recheck). */
export function useCheckBatch(batchId: string | null) {
  const [batch, setBatch] = useState<CheckBatch | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    if (!batchId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    async function tick() {
      try {
        const b = await getCheckBatch(batchId!);
        if (cancelled) return;
        setBatch(b);
        setError(null);
        if (b.summary.done) return;
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Could not load results.");
      }
      timer = setTimeout(tick, POLL_MS);
    }
    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [batchId, nonce]);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);
  const current = batchId && batch?.batch_id === batchId ? batch : null;
  return { batch: current, error: batchId ? error : null, refresh };
}
