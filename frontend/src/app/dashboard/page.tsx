import { SubmissionForm } from "@/features/submission/components/submission-form";

// The dashboard is behind a client-side sign-in check (Appwrite session in the browser), so the server can only prerender a loading
// shell. Next.js's development-only "instant navigation" validation cannot see the real page and reports it as dropped. Opting out
// is the documented fix for routes that depend on the session; it changes nothing in production behaviour.
export const instant = false;

export default function DashboardPage() {
  return (
    <main className="flex flex-1 items-center justify-center bg-slate-950 px-4 py-12">
      <SubmissionForm />
    </main>
  );
}
