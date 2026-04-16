import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Pricing — Instaply",
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
    note: "Best for trying Instaply.",
  },
  {
    id: "plus",
    label: "Plus",
    usd: 25,
    credits: 30,
    bonus: 17,
    per: 0.83,
    note: "Our most popular pack.",
  },
  {
    id: "pro",
    label: "Pro",
    usd: 50,
    credits: 70,
    bonus: 40,
    per: 0.71,
    note: "Best value per application.",
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
    a: "Unused credits are refundable within 14 days of purchase. Used credits (applications that reached 'confirmed' status) are non-refundable. Full terms at /terms and /refund.",
  },
  {
    q: "How do I pay?",
    a: "Payments are processed by Paddle, our merchant of record. Paddle supports credit and debit cards, PayPal, Apple Pay, Google Pay, and regional methods where available.",
  },
] as const;

export default function PricingPage() {
  return (
    <div className="space-y-16">
      <section className="text-center pt-6">
        <div className="inline-block rounded-full border border-white/15 px-3 py-1 text-xs text-white/60">
          Pricing
        </div>
        <h1 className="mt-4 text-5xl font-semibold tracking-tight">
          $1 per confirmed application.
        </h1>
        <p className="mt-5 text-lg text-white/70 max-w-2xl mx-auto">
          Prepaid credit packs. No subscriptions. Credits are deducted only
          after the employer confirmation email lands — if it never comes,
          you pay nothing.
        </p>
      </section>

      <section className="grid md:grid-cols-3 gap-4">
        {PACKS.map((p) => (
          <div key={p.id} className="rounded-xl border border-white/10 p-6 flex flex-col">
            <div className="text-sm text-white/60">{p.label}</div>
            <div className="mt-2 flex items-baseline gap-2">
              <div className="text-4xl font-semibold">${p.usd}</div>
              <div className="text-sm text-white/50">USD, one-time</div>
            </div>
            <div className="mt-2 text-white/80">
              {p.credits} applications
            </div>
            <div className="text-xs text-white/50">
              ${p.per.toFixed(2)} effective per application
            </div>
            {p.bonus > 0 && (
              <div className="mt-2 inline-block w-fit rounded bg-white/5 px-2 py-0.5 text-xs text-accent">
                +{p.bonus}% bonus credits
              </div>
            )}
            <div className="mt-3 text-sm text-white/60">{p.note}</div>
            <a
              href="/signup"
              className="mt-6 rounded-md bg-accent px-4 py-2 text-center text-sm font-medium"
            >
              Sign up to buy
            </a>
          </div>
        ))}
      </section>

      <section className="rounded-xl border border-white/10 p-6 text-sm text-white/70 space-y-2">
        <div><strong className="text-white">New accounts</strong> get 3 free applications to try the service before any purchase.</div>
        <div><strong className="text-white">Minimum top-up</strong> is $10 (Starter pack).</div>
        <div><strong className="text-white">What &quot;confirmed&quot; means:</strong> Instaply watches the email inbox you connect and only deducts a credit when the automated confirmation from the employer&apos;s applicant-tracking system arrives. Submission without confirmation is free.</div>
        <div><strong className="text-white">No outcome guarantees:</strong> Instaply is a filing service. We do not guarantee interviews, offers, or any response from any employer.</div>
      </section>

      <section>
        <h2 className="text-2xl font-semibold tracking-tight">Frequently asked</h2>
        <div className="mt-6 space-y-5">
          {FAQ.map((f) => (
            <div key={f.q} className="rounded-lg border border-white/10 p-5">
              <div className="font-medium text-white">{f.q}</div>
              <div className="mt-2 text-sm text-white/70">{f.a}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="text-sm text-white/60 text-center space-x-4">
        <a href="/terms" className="hover:text-white underline">Terms</a>
        <span>·</span>
        <a href="/refund" className="hover:text-white underline">Refund policy</a>
        <span>·</span>
        <a href="/privacy" className="hover:text-white underline">Privacy</a>
      </section>
    </div>
  );
}
