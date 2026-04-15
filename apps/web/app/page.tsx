import type { Metadata } from "next";
import Link from "next/link";
import { PublicShell } from "./components/public-shell";

export const metadata: Metadata = {
  title: "Instaply — $1 per confirmed job application",
  description:
    "Instaply is an agentic job-application platform. We submit applications to Greenhouse, Lever, SmartRecruiters, and Workday on your behalf. $1 per confirmed application. No subscriptions.",
};

const PORTALS = [
  "Greenhouse",
  "Lever",
  "SmartRecruiters",
  "Workday",
  "Ashby",
  "iCIMS",
];

const TESTIMONIALS = [
  {
    quote:
      "Instaply made the whole process so much smoother. I could focus on prepping for interviews instead of retyping the same answers into 40 ATS forms.",
    name: "Sowmya Deshpande",
    meta: "Long Island University",
    initials: "SD",
    accent: "#0052ff",
  },
  {
    quote:
      "Made my search a lot smoother. The match queue surfaced roles I would have missed, and submissions just landed in the background while I worked on everything else.",
    name: "Nikhil Singh",
    meta: "New York University",
    initials: "NS",
    accent: "#8b5cf6",
  },
  {
    quote:
      "As an international student, the visa and sponsorship filters alone made my process much smoother. I stopped wasting credits on roles I wasn't eligible for.",
    name: "Yash Sharma",
    meta: "New York University",
    initials: "YS",
    accent: "#10b981",
  },
  {
    quote:
      "Genuinely made my application process smoother. Pay-per-confirmation is the only pricing model that ever felt fair to me.",
    name: "Pavan Veera",
    meta: "Instaply user",
    initials: "PV",
    accent: "#f59e0b",
  },
];

const TRUST = [
  { label: "Secured by Paddle", detail: "PCI-DSS Level 1" },
  { label: "TLS 1.3 in transit", detail: "AES-256 at rest" },
  { label: "Row-level security", detail: "Per-user isolation" },
  { label: "DPDP + GDPR ready", detail: "Privacy-first by design" },
];

