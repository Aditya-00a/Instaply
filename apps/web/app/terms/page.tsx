import type { Metadata } from "next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PublicShell } from "../components/public-shell";
import { readLegalDoc } from "../lib/legal";

export const metadata: Metadata = {
  title: "Terms of Service",
  description: "Instaply Terms of Service.",
};

export default function TermsPage() {
  const md = readLegalDoc("terms");
  return (
    <PublicShell>
      <article className="legal-article">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{md}</ReactMarkdown>
      </article>
    </PublicShell>
  );
}
