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

// NOTE: Demo profile only. Replace with the signed-in user's data at runtime.
// Do NOT put real names, phone numbers, or personal emails here — this file is
// shipped to the browser and lives in a public repo.
export const starterCandidateWorkspaceProfile: CandidateWorkspaceProfile = {
  identity: {
    firstName: "Jane",
    lastName: "Doe",
    legalFullName: "Jane Doe",
    primaryEmail: "jane.doe@example.com",
    secondaryEmail: "",
    phoneNumber: "+1 (555) 555-0123",
    currentCity: "New York",
    currentRegion: "NY",
    currentCountry: "United States",
    linkedinUrl: "https://linkedin.com/in/jane-doe",
    portfolioUrl: "",
    githubUrl: ""
  },
  authorization: {
    workAuthorizationSummary: "Authorized to work in the United States.",
    requiresSponsorship: false,
    needsStemOptSupport: false,
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
    currentTitle: "Software Engineer",
    yearsOfExperienceClaim: 2,
    educationSummary: "BS in Computer Science from State University, graduated 2024.",
    educationEntries: [
      "State University - BS in Computer Science - GPA 3.6 - Graduated 2024"
    ],
    workExperienceEntries: [
      "Acme Corp - Software Engineer - Built and shipped backend services in Python and TypeScript.",
      "Beta Inc - Software Engineering Intern - Contributed to internal tooling and CI/CD."
    ],
    projectEntries: [
      "Open-source contributions to a popular web framework.",
      "Personal portfolio site built with Next.js and deployed on Vercel."
    ],
    researchPaperEntries: [],
    compensationNotes: "Open to market compensation.",
    signatureDefault: "Jane Doe",
    experienceHighlights: [
      "Shipped production features used by thousands of users.",
      "Wrote and maintained automated tests across the stack."
    ],
    projectHighlights: [
      "Built a side project with 1k+ GitHub stars.",
      "Contributed bug fixes to several open-source libraries."
    ],
    coreSkills: [
      "Python",
      "TypeScript",
      "SQL",
      "React",
      "Node.js"
    ],
    defaultResponses: [
      {
        questionKey: "work_authorization",
        answer: "Authorized to work in the United States without sponsorship.",
        notes: "Replace with the candidate's true authorization at runtime."
      },
      {
        questionKey: "location_preference",
        answer: "Open to onsite, hybrid, and remote roles in the U.S.",
        notes: "Replace with the candidate's true preference at runtime."
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
