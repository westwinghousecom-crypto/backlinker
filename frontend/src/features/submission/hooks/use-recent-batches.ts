"use client";

import { useEffect, useState } from "react";
import { listRecentBatches } from "../api/submit-urls";
import type { RecentBatch } from "../types";

/** Recent submission batches from the database. Pass a changing `reloadKey` (e.g. the open batch id) to reload. */
export function useRecentBatches(reloadKey: string | null) {
  const [batches, setBatches] = useState<RecentBatch[]>([]);

  useEffect(() => {
    let cancelled = false;
    listRecentBatches()
      .then((rows) => {
        if (!cancelled) setBatches(rows);
      })
      .catch(() => {
        // the list is a convenience: the form works without it
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  return batches;
}
