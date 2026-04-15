import type { Metadata } from "next";
import Link from "next/link";
import { PublicShell } from "../components/public-shell";

export const metadata: Metadata = {
  title: "How Instaply works",
  description:
    "Step by step: sign up, upload your resume, set preferences, connect confirmation-email monitoring, and let Instaply submit applications on your behalf.",
};

const STEPS = [
  {
    n: 1,
    title: "Sign up and verify your email",
    body: "Create an account at instaply.asion.ai. New accounts get 3 free applications to try the service end-to-end before any purchase. No credit card required.",
  },
  {
    n: 2,
    title: "Upload your resume and fill your profile",
    body: "Drop in a PDF or DOCX resume. Instaply parses work history, education, and skills. Fill in work authorization (visa status, sponsorship needs), location, and salary preferences. EEO demographic fields are optional and stored with your explicit consent.",
  },
  {
    n: 3,
    title: "Set your preferences",
    body: "Tell us what roles you want (e.g. 'risk analyst', 'senior product manager', 'director of engineering'), target seniority levels, locations, companies to exclude, and the minimum match-score threshold. You can adjust any of these at any time.",
  },
  {
    n: 4,
    title: "Connect your inbox (Gmail)",
    body: "We read only the specific confirmation emails employers send (based on known ATS sender patterns). We never read personal mail. This is the mechanism that lets us verify an application was actually received.",
  },
  {
    n: 5,
    title: "Review the match queue",
    body: "Instaply scores roles against your profile. You see every pending match and can approve, skip, or block a company before we submit. Strong matches (~85%+) can be auto-submitted if you prefer hands-off mode.",
  },
  {
    n: 6,
    title: "We submit, track, and confirm",
    body: "For each approved role we fill the ATS form, upload your resume, answer screening questions, complete EEO fields where applicable, and submit. We watch for the employer confirmation email for 30 minutes.",
  },
  {
    n: 7,
    title: "You only get charged when confirmation lands",
    body: "A credit is deducted only when the confirmation email arrives. No confirmation, no charge — even if the submission technically went through. Failed applications, portal errors, and skipped roles never consume a credit.",
  },
  {
    n: 8,
    title: "Top up when ready",
    body: "Starter $10 (10 apps), Plus $25 (30 apps, +17% bonus), Pro $50 (70 apps, +40% bonus), or a custom amount at $1 per application (minimum $10). Credits never expire while your account is active.",
  },
];

const AVOID = [
  "Roles requiring security clearances you don't hold",
  "Roles outside your work-authorization scope (unless you explicitly want sponsorship-only filtering)",
  "Intentionally misrepresenting qualifications on screening questions — Instaply uses your profile data only",
  "Submitting to the same role twice — Instaply deduplicates by ATS job ID",
];

export default function HowItWorksPage() {
  return (
    <PublicShell>
      <section className="info-hero">
        <div className="info-eyebrow">How it works</div>
        <h1 className="info-title">
          From signup to your first confirmation in under 10 minutes.
        </h1>
        <p className="info-lede">
          Instaply is designed so the first confirmed application lands
          before your free-tier credits run out. Here is the full flow.
        </p>
      </section>

      <section className="info-section">
        <ol className="info-steps">
          {STEPS.map((s) => (
            <li className="info-step" key={s.n}>
              <div className="info-step-num">{s.n}</div>
              <div className="info-step-body">
                <div className="info-step-title">{s.title}</div>
                <p>{s.body}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>

      <section className="info-section">
        <h2>Good to know</h2>
        <ul className="info-list">
          <li>
            <strong>One account per person.</strong> Free credits are tied
            to a verified identity. Creating duplicates to farm credits is
            against the Terms and results in account termination.
          </li>
          <li>
            <strong>Credits never expire</strong> while your account is
            active.
          </li>
          <li>
            <strong>You stay in control.</strong> You can pause auto-submit,
            block specific companies, or cancel any time from your
            settings.
          </li>
          <li>
            <strong>No subscriptions.</strong> You pay for what you use.
            Top-ups are one-time purchases processed by Paddle.
          </li>
        </ul>
      </section>

      <section className="info-section">
        <h2>What Instaply won't do</h2>
        <ul className="info-list">
          {AVOID.map((a) => <li key={a}>{a}</li>)}
        </ul>
      </section>

      <section className="info-cta-row">
        <Link href="/sign-in" className="landing-cta">
          Start with 3 free applications
        </Link>
        <Link href="/pricing" className="landing-cta landing-cta-secondary">
          See pricing
        </Link>
      </section>
    </PublicShell>
  );
}
