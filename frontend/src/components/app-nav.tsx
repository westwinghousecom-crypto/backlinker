"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";

const TABS = [
  { href: "/dashboard", label: "Submit for indexing" },
  { href: "/dashboard/backlinks", label: "Check my backlinks" },
  { href: "/dashboard/google", label: "Google Index Status" },
] as const;

export function AppNav() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();

  async function signOut() {
    await logout();
    router.replace("/login");
  }

  return (
    <header className="border-b border-slate-800 bg-slate-950/80">
      <nav
        aria-label="Main"
        className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-1 gap-y-1 px-4 py-2"
      >
        <span className="mr-3 shrink-0 text-sm font-semibold text-emerald-400">QuickIndex</span>
        <div className="order-3 flex w-full flex-wrap gap-1 sm:order-none sm:w-auto">
        {TABS.map((t) => {
          const active = pathname === t.href;
          return (
            <Link
              key={t.href}
              href={t.href}
              aria-current={active ? "page" : undefined}
              className={`shrink-0 rounded-lg px-3 py-1.5 text-sm transition-colors ${
                active
                  ? "bg-slate-800 text-slate-100"
                  : "text-slate-400 hover:bg-slate-900 hover:text-slate-100"
              }`}
            >
              {t.label}
            </Link>
          );
        })}
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-2 pl-3">
          {user && (
            <span
              className="hidden max-w-48 truncate text-sm text-slate-400 sm:inline"
              title={user.email}
            >
              {user.email}
            </span>
          )}
          <Link
            href="/dashboard/account"
            aria-current={pathname === "/dashboard/account" ? "page" : undefined}
            className={`rounded-lg px-3 py-1.5 text-sm transition-colors ${
              pathname === "/dashboard/account"
                ? "bg-slate-800 text-slate-100"
                : "text-slate-400 hover:bg-slate-900 hover:text-slate-100"
            }`}
          >
            Account
          </Link>
          <Button type="button" variant="ghost" size="sm" onClick={signOut}>
            <LogOut /> Sign out
          </Button>
        </div>
      </nav>
    </header>
  );
}
