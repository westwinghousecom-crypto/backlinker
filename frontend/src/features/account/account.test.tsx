import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const account = vi.hoisted(() => ({
  get: vi.fn(),
  updateRecovery: vi.fn(),
  updateVerification: vi.fn(),
  createJWT: vi.fn(),
}));
vi.mock("@/lib/appwrite", () => ({ account, ID: { unique: () => "id" } }));
vi.mock("@/lib/token", () => ({
  getToken: vi.fn(async () => "test-jwt"),
  clearToken: vi.fn(),
  announceSessionExpired: vi.fn(),
  SESSION_EXPIRED_EVENT: "quickindex:session-expired",
}));

let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(search),
}));

import { UnverifiedBanner } from "@/components/unverified-banner";
import { AuthProvider } from "@/lib/auth";
import { RESET_LINK_INVALID, VERIFY_LINK_INVALID } from "@/lib/auth-errors";
import { RECOVERY_NEUTRAL_MESSAGE } from "./api";
import { ForgotPasswordForm } from "./components/forgot-password-form";
import { ResetPasswordForm } from "./components/reset-password-form";
import { VerifyEmailView } from "./components/verify-email-view";

type Call = { url: string; init?: RequestInit };
let calls: Call[] = [];
function stubFetch(handler: (c: Call) => { status: number; body?: unknown }) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const c = { url, init };
      calls.push(c);
      const { status, body } = handler(c);
      return new Response(status === 204 ? null : JSON.stringify(body ?? {}), { status });
    }),
  );
}
const headersOf = (c: Call) => (c.init?.headers ?? {}) as Record<string, string>;

beforeEach(() => {
  vi.clearAllMocks();
  search = "";
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("forgot password", () => {
  async function submit(email = "someone@example.com") {
    await userEvent.type(screen.getByLabelText("Email"), email);
    await userEvent.click(screen.getByRole("button", { name: "Send reset link" }));
  }

  it("shows the same neutral message and sends NO token", async () => {
    stubFetch(() => ({ status: 202, body: { message: "If an account exists for that address, we have sent instructions to it." } }));
    render(<ForgotPasswordForm />);
    await submit();
    expect(await screen.findByText(RECOVERY_NEUTRAL_MESSAGE)).toBeInTheDocument();
    expect(calls[0].url).toMatch(/\/api\/v1\/account\/recovery$/);
    expect(headersOf(calls[0]).Authorization).toBeUndefined();
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ email: "someone@example.com" });
  });

  it("shows identical text whatever the server body says (nothing reveals whether the account exists)", async () => {
    const seen: string[] = [];
    for (const body of [{ message: "sent to a real account" }, { message: "no such account", exists: false }, {}]) {
      stubFetch(() => ({ status: 202, body }));
      const { unmount } = render(<ForgotPasswordForm />);
      await submit();
      await screen.findByText(RECOVERY_NEUTRAL_MESSAGE);
      seen.push(screen.getByRole("status").textContent ?? "");
      unmount();
    }
    expect(new Set(seen).size).toBe(1);
    expect(seen[0]).not.toMatch(/real account|no such/i);
  });

  it("handles rate limiting and invalid input without claiming success", async () => {
    stubFetch(() => ({ status: 429, body: { detail: "Too many requests. Please try again later." } }));
    render(<ForgotPasswordForm />);
    await submit();
    expect(await screen.findByText("Too many requests. Please try again later.")).toBeInTheDocument();
    expect(screen.queryByText(RECOVERY_NEUTRAL_MESSAGE)).not.toBeInTheDocument();
  });

  it("shows the server's message for an invalid address", async () => {
    stubFetch(() => ({ status: 422, body: { detail: "Enter a valid email address." } }));
    render(<ForgotPasswordForm />);
    await submit("a@b.co");
    expect(await screen.findByText("Enter a valid email address.")).toBeInTheDocument();
  });

  it("disables the button during a 60 second cooldown with a visible countdown, then re-enables it", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    stubFetch(() => ({ status: 202 }));
    render(<ForgotPasswordForm />);
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).type(screen.getByLabelText("Email"), "a@b.co");
    await userEvent.setup({ advanceTimers: vi.advanceTimersByTime }).click(screen.getByRole("button", { name: "Send reset link" }));
    const btn = await screen.findByRole("button", { name: /Send again in 60s/ });
    expect(btn).toBeDisabled();
    // The countdown ticks once per second; step through it so every state update is applied.
    for (let i = 0; i < 10; i++) await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(screen.getByRole("button", { name: /Send again in 50s/ })).toBeDisabled();
    for (let i = 0; i < 50; i++) await act(() => vi.advanceTimersByTimeAsync(1000));
    expect(screen.getByRole("button", { name: "Send again" })).toBeEnabled();
    expect(calls).toHaveLength(1);
  });
});

