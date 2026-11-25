import { PublicReportPageContent } from "@/features/backlink-check/components/public-report-page";

// This route reads a dynamic `params` value and fetches per-batch data at request time, so it cannot be statically
// prerendered under Cache Components; same fix used by the dashboard pages for the same reason. `instant` is a route
// segment config, so (unlike PublicReportPageContent) this file must stay a Server Component, not "use client".
export const instant = false;

// A Server Component can simply `await` the dynamic params directly; no `use()` needed here (that's only for Client
// Components). All the real behaviour lives in the client component below, tested directly with a plain `batchId`.
export default async function PublicReportPage({ params }: { params: Promise<{ batchId: string }> }) {
  const { batchId } = await params;
  return <PublicReportPageContent batchId={batchId} />;
}
