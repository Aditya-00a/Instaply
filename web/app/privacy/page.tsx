import type { Metadata } from "next";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { readLegalDoc } from "@/lib/legal";

export const metadata: Metadata = {
  title: "Privacy Policy — Instaply",
  description: "Instaply Privacy Policy.",
};

export default function PrivacyPage() {
  const md = readLegalDoc("privacy");
  return (
    <article className="prose prose-invert max-w-none">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{md}</ReactMarkdown>
    </article>
  );
}
