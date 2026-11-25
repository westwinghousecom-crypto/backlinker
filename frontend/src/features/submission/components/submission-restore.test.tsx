import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/dashboard",
  useSearchParams: () => new URLSearchParams(search),
}));
vi.mock("@/lib/token", () => ({
  getToken: vi.fn(async () => "jwt"),
  clearToken: vi.fn(),
  announceSessionExpired: vi.fn(),
  SESSION_EXPIRED_EVENT: "quickindex:session-expired",
}));
// The progress panel has its own tests; here we only care WHICH batch it is asked to show.
vi.mock("./batch-status", () => ({ BatchStatusPanel: ({ batchId }: { batchId: string }) => <div data-testid="panel">{batchId}</div> }));

import { SubmissionForm } from "./submission-form";

let calls: { url: string; method: string }[] = [];
function api(recent: unknown[] | "error" = [], submit?: { batch_id: string; total: number }) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.replace(/^https?:\/\/[^/]+/, "");
      calls.push({ url: path, method: init?.method ?? "GET" });
      if (path === "/api/v1/batches") {
        return recent === "error" ? new Response("{}", { status: 502 }) : new Response(JSON.stringify(recent), { status: 200 });
      }
      if (path.startsWith("/api/v1/submit")) return new Response(JSON.stringify(submit), { status: 200 });
      return new Response("{}", { status: 404 });
    }),
  );
}

beforeEach(() => {
  search = "";
  replace.mockClear();
});
afterEach(() => vi.unstubAllGlobals());

describe("Submit page remembers batches (from the database, not the browser)", () => {
  it("reopens the batch named in the address (?batch=...) after a reload", async () => {
    api([]);
    search = "batch=ee8d5662-ebdd-4087-8820-18065818a05a";
    render(<SubmissionForm />);
    expect(screen.getByText("Earlier submission")).toBeInTheDocument();
    expect(screen.getByTestId("panel")).toHaveTextContent("ee8d5662-ebdd-4087-8820-18065818a05a");
    expect(screen.getByText(/Reopened from your earlier submission/)).toBeInTheDocument();
  });

  it("lists the customer's earlier batches from the API and links each to its own batch", async () => {
    api([
      { batch_id: "old-2", total: 1, created_at: "2026-11-11T10:00:00.000+00:00" },
      { batch_id: "old-1", total: 3, created_at: "2026-11-10T10:00:00.000+00:00" },
    ]);
    search = "batch=old-1";
    render(<SubmissionForm />);
    const nav = await screen.findByRole("navigation", { name: "Recent submissions" });
    const links = Array.from(nav.querySelectorAll("a")).map((a) => a.getAttribute("href"));
    expect(links).toEqual(["/dashboard?batch=old-2", "/dashboard?batch=old-1"]);
    expect(nav).toHaveTextContent("1 URL");
    expect(nav).toHaveTextContent("3 URLs");
    expect(nav.querySelector('a[aria-current="true"]')).toHaveAttribute("href", "/dashboard?batch=old-1");
    expect(calls.find((c) => c.url === "/api/v1/batches")).toBeTruthy(); // authenticated GET, no user id anywhere in the path
    expect(calls.some((c) => /user/i.test(c.url))).toBe(false);
  });

  it("puts the new batch in the address after submitting and refreshes the list", async () => {
    api([{ batch_id: "new-batch", total: 2, created_at: "2026-11-11T12:00:00.000+00:00" }], { batch_id: "new-batch", total: 2 });
    render(<SubmissionForm />);
    await userEvent.click(screen.getByRole("textbox"));
    await userEvent.paste("https://a.example/1\nhttps://b.example/2");
    await userEvent.click(screen.getByRole("button", { name: "Submit for Fast Indexing" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard?batch=new-batch"));
    expect(calls.some((c) => c.url.startsWith("/api/v1/submit"))).toBe(true);
  });

  it("shows no list for a customer with no earlier submissions", async () => {
    api([]);
    render(<SubmissionForm />);
    await waitFor(() => expect(calls.some((c) => c.url === "/api/v1/batches")).toBe(true));
    expect(screen.queryByRole("navigation", { name: "Recent submissions" })).not.toBeInTheDocument();
    expect(screen.queryByTestId("panel")).not.toBeInTheDocument();
  });

  it("warns before submitting when the list contains social media links, and stays quiet otherwise", async () => {
    api([]);
    render(<SubmissionForm />);
    await userEvent.click(screen.getByRole("textbox"));
    await userEvent.paste("https://westwinghouse.com/post");
    expect(screen.queryByText(/social media link/)).not.toBeInTheDocument();
    await userEvent.clear(screen.getByRole("textbox"));
    await userEvent.paste("https://www.facebook.com/share/p/1JaLqV9B7M/\nhttps://x.com/u/status/1\nhttps://westwinghouse.com/post");
    expect(await screen.findByText("2 social media links detected")).toBeInTheDocument();
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent(/cannot override that/);
    expect(note).toHaveTextContent(/facebook \(1\)/i);
    expect(note).toHaveTextContent(/x \(1\)/i);
    expect(screen.getByRole("link", { name: "Check my backlinks" })).toHaveAttribute("href", "/dashboard/backlinks");
    expect(screen.getByRole("button", { name: "Submit for Fast Indexing" })).toBeEnabled(); // a warning, not a block
  });

  it("still works when the list cannot be loaded", async () => {
    api("error");
    search = "batch=abc";
    render(<SubmissionForm />);
    expect(screen.getByTestId("panel")).toHaveTextContent("abc");
    expect(screen.getByRole("button", { name: "Submit for Fast Indexing" })).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Recent submissions" })).not.toBeInTheDocument();
  });
});
