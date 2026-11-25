"use client";

import { useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AlertCircle, CheckCircle2 } from "lucide-react";
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
import { account } from "@/lib/appwrite";
import { RESET_LINK_INVALID, resetMessage } from "@/lib/auth-errors";

const inputClass =
  "h-9 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100 placeholder:text-slate-600 outline-none focus-visible:border-emerald-500 focus-visible:ring-3 focus-visible:ring-emerald-500/30";

export function ResetPasswordForm() {
  const params = useSearchParams();
  // The one-time secret stays in the URL/memory only: it is never rendered, logged or stored.
  const userId = params.get("userId");
  const secret = params.get("secret");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!userId || !secret) {
    return (
      <Shell title="Reset link problem">
        <Alert variant="destructive" className="border-red-900 bg-red-950/50">
          <AlertCircle />
          <AlertTitle>Cannot reset password</AlertTitle>
          <AlertDescription>{RESET_LINK_INVALID}</AlertDescription>
        </Alert>
        <p className="text-sm text-slate-400">
          <Link href="/forgot-password" className="text-emerald-400 underline underline-offset-2">
            Request a new reset link
          </Link>
        </p>
      </Shell>
    );
  }

  if (done) {
    return (
      <Shell title="Password updated">
        <Alert className="border-emerald-800 bg-emerald-950/50 text-emerald-300" role="status">
          <CheckCircle2 />
          <AlertTitle>Your password has been changed</AlertTitle>
          <AlertDescription className="text-emerald-200/80">
            You can now sign in with your new password.
          </AlertDescription>
        </Alert>
        <Link href="/login" className="text-sm text-emerald-400 underline underline-offset-2">
          Go to sign in
        </Link>
      </Shell>
    );
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirm) {
      setError("The two passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      await account.updateRecovery({ userId: userId!, secret: secret!, password });
      setDone(true);
    } catch (err) {
      setError(resetMessage(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="w-full max-w-sm">
      <Card className="border border-slate-800 bg-slate-900/60 text-slate-100">
        <CardHeader>
          <CardTitle className="text-xl font-semibold">Choose a new password</CardTitle>
          <CardDescription className="text-slate-400">At least 8 characters.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="space-y-1">
            <label htmlFor="new-password" className="block text-sm text-slate-300">
              New password
            </label>
            <input
              id="new-password"
              type="password"
              required
              className={inputClass}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
            />
          </div>
          <div className="space-y-1">
            <label htmlFor="confirm-password" className="block text-sm text-slate-300">
              Confirm new password
            </label>
            <input
              id="confirm-password"
              type="password"
              required
              className={inputClass}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              autoComplete="new-password"
            />
          </div>
          {error && (
            <Alert variant="destructive" className="border-red-900 bg-red-950/50">
              <AlertCircle />
              <AlertTitle>Could not change password</AlertTitle>
              <AlertDescription>
                {error}
                {error === RESET_LINK_INVALID && (
                  <>
                    {" "}
                    <Link href="/forgot-password" className="underline underline-offset-2">
                      Request a new link
                    </Link>
                  </>
                )}
              </AlertDescription>
            </Alert>
          )}
        </CardContent>
        <CardFooter>
          <Button
            type="submit"
            disabled={busy}
            className="w-full bg-emerald-500 font-semibold text-slate-950 hover:bg-emerald-400"
          >
            {busy ? "Please wait…" : "Change password"}
          </Button>
        </CardFooter>
      </Card>
    </form>
  );
}

function Shell({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <Card className="w-full max-w-sm border border-slate-800 bg-slate-900/60 text-slate-100">
      <CardHeader>
        <CardTitle className="text-xl font-semibold">{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">{children}</CardContent>
    </Card>
  );
}
