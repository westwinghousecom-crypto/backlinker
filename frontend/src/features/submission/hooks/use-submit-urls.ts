"use client";

import { useCallback, useState } from "react";
import { submitUrls } from "../api/submit-urls";
import type { SubmitUrlsResponse } from "../types";

export function useSubmitUrls() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SubmitUrlsResponse | null>(null);

  const submit = useCallback(async (urls: string[]): Promise<SubmitUrlsResponse | null> => {
    setIsLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await submitUrls({ urls });
      setResult(res);
      return res;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
      return null;
    } finally {
      setIsLoading(false);
    }
  }, []);

  return { submit, isLoading, error, result };
}
