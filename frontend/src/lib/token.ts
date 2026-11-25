import { account } from "@/lib/appwrite";

/** Appwrite JWTs live 15 minutes; refresh a little early. */
const REFRESH_AFTER_MS = 10 * 60 * 1000;

export const SESSION_EXPIRED_EVENT = "quickindex:session-expired";

let cached: { token: string; fetchedAt: number } | null = null;
let inflight: Promise<string> | null = null;

export function clearToken(): void {
  cached = null;
  inflight = null;
}

/** A short-lived token proving who the signed-in customer is. The API verifies it with Appwrite. */
export async function getToken(opts: { force?: boolean } = {}): Promise<string> {
  if (!opts.force && cached && Date.now() - cached.fetchedAt < REFRESH_AFTER_MS) {
    return cached.token;
  }
  if (!inflight) {
    inflight = account
      .createJWT()
      .then((jwt) => {
        cached = { token: jwt.jwt, fetchedAt: Date.now() };
        return jwt.jwt;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

export function announceSessionExpired(): void {
  clearToken();
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT));
  }
}
