import { Suspense } from "react";
import { VerifyEmailView } from "@/features/account/components/verify-email-view";

export const metadata = { title: "Verify email · QuickIndex" };

export default function VerifyEmailPage() {
  return (
    <main className="flex flex-1 items-center justify-center px-4 py-12">
      <Suspense fallback={null}>
        <VerifyEmailView />
      </Suspense>
    </main>
  );
}
