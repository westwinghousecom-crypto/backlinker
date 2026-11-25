import { TERMS_OF_SERVICE_MD } from "@/features/legal/documents";
import { LegalPage } from "@/features/legal/legal-page";

export const metadata = { title: "Terms of Service (draft) · QuickIndex" };

export default function TermsPage() {
  return <LegalPage source={TERMS_OF_SERVICE_MD} other={{ href: "/privacy", label: "Privacy Policy" }} />;
}
