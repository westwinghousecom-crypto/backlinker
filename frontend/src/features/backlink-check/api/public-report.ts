import { API_BASE_URL } from "@/lib/config";
import type { CheckBatch } from "../types";

/** Thrown by {@link getPublicCheckBatch}. `status` is 0 for an unreachable server, otherwise the HTTP status. */
export class PublicReportError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "PublicReportError";
  }
}

/**
 * Unauthenticated fetch of a batch's public report. Deliberately separate from `@/lib/api`'s `request()`, which always
 * attaches a bearer token: a visitor reading a shared report has no QuickIndex account and must never be asked for one.
 */
export async function getPublicCheckBatch(batchId: string): Promise<CheckBatch> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/api/v1/check-batches/${encodeURIComponent(batchId)}/public`);
  } catch {
    throw new PublicReportError("Could not reach the server. Please try again.", 0);
  }
  if (!res.ok) {
    throw new PublicReportError(
      res.status === 404
        ? "This report isn't available. The link may be wrong, or the owner may have turned sharing off."
        : `Request failed (${res.status})`,
      res.status,
    );
  }
  return (await res.json()) as CheckBatch;
}
