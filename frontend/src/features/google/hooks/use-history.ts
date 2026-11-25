"use client";

import { useEffect, useState } from "react";
import { getHistory } from "../api/google-api";
import type { HistoryEntry } from "../types";

/** Inspection history of one URL. Loads only while `enabled`; reloads when `version` changes (a new inspection). */
export function useHistory(id: string, enabled: boolean, version: string | null) {
  const [items, setItems] = useState<HistoryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    getHistory(id)
      .then((r) => {
        if (cancelled) return;
        setItems(r.items);
        setError(null);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Could not load the history.");
      });
    return () => {
      cancelled = true;
    };
  }, [id, enabled, version]);

  return { items, error };
}
