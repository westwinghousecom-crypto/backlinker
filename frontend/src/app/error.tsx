"use client";

import { ErrorScreen } from "@/components/error-screen";

export default function Error({ error, retry }: { error: unknown; retry: () => void }) {
  return <ErrorScreen error={error} retry={retry} scope="page crashed" />;
}
