import type { Metadata } from "next";
import { PublicShell } from "../components/public-shell";

export const metadata: Metadata = {
  title: "Changelog",
  description: "Recent changes and releases shipped to Instaply.",
};

type Entry = {
  date: string;
  title: string;
  items: string[];
};

const ENTRIES: Entry[] = [
  {
    date: "2026-04-15",
    title: "Public launch prep",
    items: [
      "Public pricing page at /pricing with Starter, Plus, Pro packs and a custom top-up calculator.",
      "Terms of Service, Privacy Policy, and Refund Policy published as standalone pages with visible, blue-header tables.",
      "Signup now requires explicit acceptance of Terms, Privacy, and Refund before account creation.",
      "Full nav added to the landing page — Product, How it works, Pricing, Contact.",
      "Broadened product positioning — Instaply is for candidates at every career level, not just early career.",
    ],
  },
  {
    date: "2026-04-10",
    title: "Pay-per-confirmation billing",
    items: [
      "Credits now only deduct when the employer confirmation email lands. Failed submissions never consume a credit.",
      "Added append-only credit ledger with tamper-evident row-level security.",
      "Paddle integration wired as merchant of record for global payments.",
    ],
  },
  {
    date: "2026-04-04",
    title: "Hardening pass",
    items: [
      "JWT verification + per-route rate limits on all authenticated endpoints.",
      "Audit logging on every sensitive action (profile updates, MCP token lifecycle, billing events).",
      "33 worker tests green; CI wired to block merges on red.",
    ],
  },
  {
    date: "2026-03-28",
    title: "Multi-surface access",
    items: [
      "Claude Desktop MCP integration shipped — manage applications from inside Claude.",
      "ChatGPT Connector shipped — Instaply as a Custom GPT action.",
      "Web dashboard redesign with Overview, Applications, Answers, Documents, Profile, Billing, Settings.",
    ],
  },
  {
    date: "2026-03-18",
    title: "Portal coverage expansion",
    items: [
      "Greenhouse and Lever pipelines at full coverage.",
      "SmartRecruiters pipeline at full coverage.",
      "Workday pipeline in private beta for selected employers.",
    ],
  },
];

export default function ChangelogPage() {
  return (
    <PublicShell>
      <section className="info-hero">
        <div className="info-eyebrow">Changelog</div>
        <h1 className="info-title">What&apos;s shipping.</h1>
        <p className="info-lede">
          A running log of features, fixes, and releases. Dated newest
          first.
        </p>
      </section>

      <div className="changelog-list">
        {ENTRIES.map((e) => (
          <article className="changelog-entry" key={e.date}>
            <div className="changelog-entry-head">
              <span className="changelog-entry-date">{e.date}</span>
              <span className="changelog-entry-title">{e.title}</span>
            </div>
            <ul>
              {e.items.map((i) => <li key={i}>{i}</li>)}
            </ul>
          </article>
        ))}
      </div>
    </PublicShell>
  );
}
