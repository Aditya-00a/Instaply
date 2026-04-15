import type { Metadata } from "next";
import Link from "next/link";
import { PublicShell } from "./components/public-shell";

export const metadata: Metadata = {
  title: "Instaply — $1 per confirmed job application",
  description:
    "Instaply is an agentic job-application platform. We submit applications to Greenhouse, Lever, and SmartRecruiters on your behalf. $1 per confirmed application. No subscriptions.",
};

export default function HomePage() {
  return (
    <PublicShell>
      <section className="landing-hero">
        <div className="landing-eyebrow">Agentic job applications</div>
        <h1 className="landing-title">
          We submit job applications on your behalf.
        </h1>
        <p className="landing-lede">
          Instaply is an agentic filing service. You upload your resume and
          set your preferences. We find matching roles on Greenhouse, Lever,
          and SmartRecruiters and submit applications for you — paying only
          when the employer confirmation email lands.
        </p>
        <div className="landing-cta-row">
          <Link href="/sign-in" className="landing-cta">
            Get 3 free applications
          </Link>
          <Link href="/pricing" className="landing-cta landing-cta-secondary">
            See pricing
          </Link>
        </div>
        <p className="landing-sub">
          $1 per confirmed application · No subscriptions · Credits never
          expire
        </p>
      </section>

      <section className="landing-grid">
        <div className="landing-card">
          <div className="landing-card-title">Submit, don't search</div>
          <p>
            You stop opening 40 tabs a day. We keep a pool of open roles and
            auto-submit the ones that match your profile.
          </p>
        </div>
        <div className="landing-card">
          <div className="landing-card-title">Pay only when it lands</div>
          <p>
            A credit is consumed only after the employer's automated
            confirmation email arrives. Failed submissions cost nothing.
          </p>
        </div>
        <div className="landing-card">
          <div className="landing-card-title">Works where you work</div>
          <p>
            Use the web dashboard, the Claude Desktop MCP integration, or
            the ChatGPT Connector — whichever fits your workflow.
          </p>
        </div>
      </section>

      <section className="landing-testimonials">
        <div className="landing-testimonials-head">
          <div className="landing-eyebrow">What users say</div>
          <h2 className="landing-testimonials-title">
            A smoother job search, across every kind of candidate.
          </h2>
        </div>
        <div className="landing-testimonials-grid">
          <figure className="landing-testimonial">
            <blockquote>
              Instaply made the whole process so much smoother. I could
              focus on prepping for interviews instead of retyping the
              same answers into 40 ATS forms.
            </blockquote>
            <figcaption>
              <span className="landing-testimonial-name">Sowmya Deshpande</span>
              <span className="landing-testimonial-meta">Long Island University</span>
            </figcaption>
          </figure>

          <figure className="landing-testimonial">
            <blockquote>
              Made my search a lot smoother. The match queue surfaced
              roles I would have missed, and submissions just landed in
              the background while I worked on everything else.
            </blockquote>
            <figcaption>
              <span className="landing-testimonial-name">Nikhil Singh</span>
              <span className="landing-testimonial-meta">New York University</span>
            </figcaption>
          </figure>

          <figure className="landing-testimonial">
            <blockquote>
              As an international student, the visa and sponsorship
              filters alone made my process much smoother. I stopped
              wasting credits on roles I wasn&apos;t eligible for.
            </blockquote>
            <figcaption>
              <span className="landing-testimonial-name">Yash Sharma</span>
              <span className="landing-testimonial-meta">New York University</span>
            </figcaption>
          </figure>

          <figure className="landing-testimonial">
            <blockquote>
              Genuinely made my application process smoother. Pay-per-
              confirmation is the only pricing model that ever felt fair
              to me.
            </blockquote>
            <figcaption>
              <span className="landing-testimonial-name">Pavan Veera</span>
              <span className="landing-testimonial-meta">Instaply user</span>
            </figcaption>
          </figure>
        </div>
      </section>

      <section className="landing-legal-row">
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
