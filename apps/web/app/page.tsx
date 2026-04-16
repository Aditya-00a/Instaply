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
];

const TESTIMONIALS = [
  {
    quote:
      "I was mass-applying to 30 jobs a day and burning out on ATS forms. Instaply let me focus on interview prep while applications went out in the background. Game changer.",
    name: "Sowmya D.",
    meta: "MS CS, Long Island University '25",
    initials: "SD",
    accent: "#0052ff",
  },
  {
    quote:
      "The match queue surfaced analyst roles at companies I didn't even know were hiring. Got two interview calls from applications Instaply submitted for me.",
    name: "Nikhil S.",
    meta: "MS Data Science, NYU '26",
    initials: "NS",
    accent: "#8b5cf6",
  },
  {
    quote:
      "As an F-1 student, half the jobs I applied to didn't even sponsor. Instaply only showed me roles where I had a real shot. Saved me weeks of dead-end applications.",
    name: "Yash S.",
    meta: "MBA, NYU Stern '25",
    initials: "YS",
    accent: "#10b981",
  },
  {
    quote:
      "The pay-per-confirmation model is genius. I only paid for applications that actually went through. Every other service charges upfront and hopes you don't notice.",
    name: "Pavan V.",
    meta: "Software Engineer, Class of '24",
    initials: "PV",
    accent: "#f59e0b",
  },
];

const TRUST = [
  { label: "Secured by Razorpay", detail: "PCI-DSS Level 1" },
  { label: "TLS 1.3 in transit", detail: "AES-256 at rest" },
  { label: "Row-level security", detail: "Your data stays yours" },
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
            Stop copy-pasting into ATS forms. We&nbsp;handle&nbsp;it.
          </h1>
          <p className="hero-lede">
            Upload your resume once. Pick the roles you want. Instaply fills
            out every application form for you — Greenhouse, Lever,
            SmartRecruiters, Workday. You only pay when the employer
            confirmation email actually lands. Built for students,
            new grads, and anyone tired of the application grind.
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
          <div className="feature-title">You pick, we apply</div>
          <p>
            Browse 2,600+ roles from top companies. Click Apply on the ones
            you like. Our system fills out the entire ATS form for you,
            including screening questions.
          </p>
        </div>
        <div className="feature-card">
          <div className="feature-ico" aria-hidden>
            ✓
          </div>
          <div className="feature-title">Pay only when it lands</div>
          <p>
            $1 per confirmed application. We only charge after the employer
            sends the confirmation email. If the form fails or no email
            arrives, it costs you nothing.
          </p>
        </div>
        <div className="feature-card">
          <div className="feature-ico" aria-hidden>
            ◆
          </div>
          <div className="feature-title">Built for visa candidates</div>
          <p>
            F-1 OPT, H-1B, CPT — set your work authorization once and
            we handle the sponsorship questions on every form. No more
            guessing which companies sponsor.
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
