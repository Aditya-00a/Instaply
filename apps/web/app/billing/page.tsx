import { Check, Coins, CreditCard, Sparkles, TestTube2, Wallet } from "lucide-react";

import { ConsoleShell } from "../components/console-shell";

const plans = [
  {
    name: "Starter",
    price: "Free",
    suffix: "",
    description: "For candidates who want to try Instaply before paying for applications.",
    cta: "Get started",
    tone: "default" as const,
    features: [
      "3 guided search runs per day",
      "3 tailored packets included",
      "2 free supported apply credits",
      "Review queue and document workspace"
    ]
  },
  {
    name: "Pay per apply",
    price: "$0.99",
    suffix: "/application",
    description: "For candidates who want to pay only when a supported application is actually executed.",
    cta: "Use pay as you go",
    tone: "default" as const,
    features: [
      "No monthly subscription required",
      "Charged only for supported apply runs",
      "Search, review, and packet flow stay available",
      "Good for low-volume or trial usage"
    ]
  },
  {
    name: "Weekly Pro",
    price: "$50",
    suffix: "/week",
    description: "For candidates who want one simple weekly plan with consistent application volume.",
    cta: "Start Weekly Pro",
    tone: "featured" as const,
    badge: "Most popular",
    features: [
      "60 supported applications every week",
      "Daily search and ranking workflow",
      "Blocked-question memory and review queue",
      "Packet generation and usage tracking"
    ]
  }
];

const compareSections = [
  {
    label: "Core workflow",
    rows: [
      ["Daily search runs", "3", "Pay as you go", "Unlimited"],
      ["Tailored packets", "3 total", "Included", "Included"],
      ["Supported applications", "2 total", "$0.99 each", "60 / week"],
      ["Blocked-question memory", "Basic", "Included", "Included"]
    ]
  },
  {
    label: "Agent features",
    rows: [
      ["Apply Agent", "Guided", "Guided + paid runs", "Included"],
      ["Review queue", "Included", "Included", "Included"],
      ["Priority processing", "-", "-", "Priority"],
      ["Tester seats", "-", "-", "1 invite"]
    ]
  },
  {
    label: "Support and controls",
    rows: [
      ["Workspace analytics", "Basic", "Included", "Included"],
      ["Plan billing", "Self-serve", "Usage based", "Weekly billing"],
      ["Account support", "Community", "Community", "Priority email"],
      ["Admin controls", "-", "-", "Basic"]
    ]
  }
];

const creditStats = [
  { label: "Current credits", value: "18", note: "Ready to use" },
  { label: "Used this month", value: "12", note: "Across apply runs" },
  { label: "Weekly allowance", value: "60", note: "On Weekly Pro" }
];

const creditBundles = [
  {
    name: "Starter top-up",
    credits: "10 credits",
    price: "$9.90",
    detail: "Best for light usage and one-off application pushes at $0.99 per application.",
    cta: "Add 10 credits"
  },
  {
    name: "Active search pack",
    credits: "25 credits",
    price: "$24.75",
    detail: "A straightforward top-up for candidates who want more supported apply runs without switching plans.",
    cta: "Add 25 credits",
    featured: true
  },
  {
    name: "High volume pack",
    credits: "50 credits",
    price: "$49.50",
    detail: "For heavier application weeks when you want to stay on pay-as-you-go pricing.",
    cta: "Add 50 credits"
  }
];

