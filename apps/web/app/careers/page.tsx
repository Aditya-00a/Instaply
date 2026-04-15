import type { Metadata } from "next";
import Link from "next/link";
import { PublicShell } from "../components/public-shell";

export const metadata: Metadata = {
  title: "Careers",
  description: "Join Instaply. Open roles and hiring philosophy.",
};

export default function CareersPage() {
  return (
    <PublicShell>
      <section className="info-hero">
        <div className="info-eyebrow">Careers</div>
        <h1 className="info-title">
          We&apos;re a small team building for candidates at scale.
        </h1>
        <p className="info-lede">
          Instaply is built by Ravendise — a focused team shipping agentic
          infrastructure for the job-application process. We are hiring
          selectively.
        </p>
      </section>

      <section className="info-section">
        <h2>How we work</h2>
        <ul className="info-list">
          <li>Small, senior team. No org-chart theater.</li>
          <li>Remote-friendly with async defaults.</li>
          <li>Direct customer contact for everyone, including engineers.</li>
          <li>Ship fast. Own what you ship, end to end.</li>
        </ul>
      </section>

      <section className="info-section">
        <h2>Open roles</h2>
        <p className="info-body">
          We hire opportunistically rather than via permanent open
          postings. If you are strong on any of the following, we want to
          hear from you:
        </p>
        <ul className="info-list">
          <li>Full-stack engineering (TypeScript, Next.js, Python)</li>
          <li>Browser automation and ATS reverse-engineering</li>
          <li>LLM systems and RAG for matching / screening</li>
          <li>Payments and billing ops</li>
          <li>Growth and content</li>
        </ul>
        <p className="info-body">
          Send a short note and a link or resume to{" "}
          <a href="mailto:hello@asion.ai">hello@asion.ai</a>. Subject line
          &ldquo;Careers — [your name]&rdquo;. Include one specific thing
          you&apos;ve shipped that you&apos;re proud of.
        </p>
      </section>

      <section className="info-cta-row">
        <Link href="/about" className="landing-cta landing-cta-secondary">
          Learn about Instaply
        </Link>
        <a href="mailto:hello@asion.ai" className="landing-cta">
          Apply
        </a>
      </section>
    </PublicShell>
  );
}
