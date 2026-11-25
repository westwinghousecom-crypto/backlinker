import { request } from "@/lib/api";
import type {
  CheckBatch,
  CheckBatchRow,
  CreateCheckBatchRequest,
  CreateCheckBatchResponse,
  GoogleNote,
  ReportSharingState,
} from "../types";

export function createCheckBatch(
  payload: CreateCheckBatchRequest,
): Promise<CreateCheckBatchResponse> {
  return request("/api/v1/check-batches", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getCheckBatch(batchId: string): Promise<CheckBatch> {
  return request(`/api/v1/check-batches/${encodeURIComponent(batchId)}`);
}

/** The signed-in customer's own batches (the server decides who that is). */
export function listCheckBatches(): Promise<CheckBatchRow[]> {
  return request("/api/v1/check-batches?limit=20");
}

export function deleteCheckBatch(batchId: string): Promise<void> {
  return request(`/api/v1/check-batches/${encodeURIComponent(batchId)}`, {
    method: "DELETE",
  });
}

export function recheckUrl(batchId: string, checkId: string): Promise<{ status: string }> {
  return request(
    `/api/v1/check-batches/${encodeURIComponent(batchId)}/checks/${encodeURIComponent(checkId)}/recheck`,
    { method: "POST" },
  );
}

/** Whether the owner has opted in to a public, read-only report link for this batch. Private by default. */
export function getSharing(batchId: string): Promise<ReportSharingState> {
  return request(`/api/v1/check-batches/${encodeURIComponent(batchId)}/sharing`);
}

export function setSharing(batchId: string, publicReport: boolean): Promise<ReportSharingState> {
  return request(`/api/v1/check-batches/${encodeURIComponent(batchId)}/sharing`, {
    method: "PUT",
    body: JSON.stringify({ public_report: publicReport }),
  });
}

/** Save (or clear) the customer's own note from searching Google themselves. */
export function markGoogleSearch(
  batchId: string,
  checkId: string,
  result: GoogleNote | "clear",
): Promise<{ manual_google: GoogleNote | null; manual_google_at: string | null }> {
  return request(
    `/api/v1/check-batches/${encodeURIComponent(batchId)}/checks/${encodeURIComponent(checkId)}/manual-google`,
    { method: "PUT", body: JSON.stringify({ result }) },
  );
}
