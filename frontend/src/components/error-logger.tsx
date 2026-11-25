"use client";

import { useEffect } from "react";
import { logClientError } from "@/lib/logger";

/** Writes uncaught errors and unhandled promise failures to the browser console with the QuickIndex prefix. Renders nothing. */
export function ErrorLogger() {
  useEffect(() => {
    const onError = (e: ErrorEvent) => logClientError("uncaught error", e.error ?? e.message, { where: e.filename ? `${e.filename}:${e.lineno}` : undefined });
    const onRejection = (e: PromiseRejectionEvent) => logClientError("unhandled promise rejection", e.reason);
    window.addEventListener("error", onError);
    window.addEventListener("unhandledrejection", onRejection);
    return () => {
      window.removeEventListener("error", onError);
      window.removeEventListener("unhandledrejection", onRejection);
    };
  }, []);
  return null;
}
