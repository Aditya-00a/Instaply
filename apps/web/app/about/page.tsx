import type { Metadata } from "next";
import Link from "next/link";
import { PublicShell } from "../components/public-shell";
import { WorkflowDiagram } from "../components/workflow-diagram";

export const metadata: Metadata = {
  title: "About Instaply",
  description:
    "Instaply is an agentic job-application platform. We submit applications to Greenhouse, Lever, SmartRecruiters, and Workday on your behalf. Pay only when the employer confirmation email lands.",
};

const WHAT = [
  {
    title: "Submit, don't search",
    body: "We maintain a live pool of roles from Greenhouse, Lever, SmartRecruiters, and Workday. You set preferences; we submit matching applications.",
  },
  {
    title: "Pay-per-confirmation",
    body: "A credit is only consumed after the employer's automated confirmation email arrives in your inbox. Failed submissions cost nothing.",
  },
  {
    title: "Three surfaces",
    body: "Use the web dashboard at instaply.asion.ai, the Claude Desktop MCP integration, or the ChatGPT Connector — whichever fits your workflow.",
  },
  {
    title: "Built on strong models",
    body: "Cover letters, answers, and ranking are powered by NVIDIA NIM plus Claude and GPT as fallbacks. You can see every draft before it is submitted.",
  },
];

const ATS = [
  { name: "Greenhouse", status: "Supported" },
  { name: "Lever", status: "Supported" },
  { name: "SmartRecruiters", status: "In development" },
  { name: "Workday", status: "Paused" },
  { name: "Ashby", status: "Roadmap" },
  { name: "iCIMS", status: "Roadmap" },
];

const WHO = [
  "Candidates at any level — new grads, mid-career, senior, and executive — running a high-volume search",
  "International candidates needing visa-friendly employers at scale",
  "Career switchers testing multiple role categories",
  "Senior ICs and managers targeting specific companies across the full open-role pool, not just the handful on job boards",
  "Anyone tired of retyping the same answers into 40 ATS forms a week",
];

const SAFETY = [
  "Every application is logged and reviewable before confirmation",
  "Row-level security on every row — your data is never shared with other users",
  "AES-256 at rest, TLS 1.3 in transit",
  "No data sold to third parties; sub-processors listed in the Privacy Policy",
  "DPDP Act (India) and GDPR (EU) compliant",
];

export default function AboutPage() {
  return (
    <PublicShell>
      <section className="info-hero">
        <div className="info-eyebrow">About</div>
        <h1 className="info-title">
          Instaply is a filing service for the modern job search.
        </h1>
        <p className="info-lede">
          We automate the mechanical half of the search — discovering roles
          and completing ATS application forms — so you can spend your time
          on the parts that actually move outcomes: prep, interviews, and
          networking.
        </p>
      </section>

      <section className="info-section">
        <h2>What Instaply does</h2>
        <div className="info-grid">
          {WHAT.map((w) => (
            <div className="info-card" key={w.title}>
              <div className="info-card-title">{w.title}</div>
              <p>{w.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="info-section">
        <h2>How it flows, end to end</h2>
        <WorkflowDiagram />
      </section>

      <section className="info-section">
        <h2>Supported portals</h2>
        <p className="info-body">
          Instaply only works with portals we have tested end-to-end. We add
          new portals only after a full submission + confirmation round-trip
          passes.
        </p>
        <div className="info-table-wrap">
          <table className="info-table">
            <thead>
              <tr>
                <th>Portal</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {ATS.map((a) => (
                <tr key={a.name}>
                  <td>{a.name}</td>
                  <td>{a.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="info-section">
        <h2>Who it is for</h2>
        <ul className="info-list">
          {WHO.map((w) => <li key={w}>{w}</li>)}
        </ul>
      </section>

      <section className="info-section">
        <h2>Safety and data handling</h2>
        <ul className="info-list">
          {SAFETY.map((s) => <li key={s}>{s}</li>)}
        </ul>
        <p className="info-body">
          Full detail lives in our <Link href="/privacy">Privacy Policy</Link>.
        </p>
      </section>

      <section className="info-section">
        <h2>What Instaply is not</h2>
        <p className="info-body">
          Instaply is not a recruiter, a headhunter, or a hiring agency. We
          file applications; we do not guarantee interviews, offers, or
          employment. Hiring decisions depend on many factors outside our
          control. See Section 18 of the{" "}
          <Link href="/terms">Terms of Service</Link> for the full
          disclaimer.
        </p>
      </section>

      <section className="info-cta-row">
        <Link href="/sign-in" className="landing-cta">
          Start with 3 free applications
        </Link>
        <Link href="/how-it-works" className="landing-cta landing-cta-secondary">
          See how it works
        </Link>
      </section>
    </PublicShell>
  );
}
