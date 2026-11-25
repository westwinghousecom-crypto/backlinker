import { act, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  failed,
  history,
  neverInspected,
  notIndexed,
  properties,
  sitemaps,
  status,
  target,
} from "../test-data";

// These tests run the real API client; only the sign-in token and routing are stubbed.
vi.mock("@/lib/token", () => ({
  getToken: vi.fn(async () => "test-jwt"),
  clearToken: vi.fn(),
  announceSessionExpired: vi.fn(),
  SESSION_EXPIRED_EVENT: "quickindex:session-expired",
}));

const replace = vi.fn();
let search = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/dashboard/google",
  useSearchParams: () => new URLSearchParams(search),
}));

import { useTargets } from "../hooks/use-targets";
import { QUOTA_MESSAGE } from "../lib/labels";
import { ConnectionCard } from "./connection-card";
import { GoogleIndexStatusPage } from "./google-index-status";
import { HistoryTimeline } from "./history-timeline";
import { PropertyPicker } from "./property-picker";
import { QuotaMeter } from "./quota-meter";
import { SitemapsPanel } from "./sitemaps-panel";
import { TargetRow } from "./target-row";
import { TargetsPanel } from "./targets-panel";

type Call = { url: string; method: string; body: unknown };
type Handler = (c: Call) => { status?: number; body?: unknown } | undefined;
let calls: Call[] = [];

/** Route fake Google/QuickIndex API responses by "METHOD /path". Unrouted calls fail the test loudly. */
function api(routes: Record<string, Handler | { status?: number; body?: unknown }>) {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.replace(/^https?:\/\/[^/]+/, "");
      const method = (init?.method ?? "GET").toUpperCase();
      const call = { url: path, method, body: init?.body ? JSON.parse(String(init.body)) : undefined };
      calls.push(call);
      const key = Object.keys(routes).find((k) => k === `${method} ${path}`);
      if (!key) return new Response(JSON.stringify({ detail: `unrouted ${method} ${path}` }), { status: 500 });
      const r = routes[key];
      const out = typeof r === "function" ? r(call) : r;
      const status = out?.status ?? 200;
      return new Response(status === 204 ? null : JSON.stringify(out?.body ?? {}), { status });
    }),
  );
}
const err = (status: number, code: string, message: string) => ({ status, body: { detail: { code, message } } });

const assign = vi.fn();
beforeEach(() => {
  vi.clearAllMocks();
  search = "";
  vi.stubGlobal("location", { ...window.location, assign });
});
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

const GOOGLE_URL = "https://accounts.google.com/o/oauth2/v2/auth?client_id=x&state=s";

