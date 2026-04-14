import { Search } from "lucide-react";

import { ConsoleShell } from "../components/console-shell";
import { blockedQuestions } from "../console-data";

const summaryCards = [
  { label: "Tracked", value: "83" },
  { label: "Packets ready", value: "12" },
  { label: "Need input", value: "4" },
  { label: "Ready to send", value: "7" }
];

const tableRows = [
  {
    role: "Risk Analyst",
    company: "Interactive Brokers",
    source: "Greenhouse",
    stage: "Packet ready",
    status: "Ready for apply",
    fit: "91%"
  },
  {
    role: "Product Analyst",
    company: "T. Rowe Price",
    source: "Workday",
    stage: "Apply plan",
    status: "Needs review",
    fit: "88%"
  },
  {
    role: "AML Operations Analyst",
    company: "Ramp",
    source: "Ashby",
    stage: "Blocked question",
    status: "Awaiting answer",
    fit: "84%"
  },
  {
    role: "Strategy Analyst",
    company: "Apollo",
    source: "Workday",
    stage: "Search queue",
    status: "Fresh match",
    fit: "79%"
  },
  {
    role: "Business Analyst",
    company: "Capital One",
    source: "Workday",
    stage: "Tailor packet",
    status: "Generating packet",
    fit: "82%"
  },
  {
    role: "Implementation Consultant",
    company: "Figma",
    source: "Greenhouse",
    stage: "Apply plan",
    status: "Ready for review",
    fit: "87%"
  }
];

export default function ApplicationsPage() {
  return (
    <ConsoleShell
      activePath="/applications"
      eyebrow=""
      title="Applications"
      description=""
      actions={[
        { href: "/review", label: "Open answers" },
        { href: "/documents", label: "Open files", variant: "secondary" }
      ]}
    >
      <section className="console-section">
        <div className="section-intro">
          <div>
            <p className="eyebrow">Pipeline</p>
            <h2>Track every role from match to apply</h2>
          </div>
        </div>

        <div className="pricing-plan-grid workspace-metric-grid">
          {summaryCards.map((card) => (
            <article className="workspace-metric-card" key={card.label}>
              <span className="workspace-metric-label">{card.label}</span>
              <strong className="workspace-metric-value">{card.value}</strong>
            </article>
          ))}
        </div>
      </section>

      {blockedQuestions.length > 0 ? (
        <section className="console-section">
          <article className="glass blocker-banner blocker-banner-product">
            <div className="blocker-banner-copy">
              <span className="blocker-banner-kicker">Review required</span>
              <strong>{blockedQuestions.length} applications are waiting on an answer</strong>
              <p>Open the answer queue to clear blockers and keep the pipeline moving.</p>
            </div>
            <a className="button-secondary" href="/review">
              Review now
            </a>
          </article>
        </section>
      ) : null}

      <section className="console-section">
        <article className="glass workspace-table-card">
          <div className="workspace-toolbar">
            <div className="workspace-search">
              <Search size={16} />
              <span>Search roles or companies</span>
            </div>
            <div className="workspace-toolbar-actions">
              <button className="workspace-filter-pill">All stages</button>
              <button className="workspace-filter-pill">Last 30 days</button>
            </div>
          </div>

          <div className="workspace-table workspace-table-compact">
            <div className="workspace-table-head workspace-table-head-applications">
              <span>Role</span>
              <span>Company</span>
              <span>Source</span>
              <span>Stage</span>
              <span>Status</span>
              <span>Fit</span>
            </div>
            {tableRows.map((row) => (
              <div className="workspace-table-row workspace-table-row-applications" key={`${row.role}-${row.company}`}>
                <strong>{row.role}</strong>
                <span>{row.company}</span>
                <span>{row.source}</span>
                <span>{row.stage}</span>
                <span>{row.status}</span>
                <span className="workspace-inline-pill">{row.fit}</span>
              </div>
            ))}
          </div>
        </article>
      </section>
    </ConsoleShell>
  );
}
