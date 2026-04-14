export const instaplyPortals = [
  "greenhouse",
  "lever",
  "workday",
  "ashby",
  "smartrecruiters",
  "jobvite",
  "icims",
  "taleo"
] as const;

export type PortalId = (typeof instaplyPortals)[number];

export const instaplyPipelineStages = [
  "search",
  "enrich",
  "rank",
  "tailor_packet",
  "apply_plan",
  "supported_apply",
  "report_outcome"
] as const;

export type PipelineStage = (typeof instaplyPipelineStages)[number];

export const instaplyRunModes = [
  "search_only",
  "search_and_packet",
  "apply_plan_only",
  "dry_run_apply",
  "supported_apply",
  "outreach_only",
  "full_agent_cycle"
] as const;

export type RunMode = (typeof instaplyRunModes)[number];

export const instaplyPlans = [
  "free_trial",
  "starter",
  "apply_pro",
  "outreach_pro",
  "agent_suite",
  "team"
] as const;

export type PlanId = (typeof instaplyPlans)[number];

export const instaplyResumeFormats = [
  "classic_one_page",
  "modern_analyst",
  "consulting_focused",
  "finance_risk",
  "minimal_ats"
] as const;

export type ResumeFormatId = (typeof instaplyResumeFormats)[number];

export const instaplyCoverLetterFormats = [
  "concise_confident",
  "formal_structured",
  "warm_story_led",
  "high_research",
  "minimal_direct"
] as const;

export type CoverLetterFormatId = (typeof instaplyCoverLetterFormats)[number];

export const instaplyExperienceLevels = [
  "student",
  "internship",
  "new_grad",
  "entry_level",
  "associate",
  "early_career",
  "mid_level"
] as const;

export type ExperienceLevel = (typeof instaplyExperienceLevels)[number];

export const instaplyWorkModes = ["remote", "hybrid", "onsite"] as const;
export type WorkMode = (typeof instaplyWorkModes)[number];

export interface CandidateIdentity {
  firstName: string;
  lastName: string;
  legalFullName: string;
  primaryEmail: string;
  secondaryEmail?: string;
  phoneNumber: string;
  currentCity: string;
  currentRegion: string;
  currentCountry: string;
  linkedinUrl?: string;
  portfolioUrl?: string;
  githubUrl?: string;
}

export interface CandidateAuthorization {
  workAuthorizationSummary: string;
  requiresSponsorship: boolean;
  needsStemOptSupport: boolean;
  eligibleCountries: string[];
  willingToRelocate: boolean;
  openToHybrid: boolean;
  openToRemote: boolean;
}

export interface JobSearchPreferences {
  targetRoles: string[];
  targetIndustries: string[];
  preferredLocations: string[];
  excludedLocations: string[];
  experienceLevel: ExperienceLevel;
  workModes: WorkMode[];
  portalSelections: PortalId[];
  suggestedCompanies: string[];
  userAddedCompanies: string[];
  companyAllowlist: string[];
  companyDenylist: string[];
  companyRecommendationMode: "agent_recommended" | "user_curated" | "hybrid";
  requireRecentPostingDays: number;
  minimumRevenueUsd: number;
  entryLevelStrict: boolean;
}

export interface ResumePreferences {
  format: ResumeFormatId;
  pageTarget: "one_page" | "flex";
  emphasizeTracks: string[];
  keepPinnedBullets: string[];
  avoidTopics: string[];
  voiceNotes: string;
}

export interface CoverLetterPreferences {
  format: CoverLetterFormatId;
  toneTags: string[];
  includePersonalStory: boolean;
  includeCompanyResearch: boolean;
  maxParagraphs: 2 | 3 | 4;
  avoidPhrases: string[];
}

export interface ApplicationProfile {
  currentTitle: string;
  yearsOfExperienceClaim: number;
  educationSummary: string;
  educationEntries: string[];
  workExperienceEntries: string[];
  projectEntries: string[];
  researchPaperEntries: string[];
  compensationNotes: string;
  signatureDefault: string;
  experienceHighlights: string[];
  projectHighlights: string[];
  coreSkills: string[];
  defaultResponses: Array<{
    questionKey: string;
    answer: string;
    notes?: string;
  }>;
}

