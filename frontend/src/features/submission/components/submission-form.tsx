"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertCircle, CheckCircle2, Copy, Check } from "lucide-react";
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
import { Textarea } from "@/components/ui/textarea";
import { BatchStatusPanel } from "./batch-status";
import { useSubmitUrls } from "../hooks/use-submit-urls";
import { parseUrls } from "../lib/parse-urls";
import { useRecentBatches } from "../hooks/use-recent-batches";
import { findSocialLinks } from "../lib/social";

const MAX_URLS = 1000;

export function SubmissionForm() {
  const [raw, setRaw] = useState("");
  const [copied, setCopied] = useState(false);
  const [single, setSingle] = useState(false);
  const { submit, isLoading, error, result } = useSubmitUrls();
  const router = useRouter();
  // The batch lives in the address (?batch=...) so a refresh or a shared link reopens it; the data itself is in the database.
  const batchParam = useSearchParams().get("batch");
  const activeId = isLoading ? null : (result?.batch_id ?? batchParam);
  const recent = useRecentBatches(activeId);

  const urls = useMemo(() => parseUrls(raw), [raw]);
  const social = useMemo(() => findSocialLinks(urls), [urls]);
  const tooMany = urls.length > MAX_URLS;
  const disabled = isLoading || urls.length === 0 || tooMany;

  async function handleSubmit() {
    const res = await submit(urls);
    if (res) {
      router.replace(`/dashboard?batch=${encodeURIComponent(res.batch_id)}`);
    }
  }

  async function copyBatchId() {
    if (!activeId) return;
    try {
      await navigator.clipboard.writeText(activeId);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard unavailable
    }
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!disabled) void handleSubmit();
      }}
      className="w-full max-w-2xl"
    >
      <Card className="border border-slate-800 bg-slate-900/60 text-slate-100">
        <CardHeader>
          <CardTitle className="text-2xl font-semibold">
            QuickIndex - Bulk Backlink Submission
          </CardTitle>
          <CardDescription className="text-slate-400">
            Paste your backlinks below, one URL per line, and we will push them
            to search engines for fast indexing.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex gap-2 text-sm">
            {[false, true].map((mode) => (
              <Button
                key={String(mode)}
                type="button"
                size="sm"
                variant={single === mode ? "default" : "ghost"}
                onClick={() => {
                  setSingle(mode);
                  setRaw("");
                }}
              >
                {mode ? "Single URL" : "Bulk"}
              </Button>
            ))}
          </div>
          <Textarea
            value={raw}
            onChange={(e) =>
              setRaw(single ? e.target.value.split(/\r?\n/)[0] : e.target.value)
            }
            placeholder={
              single
                ? "https://example.com/page"
                : "https://example.com/page-1\nhttps://example.com/page-2"
            }
            rows={single ? 1 : 12}
            spellCheck={false}
            className="border-slate-700 bg-slate-950 font-mono text-sm text-slate-100 placeholder:text-slate-600 focus-visible:border-emerald-500 focus-visible:ring-emerald-500/30"
          />
          <p
            className={`text-sm ${tooMany ? "text-amber-400" : "text-slate-400"}`}
          >
            {tooMany ? (
              <>
                Warning: {urls.length.toLocaleString()} URLs exceeds the limit
                of {MAX_URLS.toLocaleString()} per submission. Remove{" "}
                {(urls.length - MAX_URLS).toLocaleString()} to continue.
              </>
            ) : (
              <>
                <span className="font-medium text-emerald-400">
                  {urls.length.toLocaleString()}
                </span>{" "}
                valid URL{urls.length === 1 ? "" : "s"} detected (max{" "}
                {MAX_URLS.toLocaleString()})
              </>
            )}
          </p>

          {social.length > 0 && (
            <Alert role="note" className="border-amber-800 bg-amber-950/40 text-amber-200">
              <AlertCircle />
              <AlertTitle>
                {social.reduce((n, g) => n + g.count, 0)} social media link{social.reduce((n, g) => n + g.count, 0) === 1 ? "" : "s"} detected
              </AlertTitle>
              <AlertDescription className="text-amber-200/80">
                <p>
                  Social platforms decide what search engines may index, and submitting cannot override that. We will still send
                  these links, but many will not be indexed.
                </p>
                <ul className="mt-1 list-disc space-y-0.5 pl-5">
                  {social.map((g) => (
                    <li key={g.platform.name}>
                      <span className="font-medium capitalize">{g.platform.name}</span> ({g.count}): {g.platform.advice}
                    </li>
                  ))}
                </ul>
                <p className="mt-1">
                  To see whether a specific link is blocked, run it through{" "}
                  <Link href="/dashboard/backlinks" className="underline underline-offset-2">
                    Check my backlinks
                  </Link>
                  .
                </p>
              </AlertDescription>
            </Alert>
          )}

          {activeId && (
            <Alert className="border-emerald-800 bg-emerald-950/50 text-emerald-300">
              <CheckCircle2 />
              <AlertTitle>{result ? "Submission accepted" : "Earlier submission"}</AlertTitle>
              <AlertDescription className="text-emerald-200/80">
                <div className="mt-1 flex items-center gap-2">
                  <span>Batch ID:</span>
                  <code className="rounded bg-slate-950 px-2 py-0.5 font-mono text-emerald-300">
                    {activeId}
                  </code>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon-xs"
                    onClick={copyBatchId}
                    aria-label="Copy batch ID"
                  >
                    {copied ? <Check /> : <Copy />}
                  </Button>
                </div>
                <div className="mt-1">
                  {result ? `${result.total} URLs queued.` : "Reopened from your earlier submission."}
                </div>
                <BatchStatusPanel batchId={activeId} />
              </AlertDescription>
            </Alert>
          )}

          {recent.length > 0 && (
            <nav aria-label="Recent submissions" className="space-y-1 pt-1">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Recent submissions</h3>
              <ul className="space-y-1">
                {recent.map((b) => (
                  <li key={b.batch_id}>
                    <Link
                      href={`/dashboard?batch=${encodeURIComponent(b.batch_id)}`}
                      aria-current={b.batch_id === activeId ? "true" : undefined}
                      className={`block rounded-md border px-3 py-1.5 text-sm transition-colors ${
                        b.batch_id === activeId
                          ? "border-emerald-700 bg-emerald-950/40 text-slate-100"
                          : "border-slate-800 bg-slate-900/40 text-slate-300 hover:bg-slate-900"
                      }`}
                    >
                      {b.total.toLocaleString()} URL{b.total === 1 ? "" : "s"}
                      {b.created_at && (
                        <span className="text-xs text-slate-500"> · {new Date(b.created_at).toLocaleString()}</span>
                      )}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          )}

          {error && (
            <Alert
              variant="destructive"
              className="border-red-900 bg-red-950/50"
            >
              <AlertCircle />
              <AlertTitle>Submission failed</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          )}
        </CardContent>
        <CardFooter>
          <Button
            type="submit"
            disabled={disabled}
            className="w-full bg-emerald-500 font-semibold text-slate-950 hover:bg-emerald-400"
          >
            {isLoading ? "Submitting..." : "Submit for Fast Indexing"}
          </Button>
        </CardFooter>
      </Card>
    </form>
  );
}
