import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { result, sampleBatch, sampleItems } from "../test-data";
import type { CheckBatch } from "../types";
import { CheckForm } from "./check-form";
import { ResultRow } from "./result-row";
import { ResultsView } from "./results-view";
import { SummaryCards } from "./summary-cards";

// These tests exercise the real API client; only the sign-in token is stubbed.
vi.mock("@/lib/token", () => ({
  getToken: vi.fn(async () => "test-jwt"),
  clearToken: vi.fn(),
  announceSessionExpired: vi.fn(),
  SESSION_EXPIRED_EVENT: "quickindex:session-expired",
}));

type FetchCall = { url: string; init?: RequestInit };
let calls: FetchCall[] = [];

function mockFetch(handler: (c: FetchCall) => unknown, status = 200) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      // ResultsView also mounts PublicReportToggle, which independently fetches its own sharing state. That call is
      // covered by public-report-toggle.test.tsx and is unrelated noise here, so it's answered quietly and kept out
      // of `calls`, which the tests below use to inspect the one request each is actually about.
      if (/\/sharing$/.test(new URL(url).pathname)) {
        return new Response(JSON.stringify({ public_report: false, public_url: null }), { status: 200 });
      }
      const call = { url, init };
      calls.push(call);
      const body = handler(call);
      return new Response(status === 204 ? null : JSON.stringify(body), { status });
    }),
  );
}

beforeEach(() => {
  calls = [];
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SummaryCards", () => {
  it("shows the six summary numbers and says Google index status is Unknown", () => {
    render(<SummaryCards summary={sampleBatch().summary} hasTarget />);
    const section = screen.getByRole("region", { name: "Summary" });
    for (const label of ["Total URLs", "Checked", "Eligible", "With problems", "Backlinks found", "Backlinks missing"]) {
      expect(within(section).getByText(label)).toBeInTheDocument();
    }
    expect(within(section).getByText("5")).toBeInTheDocument(); // total
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "80");
    expect(section).toHaveTextContent("Google index status is Unknown");
    expect(section).toHaveTextContent("Checking… 4 of 5 done");
  });

  it("shows dashes for backlink counts when no target website was given", () => {
    render(<SummaryCards summary={sampleBatch().summary} hasTarget={false} />);
    expect(screen.getAllByText("—")).toHaveLength(2);
  });
});