describe("reset password", () => {
  const link = "userId=u1&secret=s3cr3t-value&expire=2026-12-01";

  it("changes the password through Appwrite and offers sign-in", async () => {
    search = link;
    account.updateRecovery.mockResolvedValue({});
    const { container } = render(<ResetPasswordForm />);
    await userEvent.type(screen.getByLabelText("New password"), "brand-new-pass1");
    await userEvent.type(screen.getByLabelText("Confirm new password"), "brand-new-pass1");
    await userEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByText("Your password has been changed")).toBeInTheDocument();
    expect(account.updateRecovery).toHaveBeenCalledWith({ userId: "u1", secret: "s3cr3t-value", password: "brand-new-pass1" });
    expect(screen.getByRole("link", { name: "Go to sign in" })).toHaveAttribute("href", "/login");
    expect(container.innerHTML).not.toContain("s3cr3t-value");
  });

  it("never puts the secret in the page, even on the form", () => {
    search = link;
    const { container } = render(<ResetPasswordForm />);
    expect(container.innerHTML).not.toContain("s3cr3t-value");
    expect(container.textContent).not.toContain("s3cr3t-value");
  });

  it("rejects passwords that are short or do not match, without calling Appwrite", async () => {
    search = link;
    render(<ResetPasswordForm />);
    await userEvent.type(screen.getByLabelText("New password"), "short");
    await userEvent.type(screen.getByLabelText("Confirm new password"), "short");
    await userEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByText("Password must be at least 8 characters.")).toBeInTheDocument();

    await userEvent.clear(screen.getByLabelText("New password"));
    await userEvent.clear(screen.getByLabelText("Confirm new password"));
    await userEvent.type(screen.getByLabelText("New password"), "longenough1");
    await userEvent.type(screen.getByLabelText("Confirm new password"), "different-one");
    await userEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByText("The two passwords do not match.")).toBeInTheDocument();
    expect(account.updateRecovery).not.toHaveBeenCalled();
  });

  it("explains an invalid or expired link and offers a new one", async () => {
    search = link;
    account.updateRecovery.mockRejectedValue(Object.assign(new Error("x"), { type: "user_invalid_token", code: 401 }));
    render(<ResetPasswordForm />);
    await userEvent.type(screen.getByLabelText("New password"), "brand-new-pass1");
    await userEvent.type(screen.getByLabelText("Confirm new password"), "brand-new-pass1");
    await userEvent.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByText(RESET_LINK_INVALID, { exact: false })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Request a new link" })).toHaveAttribute("href", "/forgot-password");
  });

  it("shows the invalid-link message when the link has no userId/secret", () => {
    search = "userId=only-id";
    render(<ResetPasswordForm />);
    expect(screen.getByText(RESET_LINK_INVALID)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Request a new reset link" })).toHaveAttribute("href", "/forgot-password");
    expect(screen.queryByLabelText("New password")).not.toBeInTheDocument();
  });
});

