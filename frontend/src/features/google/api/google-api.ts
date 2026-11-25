import { request } from "@/lib/api";
import type {
  AddTargetsResult,
  GoogleProperty,
  GoogleStatus,
  HistoryEntry,
  SitemapList,
  Target,
} from "../types";

const BASE = "/api/v1/google";

export const getStatus = () => request<GoogleStatus>(`${BASE}/status`);

export const requestAuthorization = (write: boolean) =>
  request<{ authorization_url: string }>(`${BASE}/connect`, {
    method: "POST",
    body: JSON.stringify({ write }),
    // The API sets a short-lived HttpOnly cookie that ties this sign-in attempt to this browser.
    credentials: "include",
  });

export const disconnectGoogle = () =>
  request<void>(`${BASE}/connection`, { method: "DELETE" });

/** Disconnect Google AND delete every tracked URL and inspection record. */
export const deleteGoogleData = () => request<void>(`${BASE}/data`, { method: "DELETE" });

export const listProperties = () =>
  request<{ properties: GoogleProperty[] }>(`${BASE}/properties`);

export const selectProperty = (site_url: string) =>
  request<{ selected_property: string }>(`${BASE}/property`, {
    method: "PUT",
    body: JSON.stringify({ site_url }),
  });

export const listTargets = () => request<{ items: Target[] }>(`${BASE}/targets`);

export const addTargets = (urls: string[]) =>
  request<AddTargetsResult>(`${BASE}/targets`, {
    method: "POST",
    body: JSON.stringify({ urls }),
  });

export const getHistory = (id: string) =>
  request<{ items: HistoryEntry[] }>(`${BASE}/targets/${encodeURIComponent(id)}/history`);

export const recheckTarget = (id: string) =>
  request<unknown>(`${BASE}/targets/${encodeURIComponent(id)}/recheck`, { method: "POST" });

export const removeTarget = (id: string) =>
  request<void>(`${BASE}/targets/${encodeURIComponent(id)}`, { method: "DELETE" });

export const listSitemaps = () => request<SitemapList>(`${BASE}/sitemaps`);

export const submitSitemap = (url: string) =>
  request<{ submitted: boolean }>(`${BASE}/sitemaps`, {
    method: "PUT",
    body: JSON.stringify({ url }),
  });

/**
 * Ask the server for a Google sign-in URL and send the browser there. The browser only ever receives this URL;
 * the Google client secret and all tokens stay on the server. We only follow URLs on Google's own sign-in host.
 */
export async function beginConnect(write: boolean): Promise<void> {
  const { authorization_url } = await requestAuthorization(write);
  let ok = false;
  try {
    const u = new URL(authorization_url);
    ok = u.protocol === "https:" && u.hostname === "accounts.google.com";
  } catch {
    ok = false;
  }
  if (!ok) throw new Error("The server returned an unexpected sign-in address. Please try again.");
  window.location.assign(authorization_url);
}
