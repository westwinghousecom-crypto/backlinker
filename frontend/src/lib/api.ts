import { API_BASE_URL } from "@/lib/config";
import { logApiCall, logApiFailure } from "@/lib/logger";
import { announceSessionExpired, clearToken, getToken } from "@/lib/token";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    /** Machine-readable error code from the API (e.g. "google_reauth_required"), when it sent one. */
    public code?: string,
    /** The id the server logged this request under. Quote it when asking for help. */
    public requestId?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

const NOT_SIGNED_IN = "Your session has expired. Please sign in again.";

async function send(path: string, init: RequestInit | undefined, token: string): Promise<Response> {
  try {
    return await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
    });
  } catch {
    throw new ApiError("Could not reach the server. Please try again.", 0);
  }
}

const REFERENCE = (id?: string) => (id ? ` (reference ${id})` : "");

/** Sends an authenticated request, refreshing an expired token once. Returns the raw response. */
async function authedFetch(path: string, init?: RequestInit): Promise<Response> {
  let token: string;
  try {
    token = await getToken();
  } catch {
    announceSessionExpired();
    throw new ApiError(NOT_SIGNED_IN, 401);
  }

  let res = await send(path, init, token);
  if (res.status === 401) {
    // The short-lived token may simply have expired: get a fresh one and retry once.
    clearToken();
    try {
      token = await getToken({ force: true });
    } catch {
      announceSessionExpired();
      throw new ApiError(NOT_SIGNED_IN, 401);
    }
    res = await send(path, init, token);
    if (res.status === 401) {
      announceSessionExpired();
      throw new ApiError(NOT_SIGNED_IN, 401);
    }
  }
  return res;
}

async function errorFrom(res: Response): Promise<ApiError> {
  let message = `Request failed (${res.status})`;
  let code: string | undefined;
  try {
    const body = await res.json();
    if (typeof body?.detail === "string") message = body.detail;
    else if (body?.detail && typeof body.detail === "object" && !Array.isArray(body.detail)) {
      if (typeof body.detail.message === "string") message = body.detail.message;
      if (typeof body.detail.code === "string") code = body.detail.code;
    } else if (Array.isArray(body?.detail) && body.detail[0]?.msg)
      message = String(body.detail[0].msg).replace(/^Value error, /, "");
    else if (typeof body?.message === "string") message = body.message;
  } catch {
    // non-JSON error body
  }
  const requestId = res.headers.get("X-Request-ID") ?? undefined;
  // For server-side trouble, give the customer something to quote; the same id is on the backend log line.
  return new ApiError(res.status >= 500 ? message + REFERENCE(requestId) : message, res.status, code, requestId);
}

/** Sends the request and logs the outcome to the browser console. Throws an ApiError for anything but a success. */
async function tracked(path: string, init?: RequestInit): Promise<Response> {
  const method = init?.method ?? "GET";
  const started = performance.now();
  let res: Response;
  try {
    res = await authedFetch(path, init);
  } catch (e) {
    if (e instanceof ApiError) {
      logApiFailure({ method, path, status: e.status, code: e.code, message: e.message, ms: performance.now() - started });
    }
    throw e;
  }
  const ms = performance.now() - started;
  if (!res.ok) {
    const err = await errorFrom(res);
    logApiFailure({ method, path, status: err.status, code: err.code, message: err.message, requestId: err.requestId, ms });
    throw err;
  }
  logApiCall(method, path, res.status, ms);
  return res;
}

/** Authenticated call to the QuickIndex API. The customer is identified by the token, never by a field we send. */
export async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await tracked(path, init);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/** Authenticated download of a non-JSON body (e.g. an XML feed). */
export async function requestText(path: string): Promise<string> {
  return (await tracked(path)).text();
}
