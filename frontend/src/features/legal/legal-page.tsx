import Link from "next/link";
import { Markdown } from "./markdown";

export const DRAFT_BANNER = "DRAFT: requires legal review before launch";

/** Public page for a legal document. The banner stays until a lawyer has approved the text and it is removed on purpose. */
export function LegalPage({ source, other }: { source: string; other: { href: string; label: string } }) {
  return (
    <main className="mx-auto w-full max-w-3xl flex-1 px-4 py-10">
      <div
        role="note"
        className="mb-6 rounded-lg border border-amber-700 bg-amber-950/50 px-4 py-3 text-sm font-semibold text-amber-200"
      >
        {DRAFT_BANNER}
      </div>
      <Markdown source={source} />
      <p className="mt-8 border-t border-slate-800 pt-4 text-sm text-slate-400">
        <Link href={other.href} className="text-emerald-400 underline underline-offset-2">
          {other.label}
        </Link>
        {" · "}
        <Link href="/dashboard" className="text-emerald-400 underline underline-offset-2">
          Back to QuickIndex
        </Link>
      </p>
    </main>
  );
}