export interface AutomationPreferences {
  autoApplyEnabled: boolean;
  allowOutreachAgent: boolean;
  preferredRunMode: RunMode;
  dryRunDefault: boolean;
  maxApplicationsPerRun: number;
  dailyApplyCap: number;
  dailyOutreachCap: number;
}

export const instaplyUtilityActions = [
  "dry_run",
  "retry_stage",
  "mark_applied",
  "mark_blocked",
  "reset_failed_attempt",
  "skip_company",
  "save_answer_for_future"
] as const;

export type UtilityAction = (typeof instaplyUtilityActions)[number];

export interface BlockedQuestionReviewItem {
  questionKey: string;
  sourcePortal: PortalId | "unknown";
  company?: string;
  jobTitle?: string;
  questionLabel: string;
  questionType: "text" | "radio" | "select" | "checkbox" | "signature" | "unknown";
  availableOptions: string[];
  suggestedAnswer?: string;
  requiresHumanReview: boolean;
  notes?: string;
}

export interface CandidateWorkspaceProfile {
  identity: CandidateIdentity;
  authorization: CandidateAuthorization;
  jobSearch: JobSearchPreferences;
  resume: ResumePreferences;
  coverLetter: CoverLetterPreferences;
  application: ApplicationProfile;
  automation: AutomationPreferences;
}

