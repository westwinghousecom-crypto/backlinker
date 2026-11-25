export interface SubmitUrlsRequest {
  urls: string[];
}

export interface SubmitUrlsResponse {
  batch_id: string;
  total: number;
}

export interface SharingState {
  public_feed: boolean;
  public_url: string | null;
}

export interface BatchUrl {
  url: string;
  status: "pending" | "processing" | "submitted" | "completed" | "failed";
  attempts: number;
}

export interface BatchStatus {
  batch_id: string;
  total: number;
  counts: Record<string, number>;
  done: boolean;
  urls: BatchUrl[];
}

export interface RecentBatch {
  batch_id: string;
  total: number;
  created_at: string | null;
}
