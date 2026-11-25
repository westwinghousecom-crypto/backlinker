import { Suspense } from "react";
import { GoogleIndexStatusPage } from "@/features/google/components/google-index-status";

// The dashboard is behind a client-side sign-in check (Appwrite session in the browser), so the server can only prerender a loading
// shell. Next.js's development-only "instant navigation" validation cannot see the real page and reports it as dropped. Opting out
// is the documented fix for routes that depend on the session; it changes nothing in production behaviour.
export const instant = false;

export const metadata = { title: "Google Index Status · QuickIndex" };

export default function GooglePage() {
  return (
    <main className="mx-auto w-full max-w-7xl flex-1 bg-slate-950 px-4 py-8">
      <Suspense fallback={<p className="text-sm text-slate-400">Loading…</p>}>
        <GoogleIndexStatusPage />
      </Suspense>
    </main>
  );
}
