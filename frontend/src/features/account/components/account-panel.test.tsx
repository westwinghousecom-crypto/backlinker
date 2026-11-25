import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/token", () => ({
  getToken: vi.fn(async () => "test-jwt"),
  clearToken: vi.fn(),
  announceSessionExpired: vi.fn(),
  SESSION_EXPIRED_EVENT: "quickindex:session-expired",
}));

const logout = vi.fn(async () => {});
const replace = vi.fn();
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ user: { id: "u1", email: "me@example.com" }, logout }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
const downloadFile = vi.fn();
vi.mock("@/lib/download", () => ({ downloadFile: (...a: unknown[]) => downloadFile(...a) }));

import { AccountPanel } from "./account-panel";

type Call = { method: string; url: string; auth: string | undefined; body: unknown };
let calls: Call[] = [];

function api(handler: (c: Call) => { status?: number; body?: unknown; text?: string }) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init: RequestInit = {}) => {
      const call: Call = {
        method: init.method ?? "GET",
        url: url.replace("http://localhost:8000", ""),
        auth: (init.headers as Record<string, string> | undefined)?.Authorization,
        body: init.body ? JSON.parse(String(init.body)) : undefined,
      };
      calls.push(call);
      const r = handler(call);
      const status = r.status ?? 200;
      if (status === 204) return new Response(null, { status });
      return new Response(r.text ?? JSON.stringify(r.body ?? {}), { status });
    }),
  );
}

beforeEach(() => {
  logout.mockClear();
  replace.mockClear();
  downloadFile.mockClear();
});
afterEach(() => vi.unstubAllGlobals());

describe("export my data", () => {
  it("fetches the export with the sign-in token and downloads it as a dated JSON file", async () => {
    api(() => ({ text: '{"account":{"id":"u1"},"urls":[]}' }));
    render(<AccountPanel />);
    await userEvent.click(screen.getByRole("button", { name: "Export my data" }));
    await waitFor(() => expect(downloadFile).toHaveBeenCalledTimes(1));
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({ method: "GET", url: "/api/v1/account/export", auth: "Bearer test-jwt" });
    const [name, text] = downloadFile.mock.calls[0];
    expect(name).toMatch(/^quickindex-export-\d{8}\.json$/);
    expect(JSON.parse(text as string).account.id).toBe("u1");
    expect(await screen.findByText(/Your data was downloaded/)).toBeInTheDocument();
  });

  it("shows the server's message (for example the 3-per-hour limit) and downloads nothing", async () => {
    api(() => ({ status: 429, body: { detail: "You can export your data 3 times per hour. Please try again later." } }));
    render(<AccountPanel />);
    await userEvent.click(screen.getByRole("button", { name: "Export my data" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(/3 times per hour/);
    expect(downloadFile).not.toHaveBeenCalled();
  });
});

describe("delete Google data", () => {
  it("asks first, then calls the Google data endpoint", async () => {
    api(() => ({ status: 204 }));
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<AccountPanel />);
    await userEvent.click(screen.getByRole("button", { name: "Delete Google data" }));
    expect(confirm).toHaveBeenCalled();
    expect(calls).toHaveLength(0);
    confirm.mockReturnValue(true);
    await userEvent.click(screen.getByRole("button", { name: "Delete Google data" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toMatchObject({ method: "DELETE", url: "/api/v1/google/data", auth: "Bearer test-jwt" });
    expect(await screen.findByText(/Google data was deleted/)).toBeInTheDocument();
  });
});

describe("delete account", () => {
  it("stays disabled until DELETE is typed exactly (capitals)", async () => {
    api(() => ({ status: 204 }));
    render(<AccountPanel />);
    const button = screen.getByRole("button", { name: "Delete my account" });
    const input = screen.getByLabelText(/Type/);
    expect(button).toBeDisabled();
    for (const wrong of ["delete", "DELET", "DELETE ", "yes"]) {
      await userEvent.clear(input);
      await userEvent.type(input, wrong);
      expect(button).toBeDisabled();
    }
    await userEvent.clear(input);
    await userEvent.type(input, "DELETE");
    expect(button).toBeEnabled();
    expect(calls).toHaveLength(0);
  });

  it("calls the endpoint once with no user id, then signs out and goes to the goodbye page", async () => {
    api(() => ({ status: 204 }));
    render(<AccountPanel />);
    await userEvent.type(screen.getByLabelText(/Type/), "DELETE");
    await userEvent.click(screen.getByRole("button", { name: "Delete my account" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/goodbye"));
    expect(calls).toHaveLength(1);
    expect(calls[0]).toMatchObject({ method: "DELETE", url: "/api/v1/account", auth: "Bearer test-jwt", body: { confirm: "DELETE" } });
    expect(Object.keys(calls[0].body as object)).toEqual(["confirm"]); // the customer is identified by the token alone
    expect(logout).toHaveBeenCalledTimes(1);
    expect(logout.mock.invocationCallOrder[0]).toBeLessThan(replace.mock.invocationCallOrder[0]);
  });

  it("explains what will be erased", () => {
    api(() => ({ status: 204 }));
    render(<AccountPanel />);
    expect(screen.getByText(/Permanently erases your submissions, backlink checks and results/)).toBeInTheDocument();
    expect(screen.getByText(/Encrypted backups may keep a copy until they expire/)).toBeInTheDocument();
  });

  it("when deletion fails it shows the error, does not sign out, and lets the customer retry", async () => {
    api(() => ({ status: 502, body: { detail: "Deleting your account did not finish. Please try again." } }));
    render(<AccountPanel />);
    await userEvent.type(screen.getByLabelText(/Type/), "DELETE");
    await userEvent.click(screen.getByRole("button", { name: "Delete my account" }));
    expect(await screen.findByText(/did not finish/)).toBeInTheDocument();
    expect(logout).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Delete my account" })).toBeEnabled();
  });
});

describe("page content", () => {
  it("shows who is signed in and links to the privacy policy and terms", () => {
    api(() => ({}));
    render(<AccountPanel />);
    expect(screen.getByText("me@example.com")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Privacy Policy" })).toHaveAttribute("href", "/privacy");
    expect(screen.getByRole("link", { name: "Terms" })).toHaveAttribute("href", "/terms");
  });
});
