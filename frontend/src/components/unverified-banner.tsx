"use client";

import { useState } from "react";
import { MailWarning } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useCooldown } from "@/hooks/use-cooldown";
import { request } from "@/lib/api";
import { useAuth } from "@/lib/auth";

interface ResendResponse {
  message: string;
  already_verified: boolean;
}

/** Shown to signed-in customers whose email address is not verified yet. */
export function UnverifiedBanner() {
  const { user } = useAuth();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<{ tone: "ok" | "error"; text: string } | null>(null);
  const [verified, setVerified] = useState(false);
  const cooldown = useCooldown(60);

  if (!user || user.emailVerified || verified) return null;

  async function resend() {
    if (busy || cooldown.active) return;
    setBusy(true);
    setNote(null);
    try {
      const res = await request<ResendResponse>("/api/v1/account/verification", { method: "POST" });
      if (res.already_verified) {
        setVerified(true);
        return;
      }
      setNote({ tone: "ok", text: res.message });
      cooldown.start();
    } catch (e) {
      setNote({ tone: "error", text: e instanceof Error ? e.message : "Could not send the email." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div role="region" aria-label="Email verification" className="border-b border-amber-900/60 bg-amber-950/40">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-3 gap-y-2 px-4 py-2 text-sm text-amber-200">
        <MailWarning className="size-4 shrink-0" />
        <span>Please verify your email address.</span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={resend}
          disabled={busy || cooldown.active}
          className="border-amber-800 bg-transparent text-amber-100 hover:bg-amber-900/40"
        >
          {busy
            ? "Sending…"
            : cooldown.active
              ? `Resend in ${cooldown.remaining}s`
              : "Resend verification email"}
        </Button>
        {note && (
          <span role={note.tone === "error" ? "alert" : "status"} className={note.tone === "error" ? "text-red-300" : "text-emerald-300"}>
            {note.text}
          </span>
        )}
      </div>
    </div>
  );
}
