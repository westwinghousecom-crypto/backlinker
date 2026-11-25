/** Turn Appwrite's technical sign-in errors into messages a customer can act on. */
const MESSAGES: Record<string, string> = {
  user_invalid_credentials: "Incorrect email or password.",
  user_not_found: "Incorrect email or password.", // do not reveal whether the email exists
  // Deliberately neutral: do not reveal whether an address already has an account.
  user_already_exists:
    "We could not create that account. If you already have one, sign in or reset your password.",
  user_blocked: "This account has been disabled. Contact support.",
  general_rate_limit_exceeded: "Too many attempts. Please wait a minute and try again.",
  user_password_personal_data: "Choose a password that does not contain your email or name.",
  password_personal_data: "Choose a password that does not contain your email or name.",
  password_recently_used: "Choose a password you have not used before.",
  user_invalid_password: "Password must be 8 to 256 characters.",
  general_argument_invalid: "Please check your details and try again.",
  user_session_already_exists: "You are already signed in.",
};

export function authMessage(e: unknown): string {
  const type = (e as { type?: string } | null)?.type;
  if (type && MESSAGES[type]) return MESSAGES[type];
  const code = (e as { code?: number } | null)?.code;
  if (code === 429) return MESSAGES.general_rate_limit_exceeded;
  if (code === 0 || (e instanceof TypeError)) return "Could not reach the sign-in service. Check your connection.";
  return "Something went wrong. Please try again.";
}

/** Only allow same-site relative paths after sign-in (prevents open redirects). */
export function safeNext(next: string | null | undefined, fallback = "/dashboard"): string {
  if (!next || !next.startsWith("/") || next.startsWith("//") || next.startsWith("/\\")) return fallback;
  return next;
}

export const RESET_LINK_INVALID = "This reset link is invalid or has expired. Request a new one.";

/** Messages for completing a password reset (the customer followed the emailed link). */
export function resetMessage(e: unknown): string {
  const type = (e as { type?: string } | null)?.type;
  const code = (e as { code?: number } | null)?.code;
  if (code === 429 || type === "general_rate_limit_exceeded") return MESSAGES.general_rate_limit_exceeded;
  if (type === "password_personal_data" || type === "user_password_personal_data") return MESSAGES.password_personal_data;
  if (type === "password_recently_used") return MESSAGES.password_recently_used;
  if (type === "user_invalid_password" || type === "password_invalid") return MESSAGES.user_invalid_password;
  if (code === 0 || e instanceof TypeError) return "Could not reach the sign-in service. Check your connection.";
  return RESET_LINK_INVALID; // invalid / expired / already used secret, unknown user, anything else
}

export const VERIFY_LINK_INVALID =
  "We could not verify your email. The link may have expired, or you may need to sign in first.";

export function verifyMessage(e: unknown): string {
  const code = (e as { code?: number } | null)?.code;
  if (code === 429) return MESSAGES.general_rate_limit_exceeded;
  if (code === 0 || e instanceof TypeError) return "Could not reach the sign-in service. Check your connection.";
  return VERIFY_LINK_INVALID;
}
