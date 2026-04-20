import {
  Briefcase,
  CheckCircle2,
  CreditCard,
  FileUp,
  Inbox,
  Search,
  Send,
  UserCheck,
} from "lucide-react";
import type { ReactNode } from "react";

type Stage = {
  icon: ReactNode;
  title: string;
  caption: string;
  accent?: "blue" | "green" | "amber";
};

const STAGES: Stage[] = [
  {
    icon: <FileUp size={22} />,
    title: "Upload resume",
    caption: "Drop your resume. We run an ATS score and pre-fill your profile.",
  },
  {
    icon: <UserCheck size={22} />,
    title: "Set targets",
    caption: "Pick roles, locations, and work-auth preferences — or skip and use defaults.",
  },
  {
    icon: <Inbox size={22} />,
    title: "Connect inbox",
    caption: "Read-only Gmail access for confirmation-email verification.",
  },
  {
    icon: <Search size={22} />,
    title: "Match roles",
    caption: "We scan Greenhouse, Lever, SmartRecruiters, and Workday and score fits.",
    accent: "blue",
  },
  {
    icon: <Send size={22} />,
    title: "Submit",
    caption: "For matched roles, we fill the ATS form and submit on your behalf.",
    accent: "blue",
  },
  {
    icon: <CheckCircle2 size={22} />,
    title: "Verify",
    caption: "Wait for the employer confirmation email. Up to 30 minutes.",
    accent: "green",
  },
  {
    icon: <CreditCard size={22} />,
    title: "Charge",
    caption: "1 credit consumed only after confirmation lands. No confirmation, no charge.",
    accent: "amber",
  },
  {
    icon: <Briefcase size={22} />,
    title: "Track",
    caption: "Every submission shows up in your dashboard with status + links.",
  },
];

export function WorkflowDiagram() {
  return (
    <div className="workflow">
      <div className="workflow-track">
        {STAGES.map((s, i) => (
          <div className="workflow-stage" key={s.title}>
            <div className={`workflow-ico${s.accent ? " workflow-ico-" + s.accent : ""}`}>
              {s.icon}
            </div>
            <div className="workflow-num">{i + 1}</div>
            <div className="workflow-stage-body">
              <strong>{s.title}</strong>
              <p>{s.caption}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="workflow-legend">
        <span className="workflow-legend-item">
          <span className="workflow-legend-dot workflow-legend-blue" /> You
        </span>
        <span className="workflow-legend-item">
          <span className="workflow-legend-dot workflow-legend-instaply" /> Instaply
        </span>
        <span className="workflow-legend-item">
          <span className="workflow-legend-dot workflow-legend-billing" /> Billing
        </span>
      </div>
    </div>
  );
}
