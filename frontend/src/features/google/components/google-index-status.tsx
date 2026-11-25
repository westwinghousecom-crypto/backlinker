"use client";

import { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { AlertCircle } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { useGoogleStatus } from "../hooks/use-google-status";
import { CALLBACK_MESSAGES } from "../lib/labels";
import { ConnectionCard } from "./connection-card";
import { PropertyPicker } from "./property-picker";
import { SitemapsPanel } from "./sitemaps-panel";
import { TargetsPanel } from "./targets-panel";

type Notice = { tone: "success" | "error"; text: string };

function noticeFrom(params: URLSearchParams): Notice | null {
  const err = params.get("google_error");
  if (err) {
    return (
      CALLBACK_MESSAGES[err] ?? {
        tone: "error",
        text: "Google could not complete the connection. Please try again.",
      }
    );
  }
  return params.get("connected") === "1" ? CALLBACK_MESSAGES.connected : null;
}

/** Page container: connection, property, Google Index Status, sitemaps. */
export function GoogleIndexStatusPage() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const { status, error, refresh } = useGoogleStatus();
  // The callback arrives as a full page load, so the outcome is read once, then the query string is cleared
  // so a reload does not repeat it.
  const [notice] = useState<Notice | null>(() => noticeFrom(params));
  useEffect(() => {
    if (params.get("connected") || params.get("google_error")) router.replace(pathname);
  }, [params, pathname, router]);

  const onReauth = useCallback(() => refresh(), [refresh]);
  const [needProperty, setNeedProperty] = useState(false);

  const active = Boolean(status?.configured && status.connected && status.state === "active" && !status.reauth_required);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-100">Google Index Status</h1>
        <p className="text-sm text-slate-400">
          Ask Google directly whether your own pages are indexed, and watch the answer change over time.
        </p>
      </div>

      {error && !status && (
        <Alert variant="destructive" className="border-red-900 bg-red-950/50">
          <AlertCircle />
          <AlertTitle>Could not load Google status</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {!status && !error && <p className="text-sm text-slate-400">Loading…</p>}

      {status && <ConnectionCard status={status} notice={notice} onChanged={refresh} />}

      {status && active && (
        <>
          <PropertyPicker
            selected={status.selected_property}
            onSelected={() => {
              setNeedProperty(false);
              refresh();
            }}
            onReauth={onReauth}
          />
          {needProperty && !status.selected_property && (
            <p role="alert" className="text-sm text-amber-300">
              Choose a Search Console property above to continue.
            </p>
          )}
          {status.selected_property && (
            <>
              <TargetsPanel
                property={status.selected_property}
                quota={status.quota}
                onReauth={onReauth}
                onNeedProperty={() => setNeedProperty(true)}
              />
              <SitemapsPanel property={status.selected_property} onReauth={onReauth} />
            </>
          )}
        </>
      )}
    </div>
  );
}
