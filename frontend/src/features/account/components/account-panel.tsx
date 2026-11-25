"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { AlertCircle, CheckCircle2 } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { deleteGoogleData } from "@/features/google/api/google-api";
import { requestText } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { downloadFile } from "@/lib/download";
import { deleteAccount } from "../api";

const CONFIRM_WORD = "DELETE";

type Note = { tone: "ok" | "error"; text: string } | null;

function NoteAlert({ note }: { note: Note }) {
  if (!note) return null;
  return note.tone === "ok" ? (
    <Alert className="border-emerald-800 bg-emerald-950/50 text-emerald-300">
      <CheckCircle2 />
      <AlertDescription>{note.text}</AlertDescription>
    </Alert>
  ) : (
    <Alert variant="destructive" className="border-red-900 bg-red-950/50">
      <AlertCircle />
      <AlertDescription>{note.text}</AlertDescription>
    </Alert>
  );
}

export function AccountPanel() {
  const { user, logout } = useAuth();
  const router = useRouter();
  const [exportNote, setExportNote] = useState<Note>(null);
  const [googleNote, setGoogleNote] = useState<Note>(null);
  const [deleteNote, setDeleteNote] = useState<Note>(null);
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState<"export" | "google" | "delete" | null>(null);

  async function exportData() {
    setBusy("export");
    setExportNote(null);
    try {
      const text = await requestText("/api/v1/account/export");
      const day = new Date().toISOString().slice(0, 10).replace(/-/g, "");
      downloadFile(`quickindex-export-${day}.json`, text);
      setExportNote({ tone: "ok", text: "Your data was downloaded. The Google refresh token is never included." });
    } catch (e) {
      setExportNote({ tone: "error", text: e instanceof Error ? e.message : "Could not export your data." });
    } finally {
      setBusy(null);
    }
  }

  async function eraseGoogle() {
    if (!window.confirm("Disconnect Google and permanently delete your tracked URLs and inspection history?")) return;
    setBusy("google");
    setGoogleNote(null);
    try {
      await deleteGoogleData();
      setGoogleNote({ tone: "ok", text: "Google was disconnected and your Google data was deleted." });
    } catch (e) {
      setGoogleNote({ tone: "error", text: e instanceof Error ? e.message : "Could not delete your Google data." });
    } finally {
      setBusy(null);
    }
  }

  async function eraseAccount() {
    if (typed !== CONFIRM_WORD) return;
    setBusy("delete");
    setDeleteNote(null);
    try {
      await deleteAccount();
    } catch (e) {
      setDeleteNote({ tone: "error", text: e instanceof Error ? e.message : "Deleting your account did not finish." });
      setBusy(null);
      return;
    }
    await logout(); // the session is already invalid; this just clears this browser
    router.replace("/goodbye");
  }

  return (
    <div className="mx-auto w-full max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-100">Account</h1>
        <p className="text-sm text-slate-400">
          Signed in as <span className="text-slate-200">{user?.email}</span>. See the{" "}
          <Link href="/privacy" className="text-emerald-400 underline underline-offset-2">
            Privacy Policy
          </Link>{" "}
          and{" "}
          <Link href="/terms" className="text-emerald-400 underline underline-offset-2">
            Terms
          </Link>
          .
        </p>
      </div>

      <Card className="border border-slate-800 bg-slate-900/60 text-slate-100">
        <CardHeader>
          <CardTitle>Export my data</CardTitle>
          <CardDescription className="text-slate-400">
            Download everything QuickIndex stores about you (submissions, backlink checks, Google tracked URLs and
            history) as one file. You can export up to 3 times per hour.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <NoteAlert note={exportNote} />
          <Button type="button" variant="outline" onClick={exportData} disabled={busy !== null}>
            {busy === "export" ? "Preparing…" : "Export my data"}
          </Button>
        </CardContent>
      </Card>

      <Card className="border border-slate-800 bg-slate-900/60 text-slate-100">
        <CardHeader>
          <CardTitle>Delete Google data</CardTitle>
          <CardDescription className="text-slate-400">
            Disconnects Google Search Console (access is revoked at Google) and erases your tracked URLs and inspection
            history. Your account and other data stay.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <NoteAlert note={googleNote} />
          <Button type="button" variant="outline" onClick={eraseGoogle} disabled={busy !== null} className="text-red-400">
            Delete Google data
          </Button>
        </CardContent>
      </Card>

      <Card className="border border-red-900/60 bg-slate-900/60 text-slate-100">
        <CardHeader>
          <CardTitle className="text-red-300">Delete account</CardTitle>
          <CardDescription className="text-slate-400">
            Permanently erases your submissions, backlink checks and results, public-feed settings, Google connection,
            tracked URLs and history, and then removes your account. This cannot be undone. Encrypted backups may keep a
            copy until they expire.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <NoteAlert note={deleteNote} />
          <label htmlFor="confirm-delete" className="block text-sm text-slate-300">
            Type <strong>{CONFIRM_WORD}</strong> to confirm
          </label>
          <input
            id="confirm-delete"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            autoComplete="off"
            className="h-9 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100 outline-none focus-visible:border-red-500 focus-visible:ring-3 focus-visible:ring-red-500/30"
          />
          <Button
            type="button"
            onClick={eraseAccount}
            disabled={typed !== CONFIRM_WORD || busy !== null}
            className="bg-red-600 font-semibold text-white hover:bg-red-500"
          >
            {busy === "delete" ? "Deleting…" : "Delete my account"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

