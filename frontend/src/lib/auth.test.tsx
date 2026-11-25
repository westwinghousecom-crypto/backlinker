import { act, render, renderHook, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const account = vi.hoisted(() => ({
  get: vi.fn(),
  create: vi.fn(),
  createEmailPasswordSession: vi.fn(),
  createJWT: vi.fn(),
  deleteSession: vi.fn(),
}));
vi.mock("@/lib/appwrite", () => ({ account, ID: { unique: () => "new-user-id" } }));

const replace = vi.fn();
let search = "";
let pathname = "/dashboard/backlinks";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => pathname,
  useSearchParams: () => new URLSearchParams(search),
}));

import { AuthForm } from "@/components/auth-form";
import { AuthGate } from "@/components/auth-gate";
import { ApiError, request } from "@/lib/api";
import { AuthProvider, useAuth } from "@/lib/auth";
import { authMessage, safeNext } from "@/lib/auth-errors";
import { clearToken, getToken, SESSION_EXPIRED_EVENT } from "@/lib/token";

const alice = { $id: "u-alice", email: "alice@example.com", name: "Alice" };
const wrapper = ({ children }: { children: ReactNode }) => <AuthProvider>{children}</AuthProvider>;

function appwriteError(type: string, code = 401) {
  return Object.assign(new Error(type), { type, code });
}

beforeEach(() => {
  vi.clearAllMocks();
  clearToken();
  search = "";
  pathname = "/dashboard/backlinks";
  account.createJWT.mockResolvedValue({ jwt: "jwt-1" });
});
afterEach(() => vi.unstubAllGlobals());

describe("AuthProvider", () => {
  it("starts signed out when Appwrite has no session", async () => {
    account.get.mockRejectedValue(appwriteError("general_unauthorized_scope"));
    const { result } = renderHook(() => useAuth(), { wrapper });
    expect(result.current.status).toBe("loading");
    await waitFor(() => expect(result.current.status).toBe("anonymous"));
    expect(result.current.user).toBeNull();
  });

  it("restores a saved session on reload", async () => {
    account.get.mockResolvedValue(alice);
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("authenticated"));
    expect(result.current.user).toEqual({ id: "u-alice", email: "alice@example.com", name: "Alice", emailVerified: false });
  });

  it("logs in, then logs out and drops the cached token", async () => {
    account.get.mockRejectedValueOnce(appwriteError("x")).mockResolvedValue(alice);
    account.createEmailPasswordSession.mockResolvedValue({});
    account.deleteSession.mockResolvedValue({});
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("anonymous"));

    await act(() => result.current.login("alice@example.com", "password123"));
    expect(account.createEmailPasswordSession).toHaveBeenCalledWith({ email: "alice@example.com", password: "password123" });
    expect(result.current.status).toBe("authenticated");

    await getToken(); // cache a token for this user
    await act(() => result.current.logout());
    expect(account.deleteSession).toHaveBeenCalledWith({ sessionId: "current" });
    expect(result.current.status).toBe("anonymous");
    await getToken();
    expect(account.createJWT).toHaveBeenCalledTimes(2); // the old user's token was not reused
  });

  it("shows a friendly message for a wrong password", async () => {
    account.get.mockRejectedValue(appwriteError("x"));
    account.createEmailPasswordSession.mockRejectedValue(appwriteError("user_invalid_credentials"));
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("anonymous"));
    await expect(result.current.login("a@b.co", "wrong-pass")).rejects.toThrow("Incorrect email or password.");
  });

  it("registers a new account and signs it in", async () => {
    account.get.mockRejectedValueOnce(appwriteError("x")).mockResolvedValue(alice);
    account.create.mockResolvedValue({});
    account.createEmailPasswordSession.mockResolvedValue({});
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("anonymous"));
    await act(() => result.current.register("Alice", "alice@example.com", "password123"));
    expect(account.create).toHaveBeenCalledWith({ userId: "new-user-id", email: "alice@example.com", password: "password123", name: "Alice" });
    expect(result.current.status).toBe("authenticated");
  });

  it("signs out everywhere in the UI when the API says the session expired", async () => {
    account.get.mockResolvedValue(alice);
    const { result } = renderHook(() => useAuth(), { wrapper });
    await waitFor(() => expect(result.current.status).toBe("authenticated"));
    act(() => window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT)));
    expect(result.current.status).toBe("anonymous");
  });
});

