CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  company TEXT NOT NULL,
  location TEXT,
  url TEXT,
  source TEXT,
  jd_text TEXT,
  match_score REAL,
  status TEXT DEFAULT 'new',
  resume_version TEXT,
  cover_letter_version TEXT,
  date_found TEXT,
  date_applied TEXT,
  source_urls_json TEXT,
  visa_sponsorship_likely INTEGER DEFAULT 0,
  visa_sponsorship_blocked INTEGER DEFAULT 0,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS resume_versions (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  resume_json TEXT NOT NULL,
  cover_letter_text TEXT,
  pdf_path TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(job_id) REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS resume_generations (
  id TEXT PRIMARY KEY,
  role_bucket TEXT NOT NULL,
  company TEXT,
  role_title TEXT,
  company_background TEXT,
  jd_hash TEXT NOT NULL,
  jd_text TEXT NOT NULL,
  tailored_resume_json TEXT NOT NULL,
  selection_summary_json TEXT,
  pdf_path TEXT,
  docx_path TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS resume_feedback (
  id TEXT PRIMARY KEY,
  generation_id TEXT NOT NULL,
  decision TEXT NOT NULL,
  notes TEXT,
  kept_experience_json TEXT,
  removed_experience_json TEXT,
  kept_projects_json TEXT,
  removed_projects_json TEXT,
  kept_publications_json TEXT,
  removed_publications_json TEXT,
  kept_leadership_json TEXT,
  removed_leadership_json TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(generation_id) REFERENCES resume_generations(id)
);

CREATE TABLE IF NOT EXISTS cover_letter_generations (
  id TEXT PRIMARY KEY,
  role_bucket TEXT NOT NULL,
  company TEXT,
  role_title TEXT,
  company_background TEXT,
  jd_hash TEXT NOT NULL,
  jd_text TEXT NOT NULL,
  cover_letter_text TEXT NOT NULL,
  selection_summary_json TEXT,
  docx_path TEXT,
  pdf_path TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cover_letter_feedback (
  id TEXT PRIMARY KEY,
  generation_id TEXT NOT NULL,
  decision TEXT NOT NULL,
  tone TEXT,
  notes TEXT,
  kept_examples_json TEXT,
  removed_examples_json TEXT,
  kept_projects_json TEXT,
  removed_projects_json TEXT,
  kept_paragraph_emphasis_json TEXT,
  removed_paragraph_emphasis_json TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(generation_id) REFERENCES cover_letter_generations(id)
);

CREATE TABLE IF NOT EXISTS review_preferences (
  id TEXT PRIMARY KEY,
  applies_to TEXT NOT NULL,
  role_bucket TEXT NOT NULL,
  preference_type TEXT NOT NULL,
  item_name TEXT NOT NULL,
  value TEXT,
  weight INTEGER DEFAULT 2,
  active INTEGER DEFAULT 1,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS job_status_events (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT NOT NULL,
  reason TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(job_id) REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS source_scan_history (
  id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  company TEXT NOT NULL,
  source_url TEXT,
  scanned_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS career_site_discovery (
  id TEXT PRIMARY KEY,
  normalized_company TEXT NOT NULL,
  company TEXT NOT NULL,
  official_domain TEXT,
  careers_url TEXT,
  ats_provider TEXT,
  ats_target TEXT,
  source_url TEXT,
  status TEXT DEFAULT 'active',
  confidence REAL DEFAULT 0.6,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_runtime_state (
  scope TEXT PRIMARY KEY,
  agent_enabled INTEGER DEFAULT 1,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS application_answers (
  id TEXT PRIMARY KEY,
  scope TEXT NOT NULL,
  prompt_key TEXT NOT NULL,
  prompt_text TEXT NOT NULL,
  control_kind TEXT,
  answer_text TEXT NOT NULL,
  answer_source TEXT DEFAULT 'rule',
  confidence REAL DEFAULT 0.7,
  active INTEGER DEFAULT 1,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_company_title_location ON jobs(company, title, location);
CREATE INDEX IF NOT EXISTS idx_resume_generations_role_bucket ON resume_generations(role_bucket);
CREATE INDEX IF NOT EXISTS idx_resume_feedback_generation_id ON resume_feedback(generation_id);
CREATE INDEX IF NOT EXISTS idx_cover_letter_generations_role_bucket ON cover_letter_generations(role_bucket);
CREATE INDEX IF NOT EXISTS idx_cover_letter_feedback_generation_id ON cover_letter_feedback(generation_id);
CREATE INDEX IF NOT EXISTS idx_review_preferences_scope_role ON review_preferences(applies_to, role_bucket);
CREATE INDEX IF NOT EXISTS idx_job_status_events_job_id ON job_status_events(job_id);
CREATE INDEX IF NOT EXISTS idx_source_scan_history_scope ON source_scan_history(source, company, scanned_at);
CREATE INDEX IF NOT EXISTS idx_career_site_discovery_lookup ON career_site_discovery(normalized_company, ats_provider, status, updated_at);
CREATE INDEX IF NOT EXISTS idx_application_answers_lookup ON application_answers(prompt_key, scope, control_kind, active);

CREATE TABLE IF NOT EXISTS application_tracking (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ready',
  applied_at TEXT,
  applied_via TEXT,
  response_received_at TEXT,
  response_type TEXT,
  interview_scheduled_at TEXT,
  interview_notes TEXT,
  offer_received_at TEXT,
  offer_details TEXT,
  outcome TEXT,
  followup_due_at TEXT,
  followup_count INTEGER DEFAULT 0,
  last_followup_at TEXT,
  notes TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY(job_id) REFERENCES jobs(id)
);
CREATE INDEX IF NOT EXISTS idx_application_tracking_job_id ON application_tracking(job_id);
CREATE INDEX IF NOT EXISTS idx_application_tracking_status ON application_tracking(status);
CREATE INDEX IF NOT EXISTS idx_application_tracking_followup ON application_tracking(followup_due_at, status);
