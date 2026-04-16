import type { Metadata } from "next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { readLegalDoc } from "@/lib/legal";

export const metadata: Metadata = {
  title: "Refund Policy — Instaply",
  description: "Instaply Refund Policy.",
};

export default function RefundPage() {
  const md = readLegalDoc("refund");
  return (
    <article className="prose prose-invert max-w-none">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{md}</ReactMarkdown>
    </article>
  );
}
