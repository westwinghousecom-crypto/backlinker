import { API_BASE_URL } from "@/lib/config";

export const RECOVERY_NEUTRAL_MESSAGE =
  "If an account exists for that address, we have sent instructions to it.";

export class RecoveryError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
    this.name = "RecoveryError";
  }
}

/**
 * Ask for a password-recovery email. This endpoint is PUBLIC (the customer is signed out), so NO token is sent.
 * The server answers 202 whether or not the address has an account; we never read the body on success, so the
 * screen cannot differ between the two cases.
 */
export async function requestRecovery(email: string): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}/api/v1/account/recovery`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
    });
  } catch {
    throw new RecoveryError("Could not reach the server. Please try again.", 0);
  }
  if (res.status === 202) return;
  if (res.status === 429) {
    throw new RecoveryError("Too many requests. Please try again later.", 429);
  }
  if (res.status === 422) {
    let message = "Enter a valid email address.";
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") message = body.detail;
      else if (Array.isArray(body?.detail) && body.detail[0]?.msg)
        message = String(body.detail[0].msg).replace(/^Value error, /, "");
    } catch {
      // keep the default
    }
    throw new RecoveryError(message, 422);
  }
  throw new RecoveryError("Something went wrong. Please try again.", res.status);
}

import { request } from "@/lib/api";

/** Permanently delete the signed-in customer's account and data. The server identifies the customer by the sign-in token. */
export function deleteAccount(): Promise<void> {
  return request<void>("/api/v1/account", { method: "DELETE", body: JSON.stringify({ confirm: "DELETE" }) });
}
