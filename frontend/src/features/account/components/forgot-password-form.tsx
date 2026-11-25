"use client";

import { useState } from "react";
import Link from "next/link";
import { AlertCircle, MailCheck } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useCooldown } from "@/hooks/use-cooldown";
import { RECOVERY_NEUTRAL_MESSAGE, requestRecovery } from "../api";

const inputClass =
  "h-9 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100 placeholder:text-slate-600 outline-none focus-visible:border-emerald-500 focus-visible:ring-3 focus-visible:ring-emerald-500/30";

export function ForgotPasswordForm() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cooldown = useCooldown(60);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (busy || cooldown.active) return;
    setBusy(true);
    setError(null);
    try {
      await requestRecovery(email.trim());
      setSent(true); // the same screen no matter whether the account exists
      cooldown.start();
    } catch (err) {
      setSent(false);
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  const disabled = busy || cooldown.active;
  return (
    <form onSubmit={submit} className="w-full max-w-sm">
      <Card className="border border-slate-800 bg-slate-900/60 text-slate-100">
        <CardHeader>
          <CardTitle className="text-xl font-semibold">Reset your password</CardTitle>
          <CardDescription className="text-slate-400">
            Enter your email address and we will send you a link to choose a new password.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1">
            <label htmlFor="email" className="block text-sm text-slate-300">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              className={inputClass}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="email"
            />
          </div>
          {sent && (
            <Alert className="border-emerald-800 bg-emerald-950/50 text-emerald-300" role="status">
              <MailCheck />
              <AlertTitle>Check your email</AlertTitle>
              <AlertDescription className="text-emerald-200/80">{RECOVERY_NEUTRAL_MESSAGE}</AlertDescription>
            </Alert>
          )}
          {error && (
            <Alert variant="destructive" className="border-red-900 bg-red-950/50">
              <AlertCircle />
              <AlertTitle>Could not send the email</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </CardContent>
        <CardFooter className="flex-col gap-3">
          <Button
            type="submit"
            disabled={disabled}
            className="w-full bg-emerald-500 font-semibold text-slate-950 hover:bg-emerald-400"
          >
            {busy
              ? "Please wait…"
              : cooldown.active
                ? `Send again in ${cooldown.remaining}s`
                : sent
                  ? "Send again"
                  : "Send reset link"}
          </Button>
          <p className="text-sm text-slate-400">
            Remembered it?{" "}
            <Link href="/login" className="text-emerald-400 underline underline-offset-2">
              Sign in
            </Link>
          </p>
        </CardFooter>
      </Card>
    </form>
  );
}
