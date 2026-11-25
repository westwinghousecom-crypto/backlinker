"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { AlertCircle, CheckCircle2 } from "lucide-react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { account } from "@/lib/appwrite";
import { VERIFY_LINK_INVALID, verifyMessage } from "@/lib/auth-errors";

type State = { kind: "verifying" } | { kind: "success" } | { kind: "failed"; message: string };

export function VerifyEmailView() {
  const params = useSearchParams();
  const userId = params.get("userId");
  const secret = params.get("secret");
  const missing = !userId || !secret;
  const [state, setState] = useState<State>({ kind: "verifying" });

  useEffect(() => {
    if (!userId || !secret) return;
    let cancelled = false;
    account
      .updateVerification({ userId, secret })
      .then(() => {
        if (!cancelled) setState({ kind: "success" });
      })
      .catch((err) => {
        if (!cancelled) setState({ kind: "failed", message: verifyMessage(err) });
      });
    return () => {
      cancelled = true;
    };
  }, [userId, secret]);

  const view: State = missing ? { kind: "failed", message: VERIFY_LINK_INVALID } : state;

  return (
    <Card className="w-full max-w-sm border border-slate-800 bg-slate-900/60 text-slate-100">
      <CardHeader>
        <CardTitle className="text-xl font-semibold">Verify your email</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {view.kind === "verifying" && (
          <p role="status" className="text-sm text-slate-400">
            Verifying your email address…
          </p>
        )}
        {view.kind === "success" && (
          <>
            <Alert className="border-emerald-800 bg-emerald-950/50 text-emerald-300" role="status">
              <CheckCircle2 />
              <AlertTitle>Email verified</AlertTitle>
              <AlertDescription className="text-emerald-200/80">
                Thank you. Your email address is now confirmed.
              </AlertDescription>
            </Alert>
            <Link href="/dashboard" className="text-sm text-emerald-400 underline underline-offset-2">
              Go to the dashboard
            </Link>
          </>
        )}
        {view.kind === "failed" && (
          <>
            <Alert variant="destructive" className="border-red-900 bg-red-950/50">
              <AlertCircle />
              <AlertTitle>Could not verify</AlertTitle>
              <AlertDescription>{view.message}</AlertDescription>
            </Alert>
            <p className="text-sm text-slate-400">
              <Link href="/login?next=%2Fdashboard" className="text-emerald-400 underline underline-offset-2">
                Sign in
              </Link>{" "}
              and use “Resend verification email” at the top of the dashboard to get a fresh link.
            </p>
          </>
        )}
      </CardContent>
    </Card>
  );
}
