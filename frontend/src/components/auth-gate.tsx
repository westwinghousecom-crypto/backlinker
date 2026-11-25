"use client";

import { useEffect, type ReactNode } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth";

/** Sends signed-out visitors to /login. This is a convenience only: the API enforces access on every call. */
export function AuthGate({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const search = useSearchParams().toString();

  useEffect(() => {
    if (status === "anonymous") {
      const here = search ? `${pathname}?${search}` : pathname;
      router.replace(`/login?next=${encodeURIComponent(here)}`);
    }
  }, [status, router, pathname, search]);

  if (status !== "authenticated") {
    return (
      <p role="status" className="p-8 text-center text-sm text-slate-400">
        {status === "loading" ? "Loading…" : "Redirecting to sign in…"}
      </p>
    );
  }
  return <>{children}</>;
}
