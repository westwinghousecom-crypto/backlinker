import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/token", () => ({
  getToken: vi.fn(async () => "test-jwt"),
  clearToken: vi.fn(),
  announceSessionExpired: vi.fn(),
  SESSION_EXPIRED_EVENT: "quickindex:session-expired",
}));

import { PublicReportToggle } from "./public-report-toggle";

type Call = { url: string; init?: RequestInit };
let calls: Call[] = [];
let sharing = { public_report: false, public_url: null as string | null };

function stubApi(overrides: Partial<Record<string, { status: number; body?: unknown }>> = {}) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, init });
      const path = new URL(url).pathname;
      const key = `${init?.method ?? "GET"} ${path.replace(/^\/api\/v1\/check-batches\/[^/]+/, "")}`;
      const o = overrides[key];
      if (o) return new Response(JSON.stringify(o.body ?? {}), { status: o.status });
      if (key === "GET /sharing") return new Response(JSON.stringify(sharing), { status: 200 });
      if (key === "PUT /sharing") {
        const on = JSON.parse(String(init?.body)).public_report;
        sharing = { public_report: on, public_url: on ? "https://app.example.com/report/batch-1" : null };
        return new Response(JSON.stringify(sharing), { status: 200 });
      }
      return new Response("{}", { status: 404 });
    }),
  );
}
const auth = (c: Call) => (c.init?.headers as Record<string, string>).Authorization;

beforeEach(() => {
  sharing = { public_report: false, public_url: null };
});
afterEach(() => vi.unstubAllGlobals());

describe("PublicReportToggle", () => {
  it("is private by default, with the explanation, and no public link", async () => {
    stubApi();
    render(<PublicReportToggle batchId="batch-1" />);
    const box = await screen.findByRole("checkbox", { name: /Public report/ });
    await waitFor(() => expect(box).toBeEnabled());
    expect(box).not.toBeChecked();
    expect(screen.getByText(/Off by default\. Turning this on lets anyone with the link see these results/)).toBeInTheDocument();
    expect(screen.getByText(/never your own Google search notes, which stay private/)).toBeInTheDocument();
    expect(screen.queryByText(/report\/batch-1/)).not.toBeInTheDocument();
    expect(auth(calls[0])).toBe("Bearer test-jwt"); // the owner-only read is authenticated
  });

  it("opts in through the API and shows the public link, then opts out again", async () => {
    stubApi();
    render(<PublicReportToggle batchId="batch-1" />);
    const box = await screen.findByRole("checkbox", { name: /Public report/ });
    await waitFor(() => expect(box).toBeEnabled());
    await userEvent.click(box);
    expect(await screen.findByText("https://app.example.com/report/batch-1")).toBeInTheDocument();
    const put = calls.find((c) => c.init?.method === "PUT")!;
    expect(put.url).toMatch(/\/api\/v1\/check-batches\/batch-1\/sharing$/);
    expect(JSON.parse(String(put.init?.body))).toEqual({ public_report: true });
    expect(auth(put)).toBe("Bearer test-jwt");
    expect(screen.getByRole("button", { name: "Copy public report link" })).toBeInTheDocument();

    await userEvent.click(box);
    await waitFor(() => expect(screen.queryByText("https://app.example.com/report/batch-1")).not.toBeInTheDocument());
    expect(JSON.parse(String(calls.filter((c) => c.init?.method === "PUT").at(-1)!.init?.body))).toEqual({
      public_report: false,
    });
  });

  it("copies the public link to the clipboard", async () => {
    stubApi();
    const writeText = vi.fn(async () => {});
    Object.assign(navigator, { clipboard: { writeText } });
    render(<PublicReportToggle batchId="batch-1" />);
    await userEvent.click(await screen.findByRole("checkbox", { name: /Public report/ }));
    await userEvent.click(await screen.findByRole("button", { name: "Copy public report link" }));
    expect(writeText).toHaveBeenCalledWith("https://app.example.com/report/batch-1");
    expect(await screen.findByLabelText("Copy public report link")).toBeInTheDocument();
  });

  it("shows ownership/404 errors plainly", async () => {
    stubApi({ "GET /sharing": { status: 404, body: { detail: "Batch not found" } } });
    render(<PublicReportToggle batchId="batch-1" />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Batch not found");
    expect(screen.getByRole("checkbox", { name: /Public report/ })).toBeDisabled();
  });
});
