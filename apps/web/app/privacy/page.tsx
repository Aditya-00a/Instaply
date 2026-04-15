import type { Metadata } from "next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PublicShell } from "../components/public-shell";
import { readLegalDoc } from "../lib/legal";

export const metadata: Metadata = {
  title: "Privacy Policy",
  description: "Instaply Privacy Policy.",
};

export default function PrivacyPage() {
  const md = readLegalDoc("privacy");
  return (
    <PublicShell>
      <article className="legal-article">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{md}</ReactMarkdown>
      </article>
    </PublicShell>
  );
}
