/** Browser-console logging. Everything here is safe to read aloud: it never includes tokens, headers, request bodies or
 *  query strings (those can hold secrets or customers' URLs). Pair the `ref` with the same id in the backend terminal. */

const PREFIX = "[QuickIndex]";

/** The path only: no query string and no fragment. */
export function safePath(path: string): string {
  return path.split(/[?#]/)[0];
}

export interface ApiFailure {
  method: string;
  path: string;
  /** 0 means the server could not be reached at all. */
  status: number;
  code?: string;
  message: string;
  requestId?: string | null;
  ms: number;
}

export function logApiFailure(f: ApiFailure): void {
  const line = `${PREFIX} ${f.method} ${safePath(f.path)} -> ${f.status === 0 ? "no response" : f.status} in ${Math.round(f.ms)}ms`;
  const detail = {
    status: f.status,
    ...(f.code ? { code: f.code } : {}),
    message: f.message,
    ...(f.requestId ? { ref: f.requestId } : {}),
  };
  // Server trouble and unreachable servers are errors; a refusal like "not found" or "reconnect Google" is a warning.
  if (f.status === 0 || f.status >= 500) console.error(line, detail);
  else console.warn(line, detail);
}

/** Successful calls are only logged while developing, to keep a real customer's console quiet. */
export function logApiCall(method: string, path: string, status: number, ms: number): void {
  if (process.env.NODE_ENV === "production") return;
  console.debug(`${PREFIX} ${method} ${safePath(path)} -> ${status} in ${Math.round(ms)}ms`);
}

/** An unexpected error from the page itself (a crash, a failed promise). */
export function logClientError(scope: string, error: unknown, extra?: Record<string, string | number | undefined>): void {
  const e = error instanceof Error ? error : new Error(typeof error === "string" ? error : "Unknown error");
  console.error(`${PREFIX} ${scope}: ${e.name}: ${e.message}`, { ...extra, stack: e.stack });
}