describe("ResultRow", () => {
  const noop = () => {};

  it("shows every required field and plain-English problems with fixes when expanded", async () => {
    const blocked = sampleItems()[1];
    render(<ul><ResultRow item={blocked} onRecheck={noop} rechecking={false} /></ul>);
    expect(screen.getByText("Blocked")).toBeInTheDocument();
    expect(screen.getByText("Not in HTML")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { expanded: false }));
    const problems = screen.getByRole("list", { name: "Problems" });
    expect(problems).toHaveTextContent("Page is marked noindex");
    expect(problems).toHaveTextContent("Why: Page is marked noindex");
    expect(problems).toHaveTextContent("How to fix: Fix: Page is marked noindex");
    expect(screen.getByText("Final URL")).toBeInTheDocument();
    expect(screen.getByText("Canonical URL")).toBeInTheDocument();
    expect(screen.getByText("Anchor text")).toBeInTheDocument();
    expect(screen.getByText(/only authorized Search Console data can confirm indexing/)).toBeInTheDocument();
  });

  it("offers a Google site: search to run yourself, and says an empty result proves nothing", async () => {
    const item = sampleItems()[0];
    item.url = "https://blog.example/post?id=7#top";
    render(<ul><ResultRow item={item} onRecheck={noop} rechecking={false} /></ul>);
    await userEvent.click(screen.getByRole("button", { expanded: false }));
    const link = screen.getByRole("link", { name: "Search this page on Google" });
    expect(link).toHaveAttribute("href", "https://www.google.com/search?q=site%3Ablog.example%2Fpost%3Fid%3D7");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(screen.getByText(/that proves nothing/)).toBeInTheDocument();
  });

  it("says a missing link is 'not in the HTML', and that JavaScript may still add it", async () => {
    const blocked = sampleItems()[1];
    render(<ul><ResultRow item={blocked} onRecheck={noop} rechecking={false} /></ul>);
    await userEvent.click(screen.getByRole("button", { expanded: false }));
    expect(screen.getByText(/may still appear if the page adds links with JavaScript/)).toBeInTheDocument();
    expect(screen.queryByText("Missing")).not.toBeInTheDocument();
  });

  it("shows link type, anchor text and final URL after a redirect", () => {
    const item = sampleItems()[2];
    item.result = result({
      ...item.result!,
      final_url: "https://nofollow.example/final",
    });
    render(<ul><ResultRow item={item} onRecheck={noop} rechecking={false} /></ul>);
    expect(screen.getByText(/Found · Nofollow/)).toBeInTheDocument();
    expect(screen.getByText(/→ https:\/\/nofollow.example\/final/)).toBeInTheDocument();
  });

  it("never labels a technically eligible page as indexed", () => {
    const { container } = render(<ul><ResultRow item={sampleItems()[0]} onRecheck={noop} rechecking={false} /></ul>);
    expect(screen.getByText("Eligible")).toBeInTheDocument();
    expect(container.textContent).toContain("Unknown");
    expect(container.textContent?.toLowerCase()).not.toMatch(/\bindexed\b/);
  });

  it("disables recheck for URLs that have not finished", () => {
    render(<ul><ResultRow item={sampleItems()[4]} onRecheck={noop} rechecking={false} /></ul>);
    expect(screen.getByRole("button", { name: /Recheck/ })).toBeDisabled();
    expect(screen.getByText("Checking…")).toBeInTheDocument();
  });
});

