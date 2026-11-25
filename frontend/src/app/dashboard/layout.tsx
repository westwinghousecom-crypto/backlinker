import { Suspense } from "react";
import { AppNav } from "@/components/app-nav";
import { AuthGate } from "@/components/auth-gate";
import { UnverifiedBanner } from "@/components/unverified-banner";

// The dashboard is behind a client-side sign-in check (Appwrite session in the browser), so the server can only prerender a loading
// shell. Next.js's development-only "instant navigation" validation cannot see the real page and reports it as dropped. Opting out
// is the documented fix for routes that depend on the session; it changes nothing in production behaviour.
export const instant = false;

export default function DashboardLayout({ children }: LayoutProps<"/dashboard">) {
  return (
    <Suspense fallback={null}>
      <AuthGate>
        <AppNav />
        <UnverifiedBanner />
        {children}
      </AuthGate>
    </Suspense>
  );
}
