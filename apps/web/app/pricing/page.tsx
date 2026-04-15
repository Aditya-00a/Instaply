import type { Metadata } from "next";
import Link from "next/link";
import { PublicShell } from "../components/public-shell";
import { PricingCustom } from "../components/pricing-custom";

export const metadata: Metadata = {
  title: "Pricing",
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
    credits: 30,
    bonus: 17,
    per: 0.83,
    note: "Most popular. 30 applications — enough for a focused job search sprint.",
    featured: true,
  },
  {
    id: "pro",
    label: "Pro",
    usd: 50,
    credits: 70,
    bonus: 40,
    per: 0.71,
    note: "Best value per application. For multi-month searches.",
    featured: false,
  },
] as const;

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
      <section className="pricing-hero">
        <div className="pricing-eyebrow">Pricing</div>
        <h1 className="pricing-title">$1 per confirmed application.</h1>
        <p className="pricing-lede">
          Prepaid credit packs. No subscriptions. Credits are deducted only
          after the employer confirmation email lands — if it never comes,
          you pay nothing.
        </p>
      </section>

      <section className="pricing-grid">
        {PACKS.map((p) => (
          <div
            key={p.id}
            className={`pricing-card${p.featured ? " pricing-card-featured" : ""}`}
          >
            <div className="pricing-card-label">{p.label}</div>
            <div className="pricing-card-price">
              <strong>${p.usd}</strong>
              <span>USD, one-time</span>
            </div>
            <div className="pricing-card-credits">{p.credits} applications</div>
            <div className="pricing-card-per">
              ${p.per.toFixed(2)} effective per application
            </div>
            {p.bonus > 0 && (
              <div className="pricing-card-bonus">+{p.bonus}% bonus credits</div>
            )}
            <p className="pricing-card-note">{p.note}</p>
            <Link
              href="/sign-in"
              className={`pricing-card-cta${p.featured ? "" : " pricing-card-cta-secondary"}`}
            >
              Sign up to buy
            </Link>
          </div>
        ))}
      </section>

      <PricingCustom />

      <section className="pricing-terms-card">
        <p>
          <strong>New accounts</strong> get 3 free applications to try the
          service before any purchase.
        </p>
        <p>
          <strong>Minimum top-up</strong> is $10 (Starter pack).
        </p>
        <p>
          <strong>What &quot;confirmed&quot; means:</strong> Instaply watches
          the email inbox you connect and only deducts a credit when the
          automated confirmation from the employer&apos;s applicant-tracking
          system arrives. Submission without confirmation is free.
        </p>
        <p>
          <strong>No outcome guarantees.</strong> Instaply is a filing service.
          We do not guarantee interviews, offers, or any response from any
          employer.
        </p>
      </section>

      <h2 className="pricing-section-heading">Frequently asked</h2>
      <div className="pricing-faq">
        {FAQ.map((f) => (
          <div className="pricing-faq-item" key={f.q}>
            <p className="pricing-faq-q">{f.q}</p>
            <p className="pricing-faq-a">{f.a}</p>
          </div>
        ))}
      </div>
    </PublicShell>
  );
}
