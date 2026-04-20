import type { Metadata } from "next";
import { PublicShell } from "../components/public-shell";

export const metadata: Metadata = {
  title: "System status",
  description: "Current operational status of the Instaply service.",
};

type Svc = { name: string; state: "up" | "degraded" | "paused"; note?: string };

// Static placeholder. Swap to a live feed (UptimeRobot, BetterStack, or
// a small /health aggregator) once we have a public dashboard.
const SERVICES: Svc[] = [
  { name: "Web dashboard (instaply.asion.ai)", state: "up" },
  { name: "API (applications + billing)", state: "up" },
  { name: "Application worker", state: "up" },
  { name: "Confirmation-email verifier", state: "degraded", note: "Not deployed yet — applications stop at 'Submitted'. Users are not billed until this is live." },
  { name: "Greenhouse pipeline", state: "up" },
  { name: "Lever pipeline", state: "up" },
  { name: "SmartRecruiters pipeline", state: "degraded", note: "Adapter exists, not yet validated end-to-end. Avoid for now." },
  { name: "Workday pipeline", state: "paused", note: "Being rebuilt as a browser extension — login-walled portals run more reliably from the user's own browser. See /how-it-works." },
  { name: "Razorpay payment processing", state: "up" },
];

export default function StatusPage() {
  const anyDegraded = SERVICES.some((s) => s.state !== "up");
  return (
    <PublicShell>
      <section className="info-hero">
        <div className="info-eyebrow">Status</div>
        <h1 className="info-title">
          {anyDegraded
            ? "Most systems operational."
            : "All systems operational."}
        </h1>
        <p className="info-lede">
          Live service status for the Instaply platform. For incidents and
          scheduled maintenance, email{" "}
          <a href="mailto:hello@asion.ai">hello@asion.ai</a>.
        </p>
      </section>

      <section className="info-section">
        {SERVICES.map((s) => (
          <div className="status-row" key={s.name}>
            <span
              className={`status-dot ${s.state === "up" ? "status-dot-up" : "status-dot-degraded"}`}
              aria-label={s.state}
            />
            <span className="status-row-label">{s.name}</span>
            <span className="status-row-state">
              {s.state === "up" ? "Operational" : s.state === "paused" ? "Paused" : "Partial"}
              {s.note ? ` · ${s.note}` : ""}
            </span>
          </div>
        ))}
      </section>
    </PublicShell>
  );
}
