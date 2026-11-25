import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/token", () => ({
  getToken: vi.fn(async () => "test-jwt"),
  clearToken: vi.fn(),
  announceSessionExpired: vi.fn(),
  SESSION_EXPIRED_EVENT: "quickindex:session-expired",
}));

import { SharingControls } from "./sharing-controls";

type Call = { url: string; init?: RequestInit };
let calls: Call[] = [];
let sharing = { public_feed: false, public_url: null as string | null };

function stubApi(overrides: Partial<Record<string, { status: number; body?: unknown; text?: string }>> = {}) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const path = new URL(url).pathname;
      const key = `${init?.method ?? "GET"} ${path.replace(/^\/api\/v1\/batches\/[^/]+/, "")}`;
      const o = overrides[key];
      if (o) return new Response(o.text ?? JSON.stringify(o.body ?? {}), { status: o.status });
      if (key === "GET /sharing") return new Response(JSON.stringify(sharing), { status: 200 });
      if (key === "PUT /sharing") {
        const on = JSON.parse(String(init?.body)).public_feed;
        sharing = { public_feed: on, public_url: on ? "https://api.example.com/batches/batch-1/feed.xml" : null };
        return new Response(JSON.stringify(sharing), { status: 200 });
      }
      if (key === "GET /feed.xml") return new Response("<rss/>", { status: 200 });
      if (key === "GET /sitemap.xml") return new Response("<urlset/>", { status: 200 });
      return new Response("{}", { status: 404 });
    }),
  );
}
const auth = (c: Call) => (c.init?.headers as Record<string, string>).Authorization;

beforeEach(() => {
  sharing = { public_feed: false, public_url: null };
});
afterEach(() => vi.unstubAllGlobals());

describe("SharingControls", () => {
  it("is private by default, with the explanation, and no public link", async () => {
    stubApi();
    render(<SharingControls batchId="batch-1" />);
    const box = await screen.findByRole("checkbox", { name: /Public feed/ });
    await waitFor(() => expect(box).toBeEnabled());
    expect(box).not.toBeChecked();
    expect(screen.getByText(/Off by default\. Turning this on lets anyone with the link read this batch's URL list\./)).toBeInTheDocument();
    expect(screen.queryByText(/batches\/batch-1\/feed\.xml/)).not.toBeInTheDocument();
    expect(auth(calls[0])).toBe("Bearer test-jwt");
  });

  it("opts in through the API and shows the public link, then opts out again", async () => {
    stubApi();
    render(<SharingControls batchId="batch-1" />);
    const box = await screen.findByRole("checkbox", { name: /Public feed/ });
    await waitFor(() => expect(box).toBeEnabled());
    await userEvent.click(box);
    expect(await screen.findByText("https://api.example.com/batches/batch-1/feed.xml")).toBeInTheDocument();
    const put = calls.find((c) => c.init?.method === "PUT")!;
    expect(put.url).toMatch(/\/api\/v1\/batches\/batch-1\/sharing$/);
    expect(JSON.parse(String(put.init?.body))).toEqual({ public_feed: true });
    expect(auth(put)).toBe("Bearer test-jwt");
    expect(screen.getByRole("button", { name: "Copy public feed link" })).toBeInTheDocument();

    await userEvent.click(box);
    await waitFor(() => expect(screen.queryByText("https://api.example.com/batches/batch-1/feed.xml")).not.toBeInTheDocument());
    expect(JSON.parse(String(calls.filter((c) => c.init?.method === "PUT").at(-1)!.init?.body))).toEqual({ public_feed: false });
  });

  it("downloads the feed and sitemap WITH the sign-in token", async () => {
    stubApi();
    const created: Blob[] = [];
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: (b: Blob) => (created.push(b), "blob:x"), revokeObjectURL: () => {} }));
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<SharingControls batchId="batch-1" />);
    await userEvent.click(await screen.findByRole("button", { name: /Download feed/ }));
    await userEvent.click(screen.getByRole("button", { name: /Download sitemap/ }));
    await waitFor(() => expect(created).toHaveLength(2));
    const feedCall = calls.find((c) => /\/feed\.xml$/.test(c.url))!;
    const mapCall = calls.find((c) => /\/sitemap\.xml$/.test(c.url))!;
    expect(feedCall.url).toMatch(/\/api\/v1\/batches\/batch-1\/feed\.xml$/);
    expect(auth(feedCall)).toBe("Bearer test-jwt");
    expect(auth(mapCall)).toBe("Bearer test-jwt");
    expect(await created[0].text()).toBe("<rss/>");
    expect(click).toHaveBeenCalledTimes(2);
  });

  it("shows ownership/404 errors plainly", async () => {
    stubApi({ "GET /sharing": { status: 404, body: { detail: "Batch not found" } } });
    render(<SharingControls batchId="batch-1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Batch not found");
    expect(screen.getByRole("checkbox", { name: /Public feed/ })).toBeDisabled();
  });

  it("shows an error when a download is refused", async () => {
    stubApi({ "GET /feed.xml": { status: 404, body: { detail: "Batch not found" } } });
    render(<SharingControls batchId="batch-1" />);
    await userEvent.click(await screen.findByRole("button", { name: /Download feed/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Batch not found");
  });
});
