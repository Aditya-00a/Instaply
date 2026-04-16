import type { Metadata } from "next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { readLegalDoc } from "@/lib/legal";

export const metadata: Metadata = {
  title: "Terms of Service — Instaply",
  description: "Instaply Terms of Service.",
};

export default function TermsPage() {
  const md = readLegalDoc("terms");
  return (
    <article className="prose prose-invert max-w-none">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{md}</ReactMarkdown>
    </article>
  );
}
