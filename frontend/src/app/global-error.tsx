"use client";

import { ErrorScreen } from "@/components/error-screen";

// Replaces the root layout when it crashes, so it brings its own <html> and <body> (and the dark colours, which the layout would have set).
export default function GlobalError({ error, retry }: { error: unknown; retry: () => void }) {
  return (
    <html lang="en" className="dark">
      <body style={{ background: "#020617", color: "#f1f5f9", fontFamily: "system-ui, sans-serif", margin: 0 }}>
        <ErrorScreen error={error} retry={retry} scope="app crashed" />
      </body>
    </html>
  );
}
