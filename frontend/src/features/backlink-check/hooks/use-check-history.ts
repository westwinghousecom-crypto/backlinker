"use client";

import { useEffect, useState } from "react";
import { listCheckBatches } from "../api/check-api";
import type { CheckBatchRow } from "../types";

/** Recent batches for the signed-in customer. Pass a changing `reloadKey` to reload. */
export function useCheckHistory(reloadKey: string | null) {
  const [rows, setRows] = useState<CheckBatchRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listCheckBatches()
      .then((r) => {
        if (cancelled) return;
        setRows(r);
        setError(null);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Could not load history.");
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  return { rows, error };
}
