import type { Metadata } from "next";
import Link from "next/link";
import { PublicShell } from "../components/public-shell";

export const metadata: Metadata = {
  title: "Security",
  description:
    "How Instaply protects your data — encryption, access control, audit logging, sub-processors, and compliance with DPDP Act and GDPR.",
};

const PILLARS = [
  {
    title: "Encryption",
    body: "TLS 1.3 for every request in transit. AES-256 at rest for databases and storage via Supabase. Secrets live in a managed KMS; we do not ship secrets in code.",
  },
  {
    title: "Access control",
    body: "Row-level security enforces per-user data isolation at the database layer. Staff access is on a least-privilege basis and logged. No engineer has default access to production user data.",
  },
  {
    title: "Audit logging",
    body: "Every sensitive action — profile updates, application submissions, MCP token creation, billing events — writes to an append-only audit log. IPs are salted and hashed before storage.",
  },
  {
    title: "Credit ledger integrity",
    body: "Credit grants and debits are append-only. Refunds and reversals are recorded as new rows, never by editing history. This makes balance reconstruction deterministic and tamper-evident.",
  },
  {
    title: "Payment security",
    body: "Razorpay processes all payments. We never see or store your full card number. Razorpay is PCI-DSS Level 1 compliant.",
  },
];

const COMPLIANCE = [
  "India's Digital Personal Data Protection Act, 2023 (DPDP Act)",
  "EU General Data Protection Regulation (GDPR), where applicable",
  "Standard Contractual Clauses for cross-border EU transfers",
  "DPDP Act § 16 permissions for transfers out of India",
];

const INCIDENT = [
  "We monitor for breaches continuously",
  "On confirmed breach, we notify affected users and the Data Protection Board of India within 72 hours",
  "Contact hello@asion.ai for any security concern — we treat all reports seriously",
];

export default function SecurityPage() {
  return (
    <PublicShell>
      <section className="info-hero">
        <div className="info-eyebrow">Security</div>
        <h1 className="info-title">
          Security is a product requirement, not a footnote.
        </h1>
        <p className="info-lede">
          Instaply handles resumes, work authorization, demographic data,
          and payment data. Here is how we protect it.
        </p>
      </section>

      <section className="info-section">
        <h2>Our five pillars</h2>
        <div className="info-grid">
          {PILLARS.map((p) => (
            <div className="info-card" key={p.title}>
              <div className="info-card-title">{p.title}</div>
              <p>{p.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="info-section">
        <h2>Compliance</h2>
        <ul className="info-list">
          {COMPLIANCE.map((c) => <li key={c}>{c}</li>)}
        </ul>
        <p className="info-body">
          Our full list of sub-processors and retention rules is in the{" "}
          <Link href="/privacy">Privacy Policy</Link>.
        </p>
      </section>

      <section className="info-section">
        <h2>Incident response</h2>
        <ul className="info-list">
          {INCIDENT.map((i) => <li key={i}>{i}</li>)}
        </ul>
      </section>

      <section className="info-section">
        <h2>Responsible disclosure</h2>
        <p className="info-body">
          Found a vulnerability? Email <a href="mailto:hello@asion.ai">hello@asion.ai</a>{" "}
          with the subject &ldquo;Security report&rdquo;. Please do not
          publicly disclose before we have had a reasonable window to fix
          it. We acknowledge reports within 48 hours.
        </p>
      </section>
    </PublicShell>
  );
}
