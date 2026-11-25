import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/token", () => ({
  getToken: vi.fn(async () => "SECRET-JWT-VALUE"),
  clearToken: vi.fn(),
  announceSessionExpired: vi.fn(),
  SESSION_EXPIRED_EVENT: "quickindex:session-expired",
}));

import { ErrorLogger } from "@/components/error-logger";
import { ErrorScreen } from "@/components/error-screen";
import { ApiError, request } from "@/lib/api";
import { logApiFailure, safePath } from "@/lib/logger";

let error: ReturnType<typeof vi.spyOn>;
let warn: ReturnType<typeof vi.spyOn>;
let debug: ReturnType<typeof vi.spyOn>;
const dump = (spy: ReturnType<typeof vi.spyOn>) => JSON.stringify(spy.mock.calls);

function respond(status: number, body: unknown, headers: Record<string, string> = {}) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(status === 204 ? null : JSON.stringify(body), { status, headers })));
}

beforeEach(() => {
  error = vi.spyOn(console, "error").mockImplementation(() => {});
  warn = vi.spyOn(console, "warn").mockImplementation(() => {});
  debug = vi.spyOn(console, "debug").mockImplementation(() => {});
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("logger", () => {
  it("strips the query string and fragment from any path it prints", () => {
    expect(safePath("/api/v1/x?code=ABC&state=DEF#frag")).toBe("/api/v1/x");
    expect(safePath("/api/v1/y")).toBe("/api/v1/y");
  });

  it("logs refusals as warnings and server trouble or an unreachable server as errors", () => {
    logApiFailure({ method: "GET", path: "/a", status: 404, message: "Not found", ms: 5 });
    expect(warn).toHaveBeenCalledTimes(1);
    expect(error).not.toHaveBeenCalled();
    logApiFailure({ method: "GET", path: "/a", status: 502, message: "Database error", requestId: "abc123def456", ms: 5 });
    logApiFailure({ method: "GET", path: "/a", status: 0, message: "Could not reach the server.", ms: 5 });
    expect(error).toHaveBeenCalledTimes(2);
    expect(error.mock.calls[0][0]).toContain("[QuickIndex] GET /a -> 502");
    expect(error.mock.calls[0][1]).toMatchObject({ ref: "abc123def456" });
    expect(error.mock.calls[1][0]).toContain("no response");
  });
});

describe("API call logging", () => {
  it("logs a failed call with status, code and the server's reference, never the token, body or query", async () => {
    respond(409, { detail: { code: "google_reauth_required", message: "Google access was revoked." } }, { "X-Request-ID": "req123456789" });
    await expect(
      request("/api/v1/google/targets?code=OAUTHCODE&url=https://private.example/page", {
        method: "POST",
        body: JSON.stringify({ urls: ["https://private.example/page"] }),
      }),
    ).rejects.toMatchObject({ status: 409, code: "google_reauth_required", requestId: "req123456789" });
    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn.mock.calls[0][0]).toContain("[QuickIndex] POST /api/v1/google/targets -> 409");
    expect(warn.mock.calls[0][1]).toMatchObject({ status: 409, code: "google_reauth_required", ref: "req123456789" });
    const everything = dump(warn) + dump(error) + dump(debug);
    for (const secret of ["SECRET-JWT-VALUE", "OAUTHCODE", "private.example", "Bearer"]) expect(everything).not.toContain(secret);
  });

  it("gives the customer a reference to quote on server errors (same id as the backend log line)", async () => {
    respond(502, { detail: "Database error: boom" }, { "X-Request-ID": "req987654321" });
    const err = await request("/api/v1/batches").catch((e: ApiError) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).message).toBe("Database error: boom (reference req987654321)");
    expect((err as ApiError).requestId).toBe("req987654321");
    expect(error).toHaveBeenCalledTimes(1);
  });

  it("leaves messages alone when there is no reference, or for ordinary refusals", async () => {
    respond(500, { detail: "oops" });
    expect(((await request("/x").catch((e) => e)) as ApiError).message).toBe("oops");
    respond(404, { detail: "Batch not found" }, { "X-Request-ID": "req111111111" });
    expect(((await request("/x").catch((e) => e)) as ApiError).message).toBe("Batch not found");
  });

  it("logs an unreachable server as an error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    await expect(request("/api/v1/batches")).rejects.toMatchObject({ status: 0 });
    expect(error).toHaveBeenCalledTimes(1);
    expect(error.mock.calls[0][0]).toContain("no response");
  });

  it("logs a successful call only as a quiet debug line while developing, and nothing at warning or error level", async () => {
    respond(200, { ok: true });
    await request("/api/v1/batches?limit=20");
    expect(debug).toHaveBeenCalledTimes(1);
    expect(debug.mock.calls[0][0]).toMatch(/^\[QuickIndex\] GET \/api\/v1\/batches -> 200 in \d+ms$/);
    expect(warn).not.toHaveBeenCalled();
    expect(error).not.toHaveBeenCalled();
  });

  it("stays silent about successful calls in production", async () => {
    vi.stubEnv("NODE_ENV", "production");
    respond(200, { ok: true });
    await request("/api/v1/batches");
    expect(debug).not.toHaveBeenCalled();
    vi.unstubAllEnvs();
  });
});

describe("crash handling", () => {
  it("shows a plain message, logs the details to the console only, and lets the customer retry", async () => {
    const retry = vi.fn();
    const boom = Object.assign(new Error("secret internal detail"), { digest: "d1g3st" });
    render(<ErrorScreen error={boom} retry={retry} scope="page crashed" />);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Something went wrong");
    expect(alert).toHaveTextContent("quote reference d1g3st");
    expect(alert).not.toHaveTextContent("secret internal detail"); // the customer never sees the raw error
    expect(error.mock.calls[0][0]).toContain("[QuickIndex] page crashed: Error: secret internal detail");
    expect(error.mock.calls[0][1]).toMatchObject({ digest: "d1g3st" });
    await userEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("copes with a thrown value that is not an Error", () => {
    render(<ErrorScreen error={"just a string"} retry={() => {}} scope="page crashed" />);
    expect(screen.getByRole("alert")).not.toHaveTextContent("reference");
    expect(error.mock.calls[0][0]).toContain("just a string");
  });

  it("logs uncaught errors and unhandled promise failures from anywhere in the page", () => {
    const { unmount } = render(<ErrorLogger />);
    act(() => {
      window.dispatchEvent(new ErrorEvent("error", { error: new Error("kaboom"), message: "kaboom" }));
      const rejection = new Event("unhandledrejection") as Event & { reason: unknown };
      rejection.reason = new Error("promise failed");
      window.dispatchEvent(rejection);
    });
    expect(error.mock.calls.map((c) => c[0])).toEqual([
      "[QuickIndex] uncaught error: Error: kaboom",
      "[QuickIndex] unhandled promise rejection: Error: promise failed",
    ]);
    unmount();
    error.mockClear();
    window.dispatchEvent(new ErrorEvent("error", { error: new Error("after unmount") }));
    expect(error).not.toHaveBeenCalled(); // listeners removed
  });
});
