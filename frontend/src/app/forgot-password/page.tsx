import { ForgotPasswordForm } from "@/features/account/components/forgot-password-form";

export const metadata = { title: "Reset password · QuickIndex" };

export default function ForgotPasswordPage() {
  return (
    <main className="flex flex-1 items-center justify-center px-4 py-12">
      <ForgotPasswordForm />
    </main>
  );
}
