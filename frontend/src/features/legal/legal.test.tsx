import fs from "node:fs";
import path from "node:path";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/appwrite", () => ({
  account: { get: vi.fn().mockRejectedValue(new Error("no session")) },
  ID: { unique: () => "id" },
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/login",
}));

import PrivacyPage from "@/app/privacy/page";
import TermsPage from "@/app/terms/page";
import { AuthForm } from "@/components/auth-form";
import { AuthProvider } from "@/lib/auth";
import { PRIVACY_POLICY_MD, TERMS_OF_SERVICE_MD } from "./documents";
import { DRAFT_BANNER } from "./legal-page";
import { parseMarkdown, renderInline } from "./markdown";

const repo = path.resolve(__dirname, "../../../..");
const doc = (name: string) => fs.readFileSync(path.join(repo, "docs/legal", name), "utf8").replace(/\r\n/g, "\n");

describe("public legal pages", () => {
  it("show the DRAFT banner on /privacy and /terms", () => {
    for (const Page of [PrivacyPage, TermsPage]) {
      const { unmount } = render(<Page />);
      expect(screen.getByRole("note")).toHaveTextContent(DRAFT_BANNER);
      expect(DRAFT_BANNER).toBe("DRAFT: requires legal review before launch");
      unmount();
    }
  });

  it("render the real documents (headings, the Limited Use statement, the retention table)", () => {
    render(<PrivacyPage />);
    expect(screen.getByRole("heading", { level: 1, name: "QuickIndex Privacy Policy" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: /Google user data \(Limited Use\)/ })).toBeInTheDocument();
    expect(screen.getByText(/Google API Services User Data Policy/, { selector: "a" })).toHaveAttribute(
      "href",
      "https://developers.google.com/terms/api-services-user-data-policy",
    );
    const table = screen.getByRole("table");
    expect(within(table).getByText(/Google inspection history/)).toBeInTheDocument();
    render(<TermsPage />);
    expect(screen.getByRole("heading", { level: 2, name: /No guarantee of indexing or ranking/ })).toBeInTheDocument();
  });

  it("highlight [PLACEHOLDERS] so they cannot be published unnoticed", () => {
    const { container } = render(<PrivacyPage />);
    const marks = container.querySelectorAll("mark[data-placeholder]");
    expect(marks.length).toBeGreaterThan(5);
    expect([...marks].some((m) => m.textContent === "[PRIVACY EMAIL ADDRESS]")).toBe(true);
  });
});

describe("the pages are the markdown documents", () => {
  it("documents.ts is in sync with docs/legal (run `npm run sync:legal` if this fails)", () => {
    expect(PRIVACY_POLICY_MD).toBe(doc("privacy-policy.md"));
    expect(TERMS_OF_SERVICE_MD).toBe(doc("terms-of-service.md"));
  });

  it("the privacy policy states exactly the retention periods the backend enforces", () => {
    const config = fs.readFileSync(path.join(repo, "backend/app/core/config.py"), "utf8");
    const setting = (name: string) => Number(new RegExp(`${name}: int = (\\d+)`).exec(config)![1]);
    const text = PRIVACY_POLICY_MD;
    expect(text).toMatch(new RegExp(`Backlink-check batches and their results \\| ${setting("RETENTION_CHECK_BATCH_DAYS")} days`));
    expect(text).toMatch(new RegExp(`public-feed setting \\| ${setting("RETENTION_SUBMISSION_DAYS")} days`));
    expect(text).toMatch(new RegExp(`Google inspection history \\| ${setting("RETENTION_GSC_HISTORY_DAYS")} days`));
    expect(text).toMatch(new RegExp(`Google daily usage counters \\| ${setting("RETENTION_QUOTA_DAYS")} days`));
    expect(setting("RETENTION_OAUTH_STATE_HOURS")).toBe(1);
    expect(text).toMatch(/security codes for the Google connection \| About 1 hour/);
  });

  it("only promises things the product does: no sale of data, deletion and export controls, the OAuth cookie", () => {
    expect(PRIVACY_POLICY_MD).toMatch(/do not sell personal data/);
    expect(PRIVACY_POLICY_MD).toMatch(/Export my data/);
    expect(PRIVACY_POLICY_MD).toMatch(/Delete account/);
    expect(PRIVACY_POLICY_MD).toMatch(/qi_oauth_binding/);
    expect(PRIVACY_POLICY_MD).toMatch(/adhere to the \[Google API Services User Data Policy\]/);
    expect(TERMS_OF_SERVICE_MD).toMatch(/does not promise that any page will be indexed/);
  });
});

describe("the tiny markdown renderer", () => {
  it("parses headings, lists, tables and paragraphs", () => {
    const blocks = parseMarkdown("# T\n\nline one\nline two\n\n## H\n\n- a\n- b\n\n| X | Y |\n| --- | --- |\n| 1 | 2 |\n");
    expect(blocks).toEqual([
      { type: "h1", text: "T" },
      { type: "p", lines: ["line one", "line two"] },
      { type: "h2", text: "H" },
      { type: "ul", items: ["a", "b"] },
      { type: "table", header: ["X", "Y"], rows: [["1", "2"]] },
    ]);
  });

  it("renders bold, code and safe links, and never makes a javascript: link", () => {
    const { container } = render(<p>{renderInline("**b** `c` [ok](https://x.example) [bad](javascript:alert(1)) [PLACEHOLDER]")}</p>);
    expect(container.querySelector("strong")).toHaveTextContent("b");
    expect(container.querySelector("code")).toHaveTextContent("c");
    expect(container.querySelector('a[href="https://x.example"]')).toHaveAttribute("rel", "noopener noreferrer");
    expect(container.querySelector('a[href^="javascript"]')).toBeNull();
    expect(container.querySelector("mark")).toHaveTextContent("[PLACEHOLDER]");
  });
});

describe("sign-in and sign-up forms link to the legal pages", () => {
  it.each(["login", "register"] as const)("%s form", async (mode) => {
    render(
      <AuthProvider>
        <AuthForm mode={mode} />
      </AuthProvider>,
    );
    expect(await screen.findByRole("link", { name: "Terms" })).toHaveAttribute("href", "/terms");
    expect(screen.getByRole("link", { name: "Privacy Policy" })).toHaveAttribute("href", "/privacy");
  });
});
