import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/token", () => ({
  getToken: vi.fn(async () => "jwt"),
  clearToken: vi.fn(),
  announceSessionExpired: vi.fn(),
  SESSION_EXPIRED_EVENT: "quickindex:session-expired",
}));

import { TrackInGoogle } from "./track-in-google";

const STATUS = {
  configured: true, connected: true, state: "active", email: "o@x.co", can_write: false, reauth_required: false,
  selected_property: "sc-domain:example.com", quota: null,
};

let posts: { urls: string[] }[] = [];

function api(status: object | "error", handler?: (urls: string[]) => Response) {
  posts = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.replace(/^https?:\/\/[^/]+/, "");
      if (path === "/api/v1/google/status") {
        return status === "error" ? new Response("{}", { status: 502 }) : new Response(JSON.stringify(status), { status: 200 });
      }
      if (path === "/api/v1/google/targets" && init?.method === "POST") {
        const body = JSON.parse(String(init.body)) as { urls: string[] };
        posts.push(body);
        return handler ? handler(body.urls) : new Response(JSON.stringify({ added: body.urls.length, skipped: [] }), { status: 200 });
      }
      return new Response("{}", { status: 404 });
    }),
  );
}

beforeEach(() => vi.spyOn(console, "error").mockImplementation(() => {}));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("Track in Google Index Status", () => {
  it("renders nothing when Google is not set up on the server (no clutter, no fake option)", async () => {
    api({ ...STATUS, configured: false, connected: false });
    const { container } = render(<TrackInGoogle urls={["https://example.com/a"]} />);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing if the Google status cannot be loaded", async () => {
    api("error");
    const { container } = render(<TrackInGoogle urls={["https://example.com/a"]} />);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it("not connected: invites the customer to connect, with no track button", async () => {
    api({ ...STATUS, connected: false, state: null, email: null, selected_property: null });
    render(<TrackInGoogle urls={["https://example.com/a"]} />);
    expect(await screen.findByRole("link", { name: "Connect Google Search Console" })).toHaveAttribute("href", "/dashboard/google");
    expect(screen.queryByRole("button", { name: "Track in Google Index Status" })).not.toBeInTheDocument();
  });

  it("expired or revoked access: asks to reconnect and offers no track button", async () => {
    api({ ...STATUS, state: "revoked", reauth_required: true });
    render(<TrackInGoogle urls={["https://example.com/a"]} />);
    expect(await screen.findByRole("link", { name: "Reconnect Google" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Track in Google Index Status" })).not.toBeInTheDocument();
  });

  it("no property chosen: sends the customer to choose one", async () => {
    api({ ...STATUS, selected_property: null });
    render(<TrackInGoogle urls={["https://example.com/a"]} />);
    expect(await screen.findByText(/Choose a Search Console property first/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Track in Google Index Status" })).not.toBeInTheDocument();
  });

  it("connected: explains what happens, then adds the URLs and links to the results", async () => {
    api(STATUS);
    render(<TrackInGoogle urls={["https://example.com/a", "https://example.com/b", "https://example.com/a"]} />);
    expect(await screen.findByText(/we ask Google directly whether they are indexed/)).toBeInTheDocument();
    expect(screen.getByText(/1, 3, 7 and 14 days/)).toBeInTheDocument();
    expect(screen.getByText(/Pages on other sites cannot be checked and are skipped/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Track in Google Index Status" }));
    expect(await screen.findByText(/2 URLs added for Google checks/)).toBeInTheDocument();
    expect(posts).toEqual([{ urls: ["https://example.com/a", "https://example.com/b"] }]); // de-duplicated, only URLs, no user id
    expect(screen.getByRole("link", { name: "See results in Google Index Status" })).toHaveAttribute("href", "/dashboard/google");
  });

  it("explains skipped URLs in plain words (other people's sites, already tracked)", async () => {
    api(STATUS, (urls) =>
      new Response(
        JSON.stringify({
          added: 1,
          skipped: urls.slice(1).map((u, i) => ({ url: u, reason: i === 0 ? "outside_property" : "duplicate" })),
        }),
        { status: 200 },
      ),
    );
    render(<TrackInGoogle urls={["https://example.com/a", "https://other.org/x", "https://example.com/dup"]} />);
    await userEvent.click(await screen.findByRole("button", { name: "Track in Google Index Status" }));
    expect(await screen.findByText(/1 URL added for Google checks\. 2 skipped\./)).toBeInTheDocument();
    expect(screen.getByText("1 skipped: Not on your Search Console property, so Google cannot report on it")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Check my backlinks" })).toHaveAttribute("href", "/dashboard/backlinks");
    expect(screen.getByText("1 skipped: Already being tracked")).toBeInTheDocument();
  });

  it("sends large batches in requests of at most 200 URLs", async () => {
    api(STATUS);
    const urls = Array.from({ length: 450 }, (_, i) => `https://example.com/p${i}`);
    render(<TrackInGoogle urls={urls} />);
    await userEvent.click(await screen.findByRole("button", { name: "Track in Google Index Status" }));
    expect(await screen.findByText(/450 URLs added for Google checks/)).toBeInTheDocument();
    expect(posts.map((p) => p.urls.length)).toEqual([200, 200, 50]);
  });

  it("shows the problem and keeps what was already added if a later request fails", async () => {
    let call = 0;
    api(STATUS, (urls) => {
      call += 1;
      return call === 1
        ? new Response(JSON.stringify({ added: urls.length, skipped: [] }), { status: 200 })
        : new Response(JSON.stringify({ detail: { code: "google_reauth_required", message: "Google access was revoked or expired." } }), { status: 409 });
    });
    const urls = Array.from({ length: 300 }, (_, i) => `https://example.com/p${i}`);
    render(<TrackInGoogle urls={urls} />);
    await userEvent.click(await screen.findByRole("button", { name: "Track in Google Index Status" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Google access was revoked or expired.");
    expect(screen.getByText(/200 URLs added for Google checks/)).toBeInTheDocument();
  });

  it("the button is disabled for an empty batch", async () => {
    api(STATUS);
    render(<TrackInGoogle urls={[]} />);
    expect(await screen.findByRole("button", { name: "Track in Google Index Status" })).toBeDisabled();
  });
});