export default function HomePage() {
  return (
    <PublicShell>
      {/* Hero: two column on desktop, stacked on mobile */}
      <section className="hero">
        <div className="hero-copy">
          <div className="hero-eyebrow">
            <span className="hero-dot" /> Agentic job applications
          </div>
          <h1 className="hero-title">
            We submit job applications on your&nbsp;behalf.
          </h1>
          <p className="hero-lede">
            Instaply is an agentic filing service. Upload your resume, set
            your preferences, and we submit matching roles to Greenhouse,
            Lever, SmartRecruiters, and Workday — paying only when the
            employer confirmation email lands.
          </p>
          <div className="hero-cta-row">
            <Link href="/sign-in" className="btn-primary">
              Get 3 free applications
            </Link>
            <Link href="/how-it-works" className="btn-secondary">
              See how it works
            </Link>
          </div>
          <p className="hero-sub">
            $1 per confirmed application · No subscriptions · Credits
            never expire
          </p>
        </div>

        {/* Live-feel mock card — static but feels alive */}
        <aside className="hero-visual" aria-hidden="true">
          <div className="hero-card">
            <div className="hero-card-head">
              <span className="hero-card-pill">
                <span className="hero-card-pulse" /> Live queue
              </span>
              <span className="hero-card-time">Now</span>
            </div>
            <ul className="hero-card-list">
              <li>
                <div className="hero-card-row-main">
                  <strong>Risk Analyst</strong>
                  <span>Interactive Brokers · Greenhouse</span>
                </div>
                <span className="hero-card-status hero-card-status-ok">
                  Confirmed
                </span>
              </li>
              <li>
                <div className="hero-card-row-main">
                  <strong>Product Analyst</strong>
                  <span>T. Rowe Price · Workday</span>
                </div>
                <span className="hero-card-status hero-card-status-ok">
                  Confirmed
                </span>
              </li>
              <li>
                <div className="hero-card-row-main">
                  <strong>Strategy Analyst</strong>
                  <span>Apollo · Lever</span>
                </div>
                <span className="hero-card-status hero-card-status-pending">
                  Submitting
                </span>
              </li>
              <li>
                <div className="hero-card-row-main">
                  <strong>AML Operations Analyst</strong>
                  <span>Ramp · Greenhouse</span>
                </div>
                <span className="hero-card-status hero-card-status-wait">
                  Waiting
                </span>
              </li>
            </ul>
            <div className="hero-card-foot">
              <div>
                <span className="hero-card-metric">18</span>
                <span className="hero-card-metric-label">matches</span>
              </div>
              <div>
                <span className="hero-card-metric">7</span>
                <span className="hero-card-metric-label">confirmed</span>
              </div>
              <div>
                <span className="hero-card-metric">$7</span>
                <span className="hero-card-metric-label">spent</span>
              </div>
            </div>
          </div>
        </aside>
      </section>

      {/* Portals strip */}
      <section className="portal-strip">
        <div className="portal-strip-label">Submits to</div>
        <div className="portal-strip-list">
          {PORTALS.map((p) => (
            <div className="portal-chip" key={p}>
              {p}
            </div>
          ))}
        </div>
      </section>

      {/* Feature grid */}
      <section className="feature-grid">
        <div className="feature-card">
          <div className="feature-ico" aria-hidden>
            ⚡
          </div>
          <div className="feature-title">Submit, don&apos;t search</div>
          <p>
            You stop opening 40 tabs a day. We keep a pool of open roles
            and auto-submit the ones that match your profile.
          </p>
        </div>
        <div className="feature-card">
          <div className="feature-ico" aria-hidden>
            ✓
          </div>
          <div className="feature-title">Pay only when it lands</div>
          <p>
            A credit is consumed only after the employer&apos;s automated
            confirmation email arrives. Failed submissions cost nothing.
          </p>
        </div>
        <div className="feature-card">
          <div className="feature-ico" aria-hidden>
            ◆
          </div>
          <div className="feature-title">Works where you work</div>
          <p>
            Use the web dashboard, the Claude Desktop MCP integration, or
            the ChatGPT Connector — whichever fits your workflow.
          </p>
        </div>
      </section>

      {/* Stat band */}
      <section className="stat-band">
        <div className="stat-item">
          <div className="stat-num">$1</div>
          <div className="stat-label">per confirmed application</div>
        </div>
        <div className="stat-item">
          <div className="stat-num">0</div>
          <div className="stat-label">subscriptions, ever</div>
        </div>
        <div className="stat-item">
          <div className="stat-num">3</div>
          <div className="stat-label">free applications on signup</div>
        </div>
        <div className="stat-item">
          <div className="stat-num">10</div>
          <div className="stat-label">free job searches per day</div>
        </div>
      </section>

      {/* Testimonials */}
      <section className="testimonials">
        <div className="testimonials-head">
          <div className="eyebrow-pill">What users say</div>
          <h2 className="testimonials-title">
            A smoother job search, across every kind of candidate.
          </h2>
        </div>
        <div className="testimonials-grid">
          {TESTIMONIALS.map((t) => (
            <figure className="testimonial-card" key={t.name}>
              <blockquote>{t.quote}</blockquote>
              <figcaption>
                <span
                  className="testimonial-avatar"
                  style={{ background: t.accent }}
                  aria-hidden
                >
                  {t.initials}
                </span>
                <div className="testimonial-who">
                  <span className="testimonial-name">{t.name}</span>
                  <span className="testimonial-meta">{t.meta}</span>
                </div>
              </figcaption>
            </figure>
          ))}
        </div>
      </section>

      {/* Trust band */}
      <section className="trust-band">
        {TRUST.map((t) => (
          <div className="trust-item" key={t.label}>
            <div className="trust-label">{t.label}</div>
            <div className="trust-detail">{t.detail}</div>
          </div>
        ))}
      </section>

      {/* Final CTA */}
      <section className="final-cta">
        <h2>Stop retyping answers. Start sending applications.</h2>
        <p>
          Your first three applications are free. No card, no trial, no
          catch.
        </p>
        <div className="hero-cta-row">
          <Link href="/sign-in" className="btn-primary">
            Start for free
          </Link>
          <Link href="/pricing" className="btn-secondary">
            See pricing
          </Link>
        </div>
      </section>

      <section className="legal-inline-row">
        <p>
          By using Instaply you agree to our{" "}
          <Link href="/terms">Terms of Service</Link>,{" "}
          <Link href="/privacy">Privacy Policy</Link>, and{" "}
          <Link href="/refund">Refund Policy</Link>.
        </p>
      </section>
    </PublicShell>
  );
}
