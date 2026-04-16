import type { Metadata } from "next";
import Link from "next/link";
import { PublicShell } from "../components/public-shell";
import { PricingCustom } from "../components/pricing-custom";

export const metadata: Metadata = {
  title: "Pricing — $1 per confirmed application",
  description:
    "Instaply pricing. $1 per confirmed application. Prepaid credit packs starting at $10. No subscriptions, no recurring charges.",
};

const PACKS = [
  {
    id: "starter",
    label: "Starter",
    usd: 10,
    credits: 10,
    bonus: 0,
    per: 1.0,
    note: "A small top-up to try Instaply end-to-end.",
    featured: false,
  },
  {
    id: "plus",
    label: "Plus",
    usd: 25,
    credits: 28,
    bonus: 12,
    per: 0.89,
    note: "Most popular. 28 applications — enough for a focused job-search sprint.",
    featured: true,
  },
  {
    id: "pro",
    label: "Pro",
    usd: 50,
    credits: 60,
    bonus: 20,
    per: 0.83,
    note: "Best value per application. For multi-month searches.",
    featured: false,
  },
] as const;

const TRUST = [
  { label: "Secured by Paddle", detail: "PCI-DSS Level 1" },
  { label: "No subscriptions", detail: "One-time credit packs" },
  { label: "Credits never expire", detail: "Account stays active" },
  { label: "Refundable", detail: "14-day unused-credit refund" },
];

const FAQ = [
  {
    q: "What does one credit buy?",
    a: "One credit = one confirmed job application. A credit is only deducted after the employer's automated confirmation email lands in your inbox. If the application fails or no confirmation arrives, you are not charged.",
  },
  {
    q: "Is this a subscription?",
    a: "No. Credit packs are one-time purchases. Credits do not expire. You top up when you want to send more applications.",
  },
  {
    q: "Which job portals are supported?",
    a: "At launch: Greenhouse, Lever, and SmartRecruiters. Workday support is in beta for selected companies. More portals are added as we test them end-to-end.",
  },
  {
    q: "Do you guarantee interviews or offers?",
    a: "No. Instaply submits applications on your behalf. We do not guarantee interviews, offers, or any specific outcome from any employer. We are a filing service, not a recruiter.",
  },
  {
    q: "What is your refund policy?",
    a: "Unused credits are refundable within 14 days of purchase. Used credits (applications that reached 'confirmed' status) are non-refundable. Full terms on the Refund Policy page.",
  },
  {
    q: "How do I pay?",
    a: "Payments are processed by Paddle, our merchant of record. Paddle supports credit and debit cards, PayPal, Apple Pay, Google Pay, and regional methods where available.",
  },
] as const;

export default function PricingPage() {
  return (
    <PublicShell>
      <section className="pricing-hero-v2">
        <div className="hero-eyebrow">
          <span className="hero-dot" /> Pricing
        </div>
        <h1 className="pricing-title-v2">
          $1 per confirmed application.
        </h1>
        <p className="pricing-lede-v2">
          Prepaid credit packs. No subscriptions, no recurring charges.
          Credits are deducted only after the employer confirmation email
          lands — if it never comes, you pay nothing.
        </p>
        <div className="pricing-hero-chips">
          <span className="pricing-hero-chip">3 free applications on signup</span>
          <span className="pricing-hero-chip">10 free searches per day</span>
          <span className="pricing-hero-chip">Minimum top-up $10</span>
          <span className="pricing-hero-chip">Credits never expire</span>
        </div>
      </section>

      <section className="pricing-grid-v2">
        {PACKS.map((p) => (
          <div
            key={p.id}
            className={`pack-card${p.featured ? " pack-card-featured" : ""}`}
          >
            {p.featured && <div className="pack-card-tag">Most popular</div>}
            <div className="pack-card-label">{p.label}</div>
            <div className="pack-card-price">
              <strong>${p.usd}</strong>
              <span>USD, one-time</span>
            </div>
            <div className="pack-card-credits">{p.credits} applications</div>
            <div className="pack-card-per">
              ${p.per.toFixed(2)} effective per application
            </div>
            {p.bonus > 0 && (
              <div className="pack-card-bonus">+{p.bonus}% bonus credits</div>
            )}
            <p className="pack-card-note">{p.note}</p>
            <Link
              href="/sign-in"
              className={p.featured ? "btn-primary" : "btn-secondary"}
            >
              Sign up to buy
            </Link>
          </div>
        ))}
      </section>

      <PricingCustom />

      <section className="trust-band">
        {TRUST.map((t) => (
          <div className="trust-item" key={t.label}>
            <div className="trust-label">{t.label}</div>
            <div className="trust-detail">{t.detail}</div>
          </div>
        ))}
      </section>

      <section className="pricing-terms-card">
        <p>
          <strong>New accounts</strong> get 3 free applications to try the
          service before any purchase.
        </p>
        <p>
          <strong>What &quot;confirmed&quot; means:</strong> Instaply
          watches the email inbox you connect and only deducts a credit
          when the automated confirmation from the employer&apos;s
          applicant-tracking system arrives. Submission without
          confirmation is free.
        </p>
        <p>
          <strong>No outcome guarantees.</strong> Instaply is a filing
          service. We do not guarantee interviews, offers, or any
          response from any employer.
        </p>
      </section>

      <section className="pricing-faq-section">
        <div className="testimonials-head">
          <div className="eyebrow-pill">Pricing FAQ</div>
          <h2 className="testimonials-title">Questions, answered.</h2>
        </div>
        <div className="pricing-faq-v2">
          {FAQ.map((f) => (
            <details className="pricing-faq-item-v2" key={f.q}>
              <summary>{f.q}</summary>
              <p>{f.a}</p>
            </details>
          ))}
        </div>
      </section>

      <section className="final-cta">
        <h2>Start with 3 free applications.</h2>
        <p>No credit card required. Top up only when you need more.</p>
        <div className="hero-cta-row">
          <Link href="/sign-in" className="btn-primary">Get started free</Link>
          <Link href="/contact" className="btn-secondary">Talk to us</Link>
        </div>
      </section>
    </PublicShell>
  );
}