export const starterCandidateWorkspaceProfile: CandidateWorkspaceProfile = {
  identity: {
    firstName: "Aditya",
    lastName: "Sakhale",
    legalFullName: "Aditya Sakhale",
    primaryEmail: "adityasakhale03@gmail.com",
    secondaryEmail: "aditya.sakhale@nyu.edu",
    phoneNumber: "+1 (929) 683-3207",
    currentCity: "New York",
    currentRegion: "NY",
    currentCountry: "United States",
    linkedinUrl: "https://linkedin.com/in/aditya-sakhale",
    portfolioUrl: "",
    githubUrl: "https://github.com/Aditya-00a"
  },
  authorization: {
    workAuthorizationSummary: "Needs sponsorship for long-term U.S. employment.",
    requiresSponsorship: true,
    needsStemOptSupport: true,
    eligibleCountries: ["United States"],
    willingToRelocate: true,
    openToHybrid: true,
    openToRemote: true
  },
  jobSearch: {
    targetRoles: [
      "Business Analyst",
      "Business Systems Analyst",
      "Product Analyst",
      "Risk Analyst",
      "Implementation Consultant",
      "Solutions Consultant",
      "Strategy & Operations",
      "Operations Analyst",
      "Data Analyst",
      "Finance Analyst",
      "Associate Consultant",
      "Analytics Consultant"
    ],
    targetIndustries: ["AI", "Fintech", "Consulting", "Analytics", "Financial Services"],
    preferredLocations: ["New York", "Remote", "San Francisco", "Chicago", "Boston"],
    excludedLocations: [],
    experienceLevel: "entry_level",
    workModes: ["remote", "hybrid", "onsite"],
    portalSelections: ["greenhouse", "lever", "workday", "ashby"],
    suggestedCompanies: ["Anthropic", "OpenAI", "Figma", "Ramp", "Capital One", "Airbnb"],
    userAddedCompanies: ["Dun & Bradstreet", "Interactive Brokers", "Apollo", "T. Rowe Price"],
    companyAllowlist: [],
    companyDenylist: [],
    companyRecommendationMode: "hybrid",
    requireRecentPostingDays: 7,
    minimumRevenueUsd: 500000000,
    entryLevelStrict: true
  },
  resume: {
    format: "modern_analyst",
    pageTarget: "one_page",
    emphasizeTracks: ["analytics", "risk", "strategy", "consulting", "ai product", "operator"],
    keepPinnedBullets: [],
    avoidTopics: [],
    voiceNotes: "Direct, evidence-based, ATS-friendly, and operator-minded."
  },
  coverLetter: {
    format: "concise_confident",
    toneTags: ["clear", "smart", "specific", "analytical"],
    includePersonalStory: false,
    includeCompanyResearch: true,
    maxParagraphs: 3,
    avoidPhrases: ["passionate self-starter", "dream company"]
  },
  application: {
    currentTitle: "AI Business Analyst Intern",
    yearsOfExperienceClaim: 3,
    educationSummary: "NYU MS in Risk Analytics, expected May 2026, 3.8 GPA, with applied AI, consulting, and risk research experience.",
    educationEntries: [
      "New York University - MS in Risk Analytics - 3.8 GPA - Expected May 2026",
      "NYU SPS x SAS Cortex Challenge Winner - XGBoost uplift model and about $8.69M optimization",
      "NASA Hackathon - Best Use of Data Award"
    ],
    workExperienceEntries: [
      "Fulcrum Digital - AI Business Analyst Intern - Designed AI solution architectures and client implementation roadmaps for Fortune 500 engagements.",
      "NextAML - AI Risk Management Intern - Built stablecoin risk monitoring models and LLM-based explainability workflows.",
      "NYU SPS Trust and Safety Lab - AI Sandbox Admin - Managed NVIDIA DGX Spark AI sandbox and agent evaluation frameworks.",
      "Ravendise - Data Scientist - Built ML, RAG, analytics, and business operations systems across client and internal workflows."
    ],
    projectEntries: [
      "JPMorgan Chase AI Strategy Project - Led conversational AI strategy, architecture comparison, and executive-facing roadmap delivery.",
      "NextLLM RAG Platform - Built regulatory research workflow using Llama, LangChain, and Supabase.",
      "Multi-Stablecoin Risk Monitoring System - Tracked over $184B market cap with ensemble ML and 0.94 AUC-ROC.",
      "ImmigrationMail AI - Built agentic email workflow using FastAPI, local models, and Gmail IMAP automation."
    ],
    researchPaperEntries: [
      "AI Powered Stablecoin Risk Monitoring Using Ensemble ML and LLM Explainability - NEDSI 2026 - For Publication",
      "AI-Powered Early Warning System for Hospital Financial Distress - NEDSI 2026 - For Publication"
    ],
    compensationNotes: "Open to market compensation for entry-level roles.",
    signatureDefault: "Aditya Sakhale",
    experienceHighlights: [
      "Designed AI solution architectures and implementation roadmaps for Fortune 500 clients at Fulcrum Digital.",
      "Built stablecoin risk monitoring models with 0.94 AUC-ROC and LLM explainability at NextAML.",
      "Scaled Ravendise from concept into a live learning business with analytics, delivery, and operations ownership."
    ],
    projectHighlights: [
      "Led a JPMorgan Chase AI strategy engagement with executive-facing deliverables.",
      "Won the NYU SPS x SAS Cortex Challenge with an XGBoost uplift model optimizing about $8.69M in operating surplus.",
      "Built a RAG platform for regulatory research using Llama, LangChain, and Supabase."
    ],
    coreSkills: [
      "Python",
      "SQL",
      "Tableau",
      "Power BI",
      "XGBoost",
      "LangChain",
      "Supabase",
      "FastAPI",
      "Risk analytics",
      "Stakeholder management"
    ],
    defaultResponses: [
      {
        questionKey: "work_authorization",
        answer: "Will require sponsorship for long-term U.S. employment.",
        notes: "Reuse only when the portal asks about sponsorship directly."
      },
      {
        questionKey: "location_preference",
        answer: "Open to New York City, nearby hybrid roles, and remote positions in the U.S.",
        notes: "Escalate if relocation policy is a decision factor."
      }
    ]
  },
  automation: {
    autoApplyEnabled: false,
    allowOutreachAgent: false,
    preferredRunMode: "search_and_packet",
    dryRunDefault: true,
    maxApplicationsPerRun: 5,
    dailyApplyCap: 5,
    dailyOutreachCap: 20
  }
};

export const dashboardSections = [
  "overview",
  "search",
  "applications",
  "outreach",
  "documents",
  "billing",
  "settings"
] as const;

export type DashboardSection = (typeof dashboardSections)[number];
