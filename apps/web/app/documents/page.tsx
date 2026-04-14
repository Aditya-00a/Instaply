import { ConsoleShell } from "../components/console-shell";
import { generatedDocuments } from "../console-data";

const documentStats = [
  { label: "Bundles", value: "11" },
  { label: "Resume style", value: "Modern" },
  { label: "Letter style", value: "Concise" },
  { label: "Exports", value: "28" }
];

export default function DocumentsPage() {
  return (
    <ConsoleShell
      activePath="/documents"
      eyebrow=""
      title="Documents"
      description=""
      actions={[
        { href: "/onboarding", label: "Edit formats" },
        { href: "/applications", label: "Back to applications", variant: "secondary" }
      ]}
    >
      <section className="console-section">
        <div className="section-intro">
          <div>
            <p className="eyebrow">Document workspace</p>
            <h2>Your latest tailored packets</h2>
          </div>
        </div>

        <div className="pricing-plan-grid workspace-metric-grid">
          {documentStats.map((card) => (
            <article className="workspace-metric-card" key={card.label}>
              <span className="workspace-metric-label">{card.label}</span>
              <strong className="workspace-metric-value">{card.value}</strong>
            </article>
          ))}
        </div>
      </section>

      <section className="console-section workspace-grid-two workspace-grid-two-narrow">
        <article className="glass workspace-table-card">
          <div className="console-card-header">
            <div>
              <div className="panel-kicker">Recent exports</div>
              <h3>Generated packets</h3>
            </div>
          </div>

            <div className="workspace-table workspace-table-compact">
              <div className="workspace-table-head workspace-table-head-documents">
                <span>Role</span>
                <span>Company</span>
                <span>Resume</span>
                <span>Cover letter</span>
                <span>Updated</span>
              </div>
              {generatedDocuments.map((row) => (
                <div className="workspace-table-row workspace-table-row-documents" key={`${row.company}-${row.role}`}>
                  <strong>{row.role}</strong>
                  <span>{row.company}</span>
                  <span>{row.resume}</span>
                  <span>{row.coverLetter}</span>
                  <span>{row.updated}</span>
              </div>
            ))}
          </div>
        </article>

        <article className="glass workspace-card">
          <div className="console-card-header">
            <div>
              <div className="panel-kicker">Defaults</div>
              <h3>Current profile style</h3>
            </div>
          </div>

          <div className="workspace-list">
            <div className="workspace-list-row">
              <div>
                <strong>Resume format</strong>
                <p>Modern analyst</p>
              </div>
            </div>
            <div className="workspace-list-row">
              <div>
                <strong>Cover letter format</strong>
                <p>Concise confident</p>
              </div>
            </div>
            <div className="workspace-list-row">
              <div>
                <strong>Voice notes</strong>
                <p>Direct, evidence-based, and ATS-friendly.</p>
              </div>
            </div>
          </div>
        </article>
      </section>
    </ConsoleShell>
  );
}