export default function BillingPage() {
  return (
    <ConsoleShell
      activePath="/billing"
      eyebrow="Pricing"
      title="Pricing"
      description=""
      actions={[
        { href: "/settings", label: "Manage billing" },
        { href: "/sign-in", label: "Invite testers", variant: "secondary" }
      ]}
    >
      <section className="console-section">
        <div className="pricing-hero">
          <div className="pricing-hero-copy">
            <p className="eyebrow">Pricing</p>
            <h2>Simple and transparent pricing</h2>
          </div>

          <div className="pricing-badge-row">
            <span className="pricing-pill">
              <Sparkles size={14} />
              MCP-native workflow
            </span>
            <span className="pricing-pill">
              <TestTube2 size={14} />
              Tester credits included
            </span>
          </div>
        </div>

        <div className="pricing-plan-grid">
          {plans.map((plan) => (
            <article
              className={`pricing-plan-card${plan.tone === "featured" ? " pricing-plan-card-featured" : ""}`}
              key={plan.name}
            >
              <div className="pricing-plan-top">
                <div>
                  <span className="pricing-plan-name">{plan.name}</span>
                  <div className="pricing-plan-price">
                    <strong>{plan.price}</strong>
                    {plan.suffix ? <span>{plan.suffix}</span> : null}
                  </div>
                </div>
                {plan.badge ? <span className="pricing-plan-badge">{plan.badge}</span> : null}
              </div>

              <p className="pricing-plan-copy">{plan.description}</p>

              <div className="pricing-feature-list">
                {plan.features.map((feature) => (
                  <div className="pricing-feature-row" key={feature}>
                    <Check size={14} />
                    <span>{feature}</span>
                  </div>
                ))}
              </div>

              <button className={`pricing-plan-button${plan.tone === "featured" ? " pricing-plan-button-featured" : ""}`}>
                {plan.cta}
              </button>
            </article>
          ))}
        </div>
      </section>

      <section className="console-section">
        <div className="section-intro">
          <div>
            <p className="eyebrow">Credits</p>
            <h2>Add credits when you need more runs</h2>
          </div>
        </div>

        <div className="credits-grid">
          <article className="glass credits-wallet-card">
            <div className="console-card-header">
              <div>
                <div className="panel-kicker">Credit wallet</div>
                <h3>Usage at a glance</h3>
              </div>
              <Wallet size={18} />
            </div>

            <div className="credits-stat-grid">
              {creditStats.map((item) => (
                <article className="credits-stat-card" key={item.label}>
                  <span>{item.label}</span>
                  <strong>{item.value}</strong>
                  <p>{item.note}</p>
                </article>
              ))}
            </div>

            <div className="credits-wallet-note">
              <Coins size={16} />
              <span>Credits are used for supported apply runs and extra packet generation beyond your plan.</span>
            </div>
          </article>

          <div className="credits-pack-grid">
            {creditBundles.map((bundle) => (
              <article
                className={`credits-pack-card${bundle.featured ? " credits-pack-card-featured" : ""}`}
                key={bundle.name}
              >
                <div className="credits-pack-top">
                  <div>
                    <span className="credits-pack-name">{bundle.name}</span>
                    <strong>{bundle.credits}</strong>
                  </div>
                  <span className="credits-pack-price">{bundle.price}</span>
                </div>
                <p>{bundle.detail}</p>
                <button className={`credits-pack-button${bundle.featured ? " credits-pack-button-featured" : ""}`}>
                  {bundle.cta}
                </button>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="console-section">
        <div className="section-intro">
          <div>
            <p className="eyebrow">Compare plans</p>
            <h2>Everything important at a glance</h2>
          </div>
        </div>

        <div className="pricing-compare-card glass">
          <div className="pricing-compare-header">
            <span />
              <span>Starter</span>
              <span>Pay per apply</span>
              <span>Weekly Pro</span>
            </div>

          {compareSections.map((section) => (
            <div className="pricing-compare-section" key={section.label}>
              <div className="pricing-compare-label">{section.label}</div>
              {section.rows.map((row) => (
                <div className="pricing-compare-row" key={row[0]}>
                  <strong>{row[0]}</strong>
                  <span>{row[1]}</span>
                  <span>{row[2]}</span>
                  <span>{row[3]}</span>
                </div>
              ))}
            </div>
          ))}
        </div>
      </section>
    </ConsoleShell>
  );
}
