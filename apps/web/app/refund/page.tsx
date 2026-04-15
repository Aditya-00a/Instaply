import type { Metadata } from "next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PublicShell } from "../components/public-shell";
import { readLegalDoc } from "../lib/legal";

export const metadata: Metadata = {
  title: "Refund Policy",
  description: "Instaply Refund Policy.",
};

export default function RefundPage() {
  const md = readLegalDoc("refund");
  return (
    <PublicShell>
      <article className="legal-article">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{md}</ReactMarkdown>
      </article>
    </PublicShell>
  );
}