describe("verify email", () => {
  it("shows verifying, then success", async () => {
    search = "userId=u1&secret=abc";
    let resolve!: () => void;
    account.updateVerification.mockReturnValue(new Promise<void>((r) => (resolve = r)));
    render(<VerifyEmailView />);
    expect(screen.getByText("Verifying your email address…")).toBeInTheDocument();
    resolve();
    expect(await screen.findByText("Email verified")).toBeInTheDocument();
    expect(account.updateVerification).toHaveBeenCalledWith({ userId: "u1", secret: "abc" });
  });

  it("explains a failure and points to sign-in and resending", async () => {
    search = "userId=u1&secret=abc";
    account.updateVerification.mockRejectedValue(Object.assign(new Error("x"), { code: 401 }));
    render(<VerifyEmailView />);
    expect(await screen.findByText(VERIFY_LINK_INVALID)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.getByText(/Resend verification email/)).toBeInTheDocument();
  });

  it("fails without calling Appwrite when the link is incomplete", () => {
    search = "";
    render(<VerifyEmailView />);
    expect(screen.getByText(VERIFY_LINK_INVALID)).toBeInTheDocument();
    expect(account.updateVerification).not.toHaveBeenCalled();
  });
});

describe("unverified banner", () => {
  const user = { $id: "u1", email: "a@example.com", name: "A" };

  it("shows for an unverified customer and hides for a verified one", async () => {
    account.get.mockResolvedValue({ ...user, emailVerification: false });
    const { unmount } = render(<AuthProvider><UnverifiedBanner /></AuthProvider>);
    expect(await screen.findByText("Please verify your email address.")).toBeInTheDocument();
    unmount();

    account.get.mockResolvedValue({ ...user, emailVerification: true });
    render(<AuthProvider><UnverifiedBanner /></AuthProvider>);
    await waitFor(() => expect(account.get).toHaveBeenCalledTimes(2));
    await act(async () => {});
    expect(screen.queryByText("Please verify your email address.")).not.toBeInTheDocument();
  });

  it("resends through the authenticated API and starts a cooldown", async () => {
    account.get.mockResolvedValue({ ...user, emailVerification: false });
    stubFetch(() => ({ status: 202, body: { message: "Verification email sent. Check your inbox.", already_verified: false } }));
    render(<AuthProvider><UnverifiedBanner /></AuthProvider>);
    await userEvent.click(await screen.findByRole("button", { name: "Resend verification email" }));
    expect(await screen.findByText("Verification email sent. Check your inbox.")).toBeInTheDocument();
    expect(calls[0].url).toMatch(/\/api\/v1\/account\/verification$/);
    expect(calls[0].init?.method).toBe("POST");
    expect(headersOf(calls[0]).Authorization).toBe("Bearer test-jwt");
    expect(screen.getByRole("button", { name: /Resend in 60s/ })).toBeDisabled();
  });

  it("hides itself when the server says the address is already verified", async () => {
    account.get.mockResolvedValue({ ...user, emailVerification: false });
    stubFetch(() => ({ status: 202, body: { message: "Your email address is already verified.", already_verified: true } }));
    render(<AuthProvider><UnverifiedBanner /></AuthProvider>);
    await userEvent.click(await screen.findByRole("button", { name: "Resend verification email" }));
    await waitFor(() => expect(screen.queryByText("Please verify your email address.")).not.toBeInTheDocument());
  });

  it("shows the server's cooldown/limit error", async () => {
    account.get.mockResolvedValue({ ...user, emailVerification: false });
    stubFetch(() => ({ status: 429, body: { detail: "Please wait 60 seconds before asking again." } }));
    render(<AuthProvider><UnverifiedBanner /></AuthProvider>);
    await userEvent.click(await screen.findByRole("button", { name: "Resend verification email" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Please wait 60 seconds before asking again.");
    expect(screen.getByRole("button", { name: "Resend verification email" })).toBeEnabled();
  });
});
