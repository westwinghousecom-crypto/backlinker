import { PRIVACY_POLICY_MD } from "@/features/legal/documents";
import { LegalPage } from "@/features/legal/legal-page";

export const metadata = { title: "Privacy Policy (draft) · QuickIndex" };

export default function PrivacyPage() {
  return <LegalPage source={PRIVACY_POLICY_MD} other={{ href: "/terms", label: "Terms of Service" }} />;
}
