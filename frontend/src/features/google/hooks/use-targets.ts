"use client";

import { useCallback, useEffect, useState } from "react";
import { listTargets } from "../api/google-api";
import type { Target } from "../types";

export const POLL_MS = 5000;

const busy = (t: Target) => t.state === "pending" || t.state === "processing";

/** Loads tracked URLs and polls every 5 s while any is waiting for / undergoing an inspection. */
export function useTargets(property: string) {
  const [items, setItems] = useState<Target[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    async function tick() {
      try {
        const res = await listTargets();
        if (cancelled) return;
        setItems(res.items);
        setError(null);
        if (!res.items.some(busy)) return; // nothing in flight: stop polling
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Could not load your URLs.");
        return;
      }
      timer = setTimeout(tick, POLL_MS);
    }
    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [property, nonce]);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);
  return { items, error, refresh };
}
