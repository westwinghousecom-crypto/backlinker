import Link from "next/link";

export const metadata = { title: "Account deleted · QuickIndex" };

export default function GoodbyePage() {
  return (
    <main className="flex flex-1 items-center justify-center px-4 py-12">
      <div className="max-w-md space-y-3 text-center">
        <h1 className="text-2xl font-semibold text-slate-100">Your account has been deleted</h1>
        <p className="text-sm text-slate-400">
          We revoked access to Google (if you had connected it) and erased the data we stored about you. Encrypted
          backups may keep a copy until they expire, as described in the{" "}
          <Link href="/privacy" className="text-emerald-400 underline underline-offset-2">
            Privacy Policy
          </Link>
          .
        </p>
        <Link href="/register" className="text-sm text-emerald-400 underline underline-offset-2">
          Create a new account
        </Link>
      </div>
    </main>
  );
}