describe("request() against the API", () => {
  function stubFetch(...statuses: number[]) {
    const seen: { auth: string | null }[] = [];
    let i = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init: RequestInit) => {
        seen.push({ auth: (init.headers as Record<string, string>).Authorization });
        const status = statuses[Math.min(i++, statuses.length - 1)];
        return new Response(status === 204 ? null : JSON.stringify(status === 200 ? { ok: true } : { detail: "nope" }), { status });
      }),
    );
    return seen;
  }

  it("sends the signed-in token and never a user id", async () => {
    const seen = stubFetch(200);
    await expect(request("/api/v1/check-batches")).resolves.toEqual({ ok: true });
    expect(seen[0].auth).toBe("Bearer jwt-1");
    expect((fetch as ReturnType<typeof vi.fn>).mock.calls[0][0]).not.toMatch(/user_id/);
  });

  it("reuses the cached token between calls", async () => {
    stubFetch(200);
    await request("/a");
    await request("/b");
    expect(account.createJWT).toHaveBeenCalledTimes(1);
  });

  it("gets a fresh token and retries once when the token has expired", async () => {
    account.createJWT.mockResolvedValueOnce({ jwt: "old" }).mockResolvedValueOnce({ jwt: "fresh" });
    const seen = stubFetch(401, 200);
    await expect(request("/api/v1/check-batches")).resolves.toEqual({ ok: true });
    expect(seen.map((s) => s.auth)).toEqual(["Bearer old", "Bearer fresh"]);
  });

  it("signs the customer out when a fresh token is still refused", async () => {
    const expired = vi.fn();
    window.addEventListener(SESSION_EXPIRED_EVENT, expired);
    stubFetch(401, 401);
    await expect(request("/x")).rejects.toMatchObject({ status: 401, message: expect.stringContaining("sign in again") });
    expect(expired).toHaveBeenCalled();
    window.removeEventListener(SESSION_EXPIRED_EVENT, expired);
  });

  it("does not call the API at all without a session", async () => {
    account.createJWT.mockRejectedValue(appwriteError("general_unauthorized_scope"));
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    await expect(request("/x")).rejects.toBeInstanceOf(ApiError);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("reports network failures and server error messages plainly", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("fetch failed"); }));
    await expect(request("/x")).rejects.toThrow("Could not reach the server");
    stubFetch(404);
    await expect(request("/x")).rejects.toMatchObject({ status: 404, message: "nope" });
  });
});

describe("AuthGate", () => {
  it("redirects signed-out visitors to /login, remembering where they were going", async () => {
    account.get.mockRejectedValue(appwriteError("x"));
    search = "batch=abc";
    render(<AuthProvider><AuthGate><p>secret page</p></AuthGate></AuthProvider>);
    expect(screen.queryByText("secret page")).not.toBeInTheDocument();
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login?next=%2Fdashboard%2Fbacklinks%3Fbatch%3Dabc"));
    expect(screen.queryByText("secret page")).not.toBeInTheDocument();
  });

  it("shows the page to a signed-in customer", async () => {
    account.get.mockResolvedValue(alice);
    render(<AuthProvider><AuthGate><p>secret page</p></AuthGate></AuthProvider>);
    expect(await screen.findByText("secret page")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });
});

describe("AuthForm", () => {
  it("signs in and goes to the page the customer wanted", async () => {
    account.get.mockRejectedValueOnce(appwriteError("x")).mockResolvedValue(alice);
    account.createEmailPasswordSession.mockResolvedValue({});
    search = "next=%2Fdashboard%2Fbacklinks%3Fbatch%3Dabc";
    render(<AuthProvider><AuthForm mode="login" /></AuthProvider>);
    await userEvent.type(await screen.findByLabelText("Email"), "alice@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "password123");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard/backlinks?batch=abc"));
  });

  it("shows the error and stays on the page when sign-in fails", async () => {
    account.get.mockRejectedValue(appwriteError("x"));
    account.createEmailPasswordSession.mockRejectedValue(appwriteError("user_invalid_credentials"));
    render(<AuthProvider><AuthForm mode="login" /></AuthProvider>);
    await userEvent.type(await screen.findByLabelText("Email"), "a@b.co");
    await userEvent.type(screen.getByLabelText("Password"), "wrongpass1");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Incorrect email or password.")).toBeInTheDocument();
    expect(replace).not.toHaveBeenCalled();
  });

  it("rejects a short password on sign-up before calling Appwrite", async () => {
    account.get.mockRejectedValue(appwriteError("x"));
    render(<AuthProvider><AuthForm mode="register" /></AuthProvider>);
    await userEvent.type(await screen.findByLabelText("Email"), "new@b.co");
    await userEvent.type(screen.getByLabelText(/Password/), "short");
    await userEvent.click(screen.getByRole("button", { name: "Create account" }));
    expect(await screen.findByText("Password must be at least 8 characters.")).toBeInTheDocument();
    expect(account.create).not.toHaveBeenCalled();
  });
});

describe("helpers", () => {
  it("only allows same-site redirects after sign-in", () => {
    expect(safeNext("/dashboard/backlinks?batch=1")).toBe("/dashboard/backlinks?batch=1");
    for (const bad of ["https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)", "", null, undefined]) {
      expect(safeNext(bad)).toBe("/dashboard");
    }
  });

  it("maps Appwrite errors to plain messages without leaking whether an email exists", () => {
    expect(authMessage(appwriteError("user_invalid_credentials"))).toBe("Incorrect email or password.");
    expect(authMessage(appwriteError("user_not_found"))).toBe("Incorrect email or password.");
    expect(authMessage(appwriteError("user_already_exists", 409))).toBe(
      "We could not create that account. If you already have one, sign in or reset your password.",
    );
    expect(authMessage({ code: 429 })).toContain("Too many attempts");
    expect(authMessage(new Error("weird internal text"))).toBe("Something went wrong. Please try again.");
  });
});
