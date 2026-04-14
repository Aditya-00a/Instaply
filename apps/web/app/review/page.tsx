import { ConsoleShell } from "../components/console-shell";
import { blockedQuestions } from "../console-data";

const reviewStats = [
  { label: "Awaiting reply", value: "4" },
  { label: "Saved answers", value: "11" },
  { label: "Urgent", value: "1" },
  { label: "Resolved today", value: "7" }
];

export default function ReviewPage() {
  return (
    <ConsoleShell
      activePath="/review"
      eyebrow=""
      title="Answers"
      description=""
      actions={[
        { href: "/onboarding", label: "Edit profile" },
        { href: "/applications", label: "Back to applications", variant: "secondary" }
      ]}
    >
      <section className="console-section">
        <div className="section-intro">
          <div>
            <p className="eyebrow">Answer queue</p>
            <h2>Review once, reuse safely</h2>
          </div>
        </div>

        <div className="pricing-plan-grid workspace-metric-grid">
          {reviewStats.map((card) => (
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
              <div className="panel-kicker">Blocked items</div>
              <h3>Questions waiting on your input</h3>
            </div>
          </div>

          <div className="workspace-table workspace-table-compact">
            <div className="workspace-table-head workspace-table-head-review">
              <span>Company</span>
              <span>Question</span>
              <span>Recommended next step</span>
              <span>Priority</span>
            </div>
            {blockedQuestions.map((row) => (
              <div className="workspace-table-row workspace-table-row-review" key={`${row.company}-${row.question}`}>
                <strong>{row.company}</strong>
                <span>{row.question}</span>
                <span>{row.recommended}</span>
                <span className={row.priority === "High" ? "review-priority review-priority-high" : "review-priority"}>
                  {row.priority}
                </span>
              </div>
            ))}
          </div>
        </article>

        <article className="glass workspace-card">
          <div className="console-card-header">
            <div>
              <div className="panel-kicker">How it works</div>
              <h3>Answer memory</h3>
            </div>
          </div>

          <div className="workspace-list">
            <div className="workspace-list-row">
              <div>
                <strong>Review a blocked question</strong>
                <p>Instaply pauses only when the answer should come from you.</p>
              </div>
            </div>
            <div className="workspace-list-row">
              <div>
                <strong>Save the approved answer</strong>
                <p>That answer becomes reusable for the same portal pattern later.</p>
              </div>
            </div>
            <div className="workspace-list-row">
              <div>
                <strong>Keep automation safe</strong>
                <p>Compensation, relocation, and signature questions stay grounded in your profile.</p>
              </div>
            </div>
          </div>
        </article>
      </section>
    </ConsoleShell>
  );
}
