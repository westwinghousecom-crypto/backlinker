"use client";

import { useState } from "react";
import { AlertCircle, CheckCircle2 } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { beginConnect, deleteGoogleData, disconnectGoogle } from "../api/google-api";
import type { GoogleStatus } from "../types";

export function ConnectionCard({
  status,
  notice,
  onChanged,
}: {
  status: GoogleStatus;
  notice: { tone: "success" | "error"; text: string } | null;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const revoked = status.connected && (status.reauth_required || status.state === "revoked");

  async function connect() {
    setBusy(true);
    setError(null);
    try {
      await beginConnect(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the connection.");
      setBusy(false);
    }
  }

  async function disconnect() {
    if (!window.confirm("Disconnect Google Search Console? Scheduled rechecks will stop.")) return;
    setBusy(true);
    setError(null);
    try {
      await disconnectGoogle();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not disconnect.");
    } finally {
      setBusy(false);
    }
  }

  async function eraseData() {
    if (
      !window.confirm(
        "Disconnect Google and permanently delete all your tracked URLs and inspection history? This cannot be undone.",
      )
    )
      return;
    setBusy(true);
    setError(null);
    try {
      await deleteGoogleData();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not delete your Google data.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="border border-slate-800 bg-slate-900/60 text-slate-100">
      <CardHeader>
        <CardTitle className="text-xl font-semibold">Google Search Console</CardTitle>
        <CardDescription className="text-slate-400">
          Connect your Google account to ask Google directly whether your own pages are indexed.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {notice && (
          <Alert
            variant={notice.tone === "error" ? "destructive" : "default"}
            className={
              notice.tone === "error"
                ? "border-red-900 bg-red-950/50"
                : "border-emerald-800 bg-emerald-950/50 text-emerald-300"
            }
          >
            {notice.tone === "error" ? <AlertCircle /> : <CheckCircle2 />}
            <AlertDescription>{notice.text}</AlertDescription>
          </Alert>
        )}
        {error && (
          <Alert variant="destructive" className="border-red-900 bg-red-950/50">
            <AlertCircle />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {!status.configured ? (
          <p className="text-sm text-slate-300">Google integration is not set up on this server yet.</p>
        ) : !status.connected ? (
          <>
            <p className="text-sm text-slate-300">
              We ask for read-only access to your Search Console data; we never change anything unless you
              later grant write access (only needed to submit sitemaps). You can disconnect at any time.
            </p>
            <Button
              type="button"
              onClick={connect}
              disabled={busy}
              className="bg-emerald-500 font-semibold text-slate-950 hover:bg-emerald-400"
            >
              {busy ? "Redirecting to Google…" : "Connect Google Search Console"}
            </Button>
          </>
        ) : (
          <>
            {revoked && (
              <Alert variant="destructive" className="border-red-900 bg-red-950/50">
                <AlertCircle />
                <AlertTitle>Google access was revoked or expired. Reconnect</AlertTitle>
                <AlertDescription>
                  <p>
                    Checks are paused until you reconnect. Your tracked URLs and history are kept.
                  </p>
                  <Button type="button" size="sm" className="mt-2" onClick={connect} disabled={busy}>
                    Reconnect Google
                  </Button>
                </AlertDescription>
              </Alert>
            )}
            <dl className="grid gap-3 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-xs uppercase tracking-wide text-slate-500">Google account</dt>
                <dd className="break-all text-slate-200">{status.email ?? "Connected"}</dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-slate-500">Access level</dt>
                <dd className="text-slate-200">{status.can_write ? "Read & write" : "Read-only"}</dd>
              </div>
            </dl>
            <div className="flex flex-wrap items-center gap-2">
              <Button type="button" variant="ghost" size="sm" onClick={disconnect} disabled={busy} className="text-red-400">
                Disconnect
              </Button>
              <Button type="button" variant="ghost" size="sm" onClick={eraseData} disabled={busy} className="text-red-400">
                Delete my Google data
              </Button>
            </div>
            <p className="text-xs text-slate-500">
              Disconnect stops checks and revokes our access but keeps your history. Delete my Google data also
              erases your tracked URLs and inspection history.
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
