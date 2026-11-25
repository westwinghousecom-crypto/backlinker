"use client";

import { useEffect, useState } from "react";
import { AlertCircle } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { listProperties, selectProperty } from "../api/google-api";
import { classifyError } from "../lib/labels";
import type { GoogleProperty } from "../types";

const TYPE_LABEL = { domain: "Domain", url_prefix: "URL prefix" } as const;

export function PropertyPicker({
  selected,
  onSelected,
  onReauth,
}: {
  selected: string | null;
  onSelected: (siteUrl: string) => void;
  onReauth: () => void;
}) {
  const [items, setItems] = useState<GoogleProperty[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listProperties()
      .then((r) => {
        if (!cancelled) setItems(r.properties);
      })
      .catch((e) => {
        if (cancelled) return;
        const c = classifyError(e);
        if (c.kind === "reauth") onReauth();
        setError(c.message);
      });
    return () => {
      cancelled = true;
    };
  }, [onReauth]);

  async function choose(p: GoogleProperty) {
    setBusy(p.site_url);
    setError(null);
    try {
      const res = await selectProperty(p.site_url);
      onSelected(res.selected_property);
    } catch (e) {
      const c = classifyError(e);
      if (c.kind === "reauth") onReauth();
      setError(c.message);
    } finally {
      setBusy(null);
    }
  }

  return (
    <section aria-label="Search Console property" className="space-y-3 rounded-lg border border-slate-800 bg-slate-900/60 p-4">
      <div>
        <h2 className="text-lg font-semibold text-slate-100">Choose a property</h2>
        <p className="text-sm text-slate-400">
          Google only inspects pages on a site you have verified in Search Console. A{" "}
          <strong className="text-slate-300">Domain</strong> property covers a whole domain and its subdomains; a{" "}
          <strong className="text-slate-300">URL prefix</strong> property covers one exact address and the paths below it.
        </p>
      </div>
      {error && (
        <Alert variant="destructive" className="border-red-900 bg-red-950/50">
          <AlertCircle />
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {items === null && !error && <p className="text-sm text-slate-500">Loading your properties…</p>}
      {items?.length === 0 && (
        <p className="text-sm text-slate-400">
          Google did not list any Search Console properties for this account. Add and verify your site in Search
          Console first.
        </p>
      )}
      <ul className="grid gap-2 sm:grid-cols-2">
        {items?.map((p) => {
          const active = p.site_url === selected;
          return (
            <li key={p.site_url}>
              <button
                type="button"
                disabled={!p.verified || busy !== null}
                aria-pressed={active}
                onClick={() => choose(p)}
                className={`w-full rounded-lg border px-3 py-2 text-left text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-60 ${
                  active
                    ? "border-emerald-700 bg-emerald-950/40"
                    : "border-slate-800 bg-slate-950/60 hover:bg-slate-900"
                }`}
              >
                <span className="flex flex-wrap items-center gap-2">
                  <span className="break-all font-mono text-slate-100">{p.label}</span>
                  <span className="rounded-full border border-slate-700 px-2 py-0.5 text-xs text-slate-300">
                    {TYPE_LABEL[p.type]}
                  </span>
                  {active && <span className="text-xs font-medium text-emerald-400">Selected</span>}
                </span>
                <span className="mt-0.5 block text-xs text-slate-400">
                  {p.verified
                    ? `Access: ${p.permission}`
                    : "Not verified: verify ownership in Search Console to use this property."}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
