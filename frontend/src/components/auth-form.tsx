"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertCircle } from "lucide-react";
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
import { useAuth } from "@/lib/auth";
import { safeNext } from "@/lib/auth-errors";

const inputClass =
  "h-9 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100 placeholder:text-slate-600 outline-none focus-visible:border-emerald-500 focus-visible:ring-3 focus-visible:ring-emerald-500/30";

export function AuthForm({ mode }: { mode: "login" | "register" }) {
  const { status, login, register } = useAuth();
  const router = useRouter();
  const next = safeNext(useSearchParams().get("next"));
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isRegister = mode === "register";

  useEffect(() => {
    if (status === "authenticated") router.replace(next);
  }, [status, next, router]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (isRegister && password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    setBusy(true);
    try {
      if (isRegister) {
        await register(name.trim() || email.split("@")[0], email.trim(), password);
      } else {
        await login(email.trim(), password);
      }
      router.replace(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setBusy(false);
    }
  }

  const other = isRegister ? "/login" : "/register";
  const otherHref = next === "/dashboard" ? other : `${other}?next=${encodeURIComponent(next)}`;

  return (
    <form onSubmit={submit} className="w-full max-w-sm">
      <Card className="border border-slate-800 bg-slate-900/60 text-slate-100">
        <CardHeader>
          <CardTitle className="text-xl font-semibold">
            {isRegister ? "Create your account" : "Sign in to QuickIndex"}
          </CardTitle>
          <CardDescription className="text-slate-400">
            {isRegister
              ? "Your submissions and results stay private to your account."
              : "Welcome back. Your batches and results are waiting."}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {isRegister && (
            <div className="space-y-1">
              <label htmlFor="name" className="block text-sm text-slate-300">
                Name
              </label>
              <input
                id="name"
                className={inputClass}
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoComplete="name"
              />
            </div>
          )}
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
          <div className="space-y-1">
            <label htmlFor="password" className="block text-sm text-slate-300">
              Password{isRegister && <span className="text-slate-500"> (8+ characters)</span>}
            </label>
            <input
              id="password"
              type="password"
              required
              className={inputClass}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={isRegister ? "new-password" : "current-password"}
            />
            {!isRegister && (
              <p className="pt-1 text-right text-xs">
                <Link href="/forgot-password" className="text-emerald-400 underline underline-offset-2">
                  Forgot password?
                </Link>
              </p>
            )}
          </div>
          {error && (
            <Alert variant="destructive" className="border-red-900 bg-red-950/50">
              <AlertCircle />
              <AlertTitle>{isRegister ? "Could not create account" : "Could not sign in"}</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </CardContent>
        <CardFooter className="flex-col gap-3">
          <Button
            type="submit"
            disabled={busy}
            className="w-full bg-emerald-500 font-semibold text-slate-950 hover:bg-emerald-400"
          >
            {busy ? "Please wait…" : isRegister ? "Create account" : "Sign in"}
          </Button>
          <p className="text-sm text-slate-400">
            {isRegister ? "Already have an account?" : "New to QuickIndex?"}{" "}
            <Link href={otherHref} className="text-emerald-400 underline underline-offset-2">
              {isRegister ? "Sign in" : "Create an account"}
            </Link>
          </p>
          <p className="text-xs text-slate-500">
            By continuing you agree to the{" "}
            <Link href="/terms" className="underline underline-offset-2 hover:text-slate-300">
              Terms
            </Link>{" "}
            and{" "}
            <Link href="/privacy" className="underline underline-offset-2 hover:text-slate-300">
              Privacy Policy
            </Link>
            .
          </p>
        </CardFooter>
      </Card>
    </form>
  );
}
