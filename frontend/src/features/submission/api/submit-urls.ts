import { request, requestText } from "@/lib/api";
import type {
  BatchStatus,
  RecentBatch,
  SharingState,
  SubmitUrlsRequest,
  SubmitUrlsResponse,
} from "../types";

export function submitUrls(
  payload: SubmitUrlsRequest,
): Promise<SubmitUrlsResponse> {
  if (payload.urls.length === 1) {
    return request("/api/v1/submit-one", {
      method: "POST",
      body: JSON.stringify({ url: payload.urls[0] }),
    });
  }
  return request("/api/v1/submit", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getBatchStatus(batchId: string): Promise<BatchStatus> {
  return request(`/api/v1/batches/${encodeURIComponent(batchId)}`);
}

/** Whether the owner has opted in to a public feed for this batch. Private by default. */
export function getSharing(batchId: string): Promise<SharingState> {
  return request(`/api/v1/batches/${encodeURIComponent(batchId)}/sharing`);
}

export function setSharing(batchId: string, publicFeed: boolean): Promise<SharingState> {
  return request(`/api/v1/batches/${encodeURIComponent(batchId)}/sharing`, {
    method: "PUT",
    body: JSON.stringify({ public_feed: publicFeed }),
  });
}

/** Download the owner's own feed/sitemap. These endpoints require sign-in, so a plain link cannot be used. */
export async function downloadBatchFile(batchId: string, kind: "feed" | "sitemap"): Promise<void> {
  const text = await requestText(`/api/v1/batches/${encodeURIComponent(batchId)}/${kind}.xml`);
  const type = kind === "feed" ? "application/rss+xml" : "application/xml";
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = `batch-${batchId.slice(0, 8)}-${kind}.xml`;
  a.click();
  URL.revokeObjectURL(url);
}

/** The signed-in customer's recent submission batches, newest first (the server decides who that is). */
export function listRecentBatches(): Promise<RecentBatch[]> {
  return request("/api/v1/batches");
}
