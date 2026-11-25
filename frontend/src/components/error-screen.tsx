"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui/button";
import { logClientError } from "@/lib/logger";

/** What the customer sees when a page crashes: a plain message and a way to try again. The details go to the console only. */
export function ErrorScreen({ error, retry, scope }: { error: unknown; retry: () => void; scope: string }) {
  const digest = error instanceof Error ? (error as Error & { digest?: string }).digest : undefined;
  useEffect(() => {
    logClientError(scope, error, { digest });
  }, [error, scope, digest]);

  return (
    <div role="alert" className="mx-auto flex max-w-md flex-col items-center gap-3 px-4 py-16 text-center">
      <h2 className="text-lg font-semibold text-slate-100">Something went wrong</h2>
      <p className="text-sm text-slate-400">
        This page hit an unexpected problem. Your data is safe. Try again, and if it keeps happening, contact support
        {digest ? ` and quote reference ${digest}` : ""}.
      </p>
      <Button type="button" onClick={retry} className="bg-emerald-500 font-semibold text-slate-950 hover:bg-emerald-400">
        Try again
      </Button>
    </div>
  );
}