describe("ResultsView", () => {
  it("filters and sorts the list", async () => {
    render(<ResultsView batch={sampleBatch()} onChanged={() => {}} />);
    expect(screen.getAllByRole("button", { name: /^Recheck/ })).toHaveLength(5);

    await userEvent.selectOptions(screen.getByLabelText("Filter by result"), "blocked");
    expect(screen.getAllByRole("button", { name: /^Recheck/ })).toHaveLength(1);
    expect(screen.getByText("Showing 1 of 5 URLs.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Clear filters" }));
    await userEvent.selectOptions(screen.getByLabelText("Sort by"), "verdict:asc");
    const first = screen.getAllByRole("listitem")[0];
    expect(first).toHaveTextContent("noindex.example"); // worst problem first

    await userEvent.type(screen.getByLabelText("Search"), "zzz-no-match");
    expect(screen.getByText("No URLs match these filters.")).toBeInTheDocument();
  });

  it("rechecks one URL through the API and asks the page to refresh", async () => {
    mockFetch(() => ({ status: "queued" }), 202);
    const onChanged = vi.fn();
    render(<ResultsView batch={sampleBatch()} onChanged={onChanged} />);
    await userEvent.click(screen.getByRole("button", { name: "Recheck https://noindex.example/b" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(calls[0].url).toMatch(/\/api\/v1\/check-batches\/batch-1\/checks\/id-1\/recheck$/);
    expect(calls[0].init?.method).toBe("POST");
  });

  it("saves what the customer saw on Google, labelled as self-reported, and refreshes the page", async () => {
    mockFetch(() => ({ manual_google: "appears", manual_google_at: "2026-11-12T10:00:00+00:00" }));
    const onChanged = vi.fn();
    render(<ResultsView batch={sampleBatch()} onChanged={onChanged} />);
    await userEvent.click(screen.getAllByRole("button", { expanded: false })[0]);
    await userEvent.click(screen.getByRole("button", { name: "It appeared" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));
    expect(calls[0].url).toMatch(/\/api\/v1\/check-batches\/batch-1\/checks\/id-0\/manual-google$/);
    expect(calls[0].init?.method).toBe("PUT");
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ result: "appears" }); // only the answer: no user id, no verdict
  });

  it("shows a saved note as self-reported and leaves the Google index status Unknown", async () => {
    const item = { ...sampleItems()[0], manual_google: "not_found" as const, manual_google_at: "2026-11-12T10:00:00+00:00" };
    const { container } = render(<ul><ResultRow item={item} onRecheck={() => {}} rechecking={false} onMark={() => {}} /></ul>);
    await userEvent.click(screen.getByRole("button", { expanded: false }));
    expect(screen.getByText(/You reported: I did not find it in my Google search/)).toHaveTextContent("Self-reported, not verified by QuickIndex");
    expect(screen.getByRole("button", { name: "Clear" })).toBeInTheDocument();
    expect(container.textContent).toContain("Unknown");
    expect(container.textContent?.toLowerCase()).not.toMatch(/indexed/);
  });

  it("walks through the checked pages one at a time and saves each answer", async () => {
    mockFetch(() => ({ manual_google: "appears", manual_google_at: "2026-11-12T10:00:00+00:00" }));
    const onChanged = vi.fn();
    const batch = sampleBatch();
    const done = batch.items.filter((i) => i.state === "done");
    render(<ResultsView batch={batch} onChanged={onChanged} />);
    await userEvent.click(screen.getByRole("button", { name: `Review on Google (${done.length})` }));
    const panel = screen.getByRole("region", { name: "Review on Google" });
    expect(panel).toHaveTextContent(`Page 1 of ${done.length}`);
    expect(within(panel).getByRole("link", { name: "Open Google search" })).toHaveAttribute("href", expect.stringContaining("https://www.google.com/search?q=site%3A"));
    await userEvent.click(within(panel).getByRole("button", { name: "Not found" }));
    await waitFor(() => expect(panel).toHaveTextContent(`Page 2 of ${done.length}`));
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({ result: "not_found" });
    await userEvent.click(within(panel).getByRole("button", { name: "Skip" }));
    expect(panel).toHaveTextContent(`Page 3 of ${done.length}`);
    expect(calls).toHaveLength(1); // skipping saves nothing
    await userEvent.click(within(panel).getByRole("button", { name: "Stop" }));
    expect(screen.queryByRole("region", { name: "Review on Google" })).not.toBeInTheDocument();
  });

  it("stays on the same page and shows the error when saving fails", async () => {
    mockFetch(() => ({ detail: "boom" }), 500);
    const batch = sampleBatch();
    const total = batch.items.filter((i) => i.state === "done").length;
    render(<ResultsView batch={batch} onChanged={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: `Review on Google (${total})` }));
    const panel = screen.getByRole("region", { name: "Review on Google" });
    await userEvent.click(within(panel).getByRole("button", { name: "It appeared" }));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(panel).toHaveTextContent(`Page 1 of ${total}`);
  });

  it("deletes a batch after confirmation and tells the page", async () => {
    mockFetch(() => ({}), 204);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const onDeleted = vi.fn();
    render(<ResultsView batch={sampleBatch()} onChanged={() => {}} onDeleted={onDeleted} />);
    await userEvent.click(screen.getByRole("button", { name: /Delete batch/ }));
    await waitFor(() => expect(onDeleted).toHaveBeenCalledTimes(1));
    expect(calls[0].url).toMatch(/\/api\/v1\/check-batches\/batch-1$/);
    expect(calls[0].init?.method).toBe("DELETE");
  });

  it("does not delete when the customer cancels", async () => {
    mockFetch(() => ({}), 204);
    vi.spyOn(window, "confirm").mockReturnValue(false);
    const onDeleted = vi.fn();
    render(<ResultsView batch={sampleBatch()} onChanged={() => {}} onDeleted={onDeleted} />);
    await userEvent.click(screen.getByRole("button", { name: /Delete batch/ }));
    expect(calls).toHaveLength(0);
    expect(onDeleted).not.toHaveBeenCalled();
  });

  it("shows an error if the recheck fails and does not refresh", async () => {
    mockFetch(() => ({ detail: "Check not found" }), 404);
    const onChanged = vi.fn();
    render(<ResultsView batch={sampleBatch()} onChanged={onChanged} />);
    await userEvent.click(screen.getByRole("button", { name: "Recheck https://good.example/a" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Check not found");
    expect(onChanged).not.toHaveBeenCalled();
  });

  it("exports the currently filtered rows as CSV", async () => {
    const created: Blob[] = [];
    vi.stubGlobal("URL", Object.assign(URL, {
      createObjectURL: (b: Blob) => (created.push(b), "blob:test"),
      revokeObjectURL: () => {},
    }));
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<ResultsView batch={sampleBatch()} onChanged={() => {}} />);
    await userEvent.selectOptions(screen.getByLabelText("Filter by result"), "eligible");
    await userEvent.click(screen.getByRole("button", { name: /Export CSV \(1\)/ }));
    expect(created).toHaveLength(1);
    const text = await created[0].text();
    expect(text).toContain("good.example/a");
    expect(text).not.toContain("noindex.example");
  });
});

describe("CheckForm", () => {
  it("counts valid URLs, blocks more than 1,000, and sends the batch to the API", async () => {
    mockFetch(() => ({ batch_id: "new-batch", total: 2 }));
    const onCreated = vi.fn();
    render(<CheckForm onCreated={onCreated} />);
    const submit = screen.getByRole("button", { name: "Check these backlinks" });
    expect(submit).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/Your website/), "mysite.com");
    await userEvent.click(screen.getByLabelText(/Backlink pages/));
    await userEvent.paste("https://a.example/1\nhttps://b.example/2\nhttps://a.example/1\n");
    expect(screen.getByText(/URLs detected/)).toHaveTextContent("2 URLs detected (max 1,000)");

    await userEvent.click(submit);
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith("new-batch"));
    expect(calls[0].url).toMatch(/\/api\/v1\/check-batches$/);
    // The customer is identified by the token, never by a field in the request.
    expect(JSON.parse(String(calls[0].init?.body))).toEqual({
      urls: ["https://a.example/1", "https://b.example/2"],
      target: "mysite.com",
    });
    expect((calls[0].init?.headers as Record<string, string>).Authorization).toBe("Bearer test-jwt");
  });

  it("refuses 1,001 URLs", async () => {
    render(<CheckForm onCreated={() => {}} />);
    const many = Array.from({ length: 1001 }, (_, i) => `https://x.example/${i}`).join("\n");
    await userEvent.click(screen.getByLabelText(/Backlink pages/));
    await userEvent.paste(many);
    expect(screen.getByText(/over the limit of 1,000/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check these backlinks" })).toBeDisabled();
  });

  it("shows the server's error message", async () => {
    mockFetch(() => ({ detail: [{ msg: "Value error, Invalid URL: nope" }] }), 422);
    render(<CheckForm onCreated={() => {}} />);
    await userEvent.click(screen.getByLabelText(/Backlink pages/));
    await userEvent.paste("nope");
    await userEvent.click(screen.getByRole("button", { name: "Check these backlinks" }));
    expect(await screen.findByText("Invalid URL: nope")).toBeInTheDocument();
  });
});

describe("polling hook", () => {
  it("keeps polling until the batch is done, then stops", async () => {
    const { useCheckBatch } = await import("../hooks/use-check-batch");
    const { renderHook } = await import("@testing-library/react");
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let n = 0;
    mockFetch(() => {
      n += 1;
      const b: CheckBatch = sampleBatch();
      b.summary.done = n >= 3;
      return b;
    });
    const { result: hook } = renderHook(() => useCheckBatch("batch-1"));
    await waitFor(() => expect(hook.current.batch).not.toBeNull());
    await vi.advanceTimersByTimeAsync(2600);
    await vi.advanceTimersByTimeAsync(2600);
    await waitFor(() => expect(hook.current.batch?.summary.done).toBe(true));
    const total = calls.length;
    await vi.advanceTimersByTimeAsync(10000);
    expect(calls.length).toBe(total); // stopped polling
    vi.useRealTimers();
  });
});
