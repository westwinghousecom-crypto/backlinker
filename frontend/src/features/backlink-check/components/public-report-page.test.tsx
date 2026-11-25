import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { sampleBatch } from "../test-data";
import { PublicReportPageContent } from "./public-report-page";

// No `@/lib/token` mock anywhere in this file: a visitor reading a shared report has no sign-in at all.

type Call = { url: string; init?: RequestInit };
let calls: Call[] = [];

function stubApi(status: number, body: unknown) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      return new Response(JSON.stringify(body), { status });
    }),
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("public report page content", () => {
  it("renders a shared batch's results with no sign-in and no Authorization header", async () => {
    stubApi(200, sampleBatch());
    render(<PublicReportPageContent batchId="batch-1" />);
    expect(await screen.findByText(/Looking for links to/)).toBeInTheDocument();
    expect(screen.getByText("https://mysite.com")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "URL results" })).toBeInTheDocument();
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toMatch(/\/api\/v1\/check-batches\/batch-1\/public$/);
    expect(calls[0].init).toBeUndefined(); // a plain unauthenticated fetch: no init object, no headers, no token
  });

  it("never shows a recheck button, a delete button, or Google-note write controls", async () => {
    stubApi(200, sampleBatch());
    render(<PublicReportPageContent batchId="batch-1" />);
    const list = await screen.findByRole("list", { name: "URL results" });
    await waitFor(() => expect(within(list).getAllByRole("listitem").length).toBeGreaterThan(0));
    for (const row of within(list).getAllByRole("listitem")) {
      const withinRow = within(row);
      expect(withinRow.queryByRole("button", { name: /^Recheck/ })).not.toBeInTheDocument();
      expect(withinRow.queryByRole("button", { name: /It appeared/ })).not.toBeInTheDocument();
      expect(withinRow.queryByRole("button", { name: /Not found/ })).not.toBeInTheDocument();
    }
    expect(screen.queryByRole("button", { name: /Delete batch/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Export CSV/ })).not.toBeInTheDocument();
  });

  it("shows a plain not-found message on a 404, instead of crashing", async () => {
    stubApi(404, { detail: "Batch not found" });
    render(<PublicReportPageContent batchId="batch-1" />);
    expect(await screen.findByText("Report not found")).toBeInTheDocument();
    expect(screen.getByText(/link may be wrong, or the owner may have turned sharing off/)).toBeInTheDocument();
    expect(screen.queryByRole("list", { name: "URL results" })).not.toBeInTheDocument();
  });

  it("shows a generic message for a server error, and for an unreachable server", async () => {
    stubApi(500, { detail: "boom" });
    render(<PublicReportPageContent batchId="batch-1" />);
    expect(await screen.findByText("Something went wrong")).toBeInTheDocument();

    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    render(<PublicReportPageContent batchId="batch-2" />);
    await waitFor(() => expect(screen.getAllByText("Something went wrong")).toHaveLength(2));
  });

  it("shows a loading state before the fetch resolves, and an empty-batch message if the batch has no URLs", async () => {
    let resolve!: (r: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>((r) => (resolve = r))),
    );
    render(<PublicReportPageContent batchId="batch-1" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading…");
    resolve(new Response(JSON.stringify(sampleBatch({ items: [] })), { status: 200 }));
    expect(await screen.findByText("No URLs in this batch.")).toBeInTheDocument();
  });

  it("re-fetches when the batch id changes", async () => {
    stubApi(200, sampleBatch());
    const { rerender } = render(<PublicReportPageContent batchId="batch-1" />);
    await screen.findByText(/Looking for links to/);
    rerender(<PublicReportPageContent batchId="batch-2" />);
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1].url).toMatch(/\/api\/v1\/check-batches\/batch-2\/public$/);
  });
});
