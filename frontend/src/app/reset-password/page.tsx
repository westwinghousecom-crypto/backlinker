import { Suspense } from "react";
import { ResetPasswordForm } from "@/features/account/components/reset-password-form";

export const metadata = { title: "Choose a new password · QuickIndex" };

export default function ResetPasswordPage() {
  return (
    <main className="flex flex-1 items-center justify-center px-4 py-12">
      <Suspense fallback={null}>
        <ResetPasswordForm />
      </Suspense>
    </main>
  );
}
