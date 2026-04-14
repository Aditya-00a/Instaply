import {
  starterCandidateWorkspaceProfile,
  type DashboardSection
} from "@instaply/contracts";

export interface ConsoleNavItem {
  href: string;
  label: string;
  section: "workspace" | "account";
}

export interface SummaryMetric {
  label: string;
  value: string;
  note: string;
}

export const consoleNavItems: ConsoleNavItem[] = [
  { href: "/dashboard", label: "Overview", section: "workspace" },
  { href: "/applications", label: "Applications", section: "workspace" },
  { href: "/review", label: "Answers", section: "workspace" },
  { href: "/documents", label: "Documents", section: "workspace" },
  { href: "/onboarding", label: "Profile", section: "workspace" },
  { href: "/billing", label: "Billing", section: "account" },
  { href: "/settings", label: "Settings", section: "account" }
];

export const candidateSnapshot = {
  name: starterCandidateWorkspaceProfile.identity.legalFullName,
  plan: "Agent Suite Trial",
  location: `${starterCandidateWorkspaceProfile.identity.currentCity}, ${starterCandidateWorkspaceProfile.identity.currentRegion}`,
  autoApplyEnabled: starterCandidateWorkspaceProfile.automation.autoApplyEnabled ? "Enabled" : "Off",
  runMode: starterCandidateWorkspaceProfile.automation.preferredRunMode.replaceAll("_", " "),
  dailyCap: `${starterCandidateWorkspaceProfile.automation.dailyApplyCap} apply actions / day`
};

export const overviewMetrics: SummaryMetric[] = [
  { label: "Matches", value: "18", note: "live matches tracked across configured portals" },
  { label: "Packets built", value: "11", note: "tailored resume and cover letter bundles generated" },
  { label: "Answers needed", value: "4", note: "questions waiting for a candidate-approved answer" },
  { label: "Ready now", value: "7", note: "supported applications ready for the next step" }
];

export const queueRows = [
  {
    role: "Risk Analyst",
    rating: "91%"
  },
  {
    role: "Product Analyst",
    rating: "88%"
  },
  {
    role: "AML Operations Analyst",
    rating: "84%"
  },
  {
    role: "Strategy Analyst",
    rating: "79%"
  }
];

export const blockedQuestions = [
  {
    company: "Ramp",
    question: "Work authorization dropdown needs a reusable answer and escalation rule.",
    recommended: "Save once and apply across supported portals.",
    priority: "High"
  },
  {
    company: "Interactive Brokers",
    question: "Signature confirmation can use the legal full name from profile settings.",
    recommended: "Mark as safe auto-fill.",
    priority: "Medium"
  },
  {
    company: "Apollo",
    question: "Location preference depends on relocation policy and hybrid willingness.",
    recommended: "Candidate should review once and store the rule.",
    priority: "Medium"
  }
];

export const generatedDocuments = [
  {
    role: "Risk Analyst",
    company: "Interactive Brokers",
    resume: "Modern Analyst",
    coverLetter: "Concise, Confident",
    updated: "12 min ago"
  },
  {
    role: "Product Analyst",
    company: "T. Rowe Price",
    resume: "Modern Analyst",
    coverLetter: "High Research",
    updated: "28 min ago"
  },
  {
    role: "AML Operations Analyst",
    company: "Ramp",
    resume: "Finance Risk",
    coverLetter: "Formal, Structured",
    updated: "41 min ago"
  }
];

export const billingCards = [
  {
    title: "Current plan",
    value: "Agent Suite Trial",
    note: "Includes starter credits for search, packet generation, and guarded apply planning."
  },
  {
    title: "Credits remaining",
    value: "27",
    note: "Shared across packet generation, apply planning, and review-assisted runs."
  },
  {
    title: "Tester seats",
    value: "3",
    note: "Reserved for private beta accounts and internal pilot candidates."
  }
];

export const activityFeed = [
  "Candidate preferences now cover resume format, cover letter format, portal choices, and company controls.",
  "The MCP tool surface now separates search, queue, packet, apply-plan, and answer-memory actions.",
  "Instaply is being built as a private hosted product with a thin console and MCP-first interaction model.",
  "Blocked-question review is treated as a product feature, not an implementation detail."
];

export const trustSignals = [
  "Private hosted workspace",
  "Answer memory and blocked review queue",
  "Supported portals first",
  "Evidence-backed activity history"
];

export const sectionLabels: Record<DashboardSection, string> = {
  overview: "Overview",
  search: "Search",
  applications: "Applications",
  outreach: "Outreach",
  documents: "Documents",
  billing: "Billing",
  settings: "Settings"
};
