"use client";

import { useMemo, useState } from "react";
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
import { Textarea } from "@/components/ui/textarea";
import { parseUrls } from "@/features/submission/lib/parse-urls";
import { createCheckBatch } from "../api/check-api";

export const MAX_URLS = 1000;

export function CheckForm({ onCreated }: { onCreated: (batchId: string) => void }) {
  const [raw, setRaw] = useState("");
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const urls = useMemo(() => parseUrls(raw), [raw]);
  const tooMany = urls.length > MAX_URLS;
  const disabled = busy || urls.length === 0 || tooMany;

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const res = await createCheckBatch({
        urls,
        target: target.trim() || undefined,
      });
      setRaw("");
      onCreated(res.batch_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!disabled) void submit();
      }}
    >
      <Card className="border border-slate-800 bg-slate-900/60 text-slate-100">
        <CardHeader>
          <CardTitle className="text-xl font-semibold">Check my backlinks</CardTitle>
          <CardDescription className="text-slate-400">
            Paste the pages that link to you. We check whether Google can crawl
            and index each page, and whether your link is really there.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <label className="block text-sm text-slate-300" htmlFor="target">
            Your website <span className="text-slate-500">(optional, needed to find your link)</span>
          </label>
          <input
            id="target"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            placeholder="https://your-site.com"
            inputMode="url"
            autoComplete="off"
            className="h-9 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100 placeholder:text-slate-600 outline-none focus-visible:border-emerald-500 focus-visible:ring-3 focus-visible:ring-emerald-500/30"
          />
          <label className="block text-sm text-slate-300" htmlFor="urls">
            Backlink pages (one URL per line)
          </label>
          <Textarea
            id="urls"
            value={raw}
            onChange={(e) => setRaw(e.target.value)}
            placeholder={"https://blog.example.com/post-1\nhttps://news.example.org/article"}
            rows={8}
            spellCheck={false}
            className="border-slate-700 bg-slate-950 font-mono text-sm text-slate-100 placeholder:text-slate-600 focus-visible:border-emerald-500 focus-visible:ring-emerald-500/30"
          />
          <p className={`text-sm ${tooMany ? "text-amber-400" : "text-slate-400"}`}>
            {tooMany ? (
              <>
                {urls.length.toLocaleString()} URLs is over the limit of{" "}
                {MAX_URLS.toLocaleString()} per batch. Remove{" "}
                {(urls.length - MAX_URLS).toLocaleString()} to continue.
              </>
            ) : (
              <>
                <span className="font-medium text-emerald-400">
                  {urls.length.toLocaleString()}
                </span>{" "}
                URL{urls.length === 1 ? "" : "s"} detected (max {MAX_URLS.toLocaleString()})
              </>
            )}
          </p>
          {error && (
            <Alert variant="destructive" className="border-red-900 bg-red-950/50">
              <AlertCircle />
              <AlertTitle>Could not start the check</AlertTitle>
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
            {busy ? "Starting…" : "Check these backlinks"}
          </Button>
        </CardFooter>
      </Card>
    </form>
  );
}
