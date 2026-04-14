import { ArrowUpRight } from "lucide-react";

import { ConsoleShell } from "../components/console-shell";
import { blockedQuestions, generatedDocuments, overviewMetrics, queueRows } from "../console-data";

const recentUpdates = [
  { label: "Packet ready", title: "Risk Analyst", meta: "Interactive Brokers", state: "Ready" },
  { label: "Answer needed", title: "AML Operations Analyst", meta: "Ramp", state: "Waiting" },
  { label: "Fresh match", title: "Strategy Analyst", meta: "Apollo", state: "New" }
];

export default function DashboardPage() {
  return (
    <ConsoleShell
      activePath="/dashboard"
      eyebrow=""
      title="Overview"
      description=""
      actions={[
        { href: "/applications", label: "View applications" },
        { href: "/review", label: "Open answers", variant: "secondary" }
      ]}
    >
      <section className="console-section">
        <div className="section-intro">
          <div>
            <p className="eyebrow">Workspace</p>
            <h2>Everything important in one place</h2>
          </div>
        </div>

        <div className="pricing-plan-grid workspace-metric-grid">
          {overviewMetrics.map((metric) => (
            <article className="workspace-metric-card" key={metric.label}>
              <span className="workspace-metric-label">{metric.label}</span>
              <strong className="workspace-metric-value">{metric.value}</strong>
            </article>
          ))}
        </div>
      </section>

      {blockedQuestions.length > 0 ? (
        <section className="console-section">
          <article className="glass blocker-banner blocker-banner-product">
            <div className="blocker-banner-copy">
              <span className="blocker-banner-kicker">Needs review</span>
              <strong>{blockedQuestions.length} answers are waiting on you</strong>
              <p>Answer them once and Instaply can reuse them safely across supported applications.</p>
            </div>
            <a className="button-secondary" href="/review">
              Open answers
            </a>
          </article>
        </section>
      ) : null}

      <section className="console-section workspace-grid-two">
        <article className="glass workspace-card">
          <div className="console-card-header">
            <div>
              <div className="panel-kicker">Activity</div>
              <h3>Latest progress</h3>
            </div>
            <ArrowUpRight size={18} />
          </div>

          <div className="workspace-list">
            {recentUpdates.map((item) => (
              <div className="workspace-list-row" key={`${item.label}-${item.title}`}>
                <div>
                  <span className="workspace-list-kicker">{item.label}</span>
                  <strong>{item.title}</strong>
                  <p>{item.meta}</p>
                </div>
                <span className="workspace-inline-pill">{item.state}</span>
              </div>
            ))}
          </div>
        </article>

        <article className="glass workspace-card">
          <div className="console-card-header">
            <div>
              <div className="panel-kicker">Documents</div>
              <h3>Recent files</h3>
            </div>
          </div>

          <div className="workspace-list">
            {generatedDocuments.map((document) => (
              <div className="workspace-list-row" key={`${document.company}-${document.role}`}>
                <div>
                  <strong>{document.role}</strong>
                  <p>{document.company}</p>
                  <div className="workspace-tag-row">
                    <span className="workspace-tag">Resume: {document.resume}</span>
                    <span className="workspace-tag">Letter: {document.coverLetter}</span>
                  </div>
                </div>
                <span className="workspace-inline-note">{document.updated}</span>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="console-section">
        <article className="glass workspace-table-card">
          <div className="console-card-header">
            <div>
              <div className="panel-kicker">Queue</div>
              <h3>Open roles</h3>
            </div>
          </div>

          <div className="workspace-list">
            {queueRows.map((row) => (
              <div className="workspace-list-row" key={row.role}>
                <strong>{row.role}</strong>
                <span className="workspace-inline-pill">{row.rating}</span>
              </div>
            ))}
          </div>
        </article>
      </section>
    </ConsoleShell>
  );
}