describe("connection card", () => {
  it("not configured: explains and offers no connect button", () => {
    render(<ConnectionCard status={status({ configured: false, connected: false, state: null })} notice={null} onChanged={() => {}} />);
    expect(screen.getByText("Google integration is not set up on this server yet.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Connect Google Search Console/ })).not.toBeInTheDocument();
  });

  it("connect asks the server for a URL (read-only) and redirects the browser to Google", async () => {
    api({ "POST /api/v1/google/connect": { body: { authorization_url: GOOGLE_URL } } });
    render(<ConnectionCard status={status({ connected: false, state: null, email: null })} notice={null} onChanged={() => {}} />);
    expect(screen.getByText(/read-only access to your Search Console data/)).toBeInTheDocument();
    expect(screen.getByText(/never change anything unless you/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Connect Google Search Console" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith(GOOGLE_URL));
    expect(calls[0]).toMatchObject({ method: "POST", url: "/api/v1/google/connect", body: { write: false } });
  });

  it("refuses to redirect anywhere except Google's sign-in host", async () => {
    api({ "POST /api/v1/google/connect": { body: { authorization_url: "https://evil.example/phish" } } });
    render(<ConnectionCard status={status({ connected: false, state: null })} notice={null} onChanged={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Connect Google Search Console" }));
    expect(await screen.findByText(/unexpected sign-in address/)).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
  });

  it("shows the connected account and access level, and disconnects after confirmation", async () => {
    api({ "DELETE /api/v1/google/connection": { status: 204 } });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const onChanged = vi.fn();
    render(<ConnectionCard status={status()} notice={null} onChanged={onChanged} />);
    expect(screen.getByText("owner@example.com")).toBeInTheDocument();
    expect(screen.getByText("Read-only")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(calls[0]).toMatchObject({ method: "DELETE", url: "/api/v1/google/connection" });
  });

  it("sends the connect request with credentials so the API can bind the sign-in to this browser", async () => {
    api({ "POST /api/v1/google/connect": { body: { authorization_url: GOOGLE_URL } } });
    render(<ConnectionCard status={status({ connected: false, state: null, email: null })} notice={null} onChanged={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Connect Google Search Console" }));
    await waitFor(() => expect(assign).toHaveBeenCalled());
    const init = (fetch as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls[0][1];
    expect(init.credentials).toBe("include");
  });

  it("'Delete my Google data' is separate from Disconnect, asks first, and erases via the data endpoint", async () => {
    api({ "DELETE /api/v1/google/data": { status: 204 } });
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const onChanged = vi.fn();
    render(<ConnectionCard status={status()} notice={null} onChanged={onChanged} />);
    expect(screen.getByText(/Disconnect stops checks and revokes our access but keeps your history/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Delete my Google data" }));
    expect(confirm).toHaveBeenCalled();
    expect(calls).toHaveLength(0); // cancelled: nothing sent
    confirm.mockReturnValue(true);
    await userEvent.click(screen.getByRole("button", { name: "Delete my Google data" }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(calls[0]).toMatchObject({ method: "DELETE", url: "/api/v1/google/data" });
  });

  it("revoked access shows a prominent reconnect alert", () => {
    render(<ConnectionCard status={status({ state: "revoked", reauth_required: true })} notice={null} onChanged={() => {}} />);
    expect(screen.getByText("Google access was revoked or expired. Reconnect")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reconnect Google" })).toBeInTheDocument();
  });
});

describe("page", () => {
  it("shows friendly messages for each callback outcome and clears the query string", async () => {
    for (const [q, text] of [
      ["google_error=access_denied", "You did not grant access"],
      ["google_error=scope_missing", "Search Console permission was not granted"],
      ["google_error=invalid_state", "invalid or had expired"],
      ["connected=1", "Google Search Console is connected."],
    ] as const) {
      search = q;
      replace.mockClear();
      api({ "GET /api/v1/google/status": { body: status({ connected: false, state: null, selected_property: null, quota: null }) } });
      const { unmount } = render(<GoogleIndexStatusPage />);
      expect(await screen.findByText(new RegExp(text))).toBeInTheDocument();
      expect(replace).toHaveBeenCalledWith("/dashboard/google");
      unmount();
    }
  });

  it("revoked credentials: shows the alert and does not load properties or URLs", async () => {
    api({ "GET /api/v1/google/status": { body: status({ state: "revoked", reauth_required: true }) } });
    render(<GoogleIndexStatusPage />);
    expect(await screen.findByText("Google access was revoked or expired. Reconnect")).toBeInTheDocument();
    expect(calls.map((c) => c.url)).toEqual(["/api/v1/google/status"]);
  });

  it("connected with a property shows the full dashboard", async () => {
    api({
      "GET /api/v1/google/status": { body: status() },
      "GET /api/v1/google/properties": { body: { properties: properties() } },
      "GET /api/v1/google/targets": { body: { items: [target()] } },
      "GET /api/v1/google/sitemaps": { body: sitemaps(true) },
    });
    render(<GoogleIndexStatusPage />);
    expect(await screen.findByRole("region", { name: "Google Index Status" })).toBeInTheDocument();
    expect(await screen.findByText("https://mysite.com/a")).toBeInTheDocument();
    expect(await screen.findByRole("region", { name: "Sitemaps" })).toBeInTheDocument();
  });
});

describe("property picker", () => {
  it("labels Domain and URL-prefix properties, disables unverified ones, and selects with PUT", async () => {
    api({
      "GET /api/v1/google/properties": { body: { properties: properties() } },
      "PUT /api/v1/google/property": (c) => ({ body: { selected_property: (c.body as { site_url: string }).site_url } }),
    });
    const onSelected = vi.fn();
    render(<PropertyPicker selected="sc-domain:mysite.com" onSelected={onSelected} onReauth={() => {}} />);
    const domain = await screen.findByRole("button", { name: /mysite\.com/ });
    expect(within(domain).getByText("Domain")).toBeInTheDocument();
    expect(domain).toHaveAttribute("aria-pressed", "true");
    const prefix = screen.getByRole("button", { name: /other\.com\/blog/ });
    expect(within(prefix).getByText("URL prefix")).toBeInTheDocument();
    const unverified = screen.getByRole("button", { name: /pending\.example/ });
    expect(unverified).toBeDisabled();
    expect(within(unverified).getByText(/verify ownership in Search Console/)).toBeInTheDocument();

    await userEvent.click(prefix);
    await waitFor(() => expect(onSelected).toHaveBeenCalledWith("https://www.other.com/blog/"));
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ site_url: "https://www.other.com/blog/" });
  });

  it("asks to reconnect when Google access is gone", async () => {
    api({ "GET /api/v1/google/properties": err(409, "google_reauth_required", "Reconnect Google to continue.") });
    const onReauth = vi.fn();
    render(<PropertyPicker selected={null} onSelected={() => {}} onReauth={onReauth} />);
    expect(await screen.findByText("Reconnect Google to continue.")).toBeInTheDocument();
    expect(onReauth).toHaveBeenCalled();
  });

  it("shows the server's message when a property cannot be used", async () => {
    api({
      "GET /api/v1/google/properties": { body: { properties: properties() } },
      "PUT /api/v1/google/property": err(400, "property_not_usable", "That property is not verified."),
    });
    render(<PropertyPicker selected={null} onSelected={() => {}} onReauth={() => {}} />);
    await userEvent.click(await screen.findByRole("button", { name: /mysite\.com/ }));
    expect(await screen.findByText("That property is not verified.")).toBeInTheDocument();
  });
});

describe("Google Index Status rows", () => {
  const noop = () => {};
  const row = (t = target()) => render(<ul><TargetRow target={t} onRecheck={noop} onRemove={noop} working={false} /></ul>);

  it("uses exactly the four status labels", () => {
    const labels = new Set<string>();
    for (const t of [target(), notIndexed(), neverInspected(), failed()]) {
      const { container, unmount } = row(t);
      labels.add(container.querySelector("span.rounded-full[title]")!.textContent!);
      unmount();
    }
    expect([...labels].sort()).toEqual(["Confirmed Indexed", "Confirmed Not Indexed", "Inspection Failed", "Unknown"]);
  });

  it("a URL Google has not inspected says Unknown, never Confirmed Indexed", () => {
    const { container } = row(neverInspected());
    expect(screen.getByText("Unknown")).toBeInTheDocument();
    expect(screen.getByText("Not inspected yet")).toBeInTheDocument();
    expect(container.textContent).not.toMatch(/Confirmed Indexed/);
  });

  it("shows the evidence source and the last inspection time", () => {
    row();
    expect(screen.getByText("Google URL Inspection API")).toBeInTheDocument();
    expect(screen.getByText(/Last inspected /)).toBeInTheDocument();
    expect(screen.queryByText("Not inspected yet")).not.toBeInTheDocument();
    expect(screen.getByText(/Next check /)).toBeInTheDocument();
  });

  it("expands to Google's evidence and flags a canonical mismatch", async () => {
    api({ "GET /api/v1/google/targets/t-no/history": { body: { items: [] } } });
    row(notIndexed());
    await userEvent.click(screen.getByRole("button", { expanded: false }));
    expect(screen.getByText("NEUTRAL")).toBeInTheDocument();
    expect(screen.getByText("Crawled - currently not indexed")).toBeInTheDocument();
    expect(screen.getByText(/differs from your declared canonical/)).toBeInTheDocument();
    expect(screen.getByText("ALLOWED")).toBeInTheDocument();
    expect(screen.getByText("INDEXING_ALLOWED")).toBeInTheDocument();
    expect(screen.getByText("SUCCESSFUL")).toBeInTheDocument();
    expect(screen.getByText(/https:\/\/mysite.com\/sitemap.xml/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /View in Search Console/ })).toHaveAttribute("href", expect.stringContaining("search.google.com"));
  });

  it("no mismatch flag when canonicals agree", async () => {
    api({ "GET /api/v1/google/targets/t1/history": { body: { items: [] } } });
    row();
    await userEvent.click(screen.getByRole("button", { expanded: false }));
    expect(screen.queryByText(/differs from your declared canonical/)).not.toBeInTheDocument();
  });

  it("a failed inspection shows the error and the last known status", async () => {
    api({ "GET /api/v1/google/targets/t-fail/history": { body: { items: [] } } });
    row(failed());
    await userEvent.click(screen.getByRole("button", { expanded: false }));
    const note = screen.getByRole("note");
    expect(note).toHaveTextContent("Google refused this inspection");
    expect(note).toHaveTextContent("Last known status: Confirmed Indexed");
  });

  it("recheck is disabled while an inspection is pending", () => {
    row(neverInspected());
    expect(screen.getByRole("button", { name: /^Recheck/ })).toBeDisabled();
  });
});

describe("history timeline", () => {
  it("lists inspections newest first and notes where Google's answer changed", () => {
    render(<HistoryTimeline items={history()} error={null} />);
    const items = within(screen.getByRole("list", { name: "Inspection history" })).getAllByRole("listitem");
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent("Inspection Failed");
    expect(items[0]).toHaveTextContent("Manual recheck");
    expect(items[0]).toHaveTextContent("quota exhausted");
    expect(items[1]).toHaveTextContent("Changed from Confirmed Not Indexed to Confirmed Indexed");
    expect(items[1]).toHaveTextContent("Scheduled recheck");
    expect(items[2]).toHaveTextContent("First check");
    expect(items[2]).not.toHaveTextContent("Changed from");
  });

  it("is loaded from the API when a row is expanded", async () => {
    api({ "GET /api/v1/google/targets/t1/history": { body: { items: history() } } });
    render(<ul><TargetRow target={target()} onRecheck={() => {}} onRemove={() => {}} working={false} /></ul>);
    await userEvent.click(screen.getByRole("button", { expanded: false }));
    expect(await screen.findByRole("list", { name: "Inspection history" })).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/v1/google/targets/t1/history")).toBe(true);
  });
});

describe("targets panel", () => {
  const panel = (over: Partial<Parameters<typeof TargetsPanel>[0]> = {}) =>
    render(<TargetsPanel property="sc-domain:mysite.com" quota={status().quota} onReauth={() => {}} onNeedProperty={() => {}} {...over} />);

  it("counts the four statuses and always shows the evidence rule", async () => {
    api({ "GET /api/v1/google/targets": { body: { items: [target(), notIndexed(), neverInspected(), failed()] } } });
    panel();
    await screen.findByText("https://mysite.com/a");
    for (const s of ["indexed", "not_indexed", "unknown", "failed"]) expect(screen.getByTestId(`count-${s}`)).toHaveTextContent("1");
    expect(screen.getByText(/Only Google's own URL Inspection can confirm indexing/)).toBeInTheDocument();
    expect(screen.getByText(/HTTP checks, IndexNow, WebSub, sitemaps and social shares never do/)).toBeInTheDocument();
  });

  it("adds URLs and lists skipped ones with plain-English reasons", async () => {
    api({
      "GET /api/v1/google/targets": { body: { items: [] } },
      "POST /api/v1/google/targets": { body: { added: 1, skipped: [{ url: "https://evil.example/x", reason: "outside_property" }, { url: "https://mysite.com/a", reason: "duplicate" }] } },
    });
    panel();
    await userEvent.click(screen.getByLabelText(/Your pages to check/));
    await userEvent.paste("https://mysite.com/new\nhttps://evil.example/x\nhttps://mysite.com/a");
    expect(screen.getByText("3 URLs detected")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Check with Google" }));
    const skipped = await screen.findByRole("list", { name: "Skipped URLs" });
    expect(skipped).toHaveTextContent("Not on your Search Console property, so Google cannot report on it");
    expect(screen.getByRole("link", { name: "Check my backlinks" })).toHaveAttribute("href", "/dashboard/backlinks");
    expect(screen.getByRole("status")).toHaveTextContent(/Pages on other sites, and social media posts, cannot be checked this way/);
    expect(skipped).toHaveTextContent("Already being tracked");
    expect(screen.getByRole("status")).toHaveTextContent("Added 1 URL.");
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ urls: ["https://mysite.com/new", "https://evil.example/x", "https://mysite.com/a"] });
  });

  it("blocks more than 200 URLs", async () => {
    api({ "GET /api/v1/google/targets": { body: { items: [] } } });
    panel();
    await userEvent.click(screen.getByLabelText(/Your pages to check/));
    await userEvent.paste(Array.from({ length: 201 }, (_, i) => `https://mysite.com/${i}`).join("\n"));
    expect(screen.getByText(/over the limit of 200/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check with Google" })).toBeDisabled();
  });

  it("recheck and remove call the API", async () => {
    api({
      "GET /api/v1/google/targets": { body: { items: [target()] } },
      "POST /api/v1/google/targets/t1/recheck": { status: 202 },
      "DELETE /api/v1/google/targets/t1": { status: 204 },
    });
    vi.spyOn(window, "confirm").mockReturnValue(true);
    panel();
    await userEvent.click(await screen.findByRole("button", { name: /^Recheck/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "POST" && c.url.endsWith("/recheck"))).toBe(true));
    await userEvent.click(await screen.findByRole("button", { name: /^Remove/ }));
    await waitFor(() => expect(calls.some((c) => c.method === "DELETE")).toBe(true));
  });

  it("prompts to choose a property when the API says none is selected", async () => {
    api({
      "GET /api/v1/google/targets": { body: { items: [] } },
      "POST /api/v1/google/targets": err(409, "property_not_selected", "Choose a Search Console property first."),
    });
    const onNeedProperty = vi.fn();
    panel({ onNeedProperty });
    await userEvent.click(screen.getByLabelText(/Your pages to check/));
    await userEvent.paste("https://mysite.com/a");
    await userEvent.click(screen.getByRole("button", { name: "Check with Google" }));
    expect(await screen.findByText("Choose a Search Console property first.")).toBeInTheDocument();
    expect(onNeedProperty).toHaveBeenCalled();
  });

  it("quota_exhausted shows a calm message, not a raw error", async () => {
    api({
      "GET /api/v1/google/targets": { body: { items: [target()] } },
      "POST /api/v1/google/targets/t1/recheck": err(429, "quota_exhausted", "RESOURCE_EXHAUSTED"),
    });
    panel();
    await userEvent.click(await screen.findByRole("button", { name: /^Recheck/ }));
    expect(await screen.findByText(QUOTA_MESSAGE)).toBeInTheDocument();
    expect(screen.queryByText("RESOURCE_EXHAUSTED")).not.toBeInTheDocument();
  });

  it("reconnect is requested when Google access disappears mid-use", async () => {
    api({ "GET /api/v1/google/targets": err(409, "google_reauth_required", "Reconnect Google to continue.") });
    const onReauth = vi.fn();
    panel({ onReauth });
    expect(await screen.findByText("Reconnect Google to continue.")).toBeInTheDocument();
  });
});

describe("polling", () => {
  it("polls every 5 seconds while a URL is pending and stops once nothing is in flight", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    let n = 0;
    api({
      "GET /api/v1/google/targets": () => {
        n += 1;
        return { body: { items: [n < 3 ? neverInspected() : target()] } };
      },
    });
    const { result } = renderHook(() => useTargets("sc-domain:mysite.com"));
    await waitFor(() => expect(result.current.items).not.toBeNull());
    expect(calls).toHaveLength(1);
    await act(() => vi.advanceTimersByTimeAsync(4500));
    expect(calls).toHaveLength(1); // not before 5 s
    await act(() => vi.advanceTimersByTimeAsync(600));
    expect(calls).toHaveLength(2);
    await act(() => vi.advanceTimersByTimeAsync(5100));
    expect(calls).toHaveLength(3);
    expect(result.current.items?.[0].state).toBe("done");
    await act(() => vi.advanceTimersByTimeAsync(30000));
    expect(calls).toHaveLength(3); // stopped
  });

  it("does not poll at all when everything is already settled", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    api({ "GET /api/v1/google/targets": { body: { items: [target(), notIndexed()] } } });
    const { result } = renderHook(() => useTargets("sc-domain:mysite.com"));
    await waitFor(() => expect(result.current.items).toHaveLength(2));
    await act(() => vi.advanceTimersByTimeAsync(20000));
    expect(calls).toHaveLength(1);
  });
});

describe("sitemaps panel", () => {
  it("lists sitemaps with errors, warnings and a pending badge", async () => {
    api({ "GET /api/v1/google/sitemaps": { body: sitemaps(true) } });
    render(<SitemapsPanel property="sc-domain:mysite.com" onReauth={() => {}} />);
    const list = await screen.findByRole("list", { name: "Known sitemaps" });
    expect(list).toHaveTextContent("https://mysite.com/sitemap.xml");
    expect(list).toHaveTextContent("Pending");
    expect(list).toHaveTextContent("1 error");
    expect(list).toHaveTextContent("2 warnings");
  });

  it("with write access, submits a sitemap", async () => {
    api({
      "GET /api/v1/google/sitemaps": { body: sitemaps(true) },
      "PUT /api/v1/google/sitemaps": { body: { submitted: true } },
    });
    render(<SitemapsPanel property="sc-domain:mysite.com" onReauth={() => {}} />);
    await userEvent.type(await screen.findByLabelText("Sitemap URL"), "https://mysite.com/news.xml");
    await userEvent.click(screen.getByRole("button", { name: "Submit sitemap" }));
    expect(await screen.findByText("Sitemap submitted to Google.")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({ url: "https://mysite.com/news.xml" });
  });

  it("read-only connection: explains the extra permission and requests write access", async () => {
    api({
      "GET /api/v1/google/sitemaps": { body: sitemaps(false) },
      "POST /api/v1/google/connect": { body: { authorization_url: GOOGLE_URL } },
    });
    render(<SitemapsPanel property="sc-domain:mysite.com" onReauth={() => {}} />);
    expect(await screen.findByText(/Submitting needs extra permission/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Submit sitemap" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Grant write access" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith(GOOGLE_URL));
    expect(calls.find((c) => c.method === "POST")?.body).toEqual({ write: true });
  });

  it("write_permission_required from the server shows the same prompt", async () => {
    api({
      "GET /api/v1/google/sitemaps": { body: sitemaps(true) },
      "PUT /api/v1/google/sitemaps": err(403, "write_permission_required", "Needs write access"),
    });
    render(<SitemapsPanel property="sc-domain:mysite.com" onReauth={() => {}} />);
    await userEvent.type(await screen.findByLabelText("Sitemap URL"), "https://mysite.com/news.xml");
    await userEvent.click(screen.getByRole("button", { name: "Submit sitemap" }));
    expect(await screen.findByText(/Submitting needs extra permission/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Grant write access" })).toBeInTheDocument();
  });
});

describe("quota meter", () => {
  it("shows used / limit and the per-minute limit", () => {
    render(<QuotaMeter quota={{ property: "p", per_day_limit: 2000, used_today: 500, per_minute_limit: 600 }} />);
    expect(screen.getByText(/500 \/ 2,000/)).toBeInTheDocument();
    expect(screen.getByText(/max 600 per minute/)).toBeInTheDocument();
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "500");
    expect(screen.queryByText(QUOTA_MESSAGE)).not.toBeInTheDocument();
  });

  it("warns near the limit and explains when it is reached", () => {
    const { rerender } = render(<QuotaMeter quota={{ property: "p", per_day_limit: 2000, used_today: 1700, per_minute_limit: 600 }} />);
    expect(screen.getByText(/used 85% of today's Google limit/)).toBeInTheDocument();
    rerender(<QuotaMeter quota={{ property: "p", per_day_limit: 2000, used_today: 2000, per_minute_limit: 600 }} />);
    expect(screen.getByText(QUOTA_MESSAGE)).toBeInTheDocument();
  });
});
