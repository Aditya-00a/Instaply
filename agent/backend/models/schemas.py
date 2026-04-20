from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    llm_provider: str
    llm_reachable: bool
    ollama_reachable: bool
    model_name: str
    database_path: str


class AgentRuntimeResponse(BaseModel):
    scope: str
    agent_enabled: bool
    updated_at: str = ""
    status: str
    loop_running: bool = False
    last_cycle_at: str = ""
    last_status: str = ""
    last_summary: str = ""
    last_error: str = ""


class MatchJDRequest(BaseModel):
    jd_text: str = Field(..., min_length=20)
    profile: dict[str, Any]


class LLMTestRequest(BaseModel):
    prompt: str = "Reply with the single word: working"
    system: str = ""


class LLMTestResponse(BaseModel):
    llm_provider: str
    model_name: str
    output: str


class MatchJDResponse(BaseModel):
    match_score: float
    match_reasons: list[str]
    top_keywords: list[str]
    role_bucket: str
    visa_sponsorship_likely: bool
    visa_sponsorship_blocked: bool = False


class TailorResumeRequest(BaseModel):
    jd_text: str
    master_resume: dict[str, Any]
    company_context: dict[str, Any] = Field(default_factory=dict)
    company_background: str = ""


class TailorResumeResponse(BaseModel):
    role_bucket: str
    selected_summary: str
    keyword_hits: list[str]
    tailored_resume: dict[str, Any]
    ats_notes: list[str]
    guardrails: dict[str, Any]
    selection_summary: dict[str, Any]
    jd_parse: dict[str, Any]
    learning_profile: dict[str, Any]


class CoverLetterRequest(BaseModel):
    jd_text: str
    profile: dict[str, Any]
    company_context: dict[str, Any] = Field(default_factory=dict)
    master_resume: dict[str, Any] = Field(default_factory=dict)


class CoverLetterResponse(BaseModel):
    role_bucket: str
    cover_letter: str


class BuildCoverLetterDocumentRequest(BaseModel):
    cover_letter: str
    contact: dict[str, Any]
    company_context: dict[str, Any] = Field(default_factory=dict)
    date_text: str = ""
    recipient_lines: list[str] = Field(default_factory=list)
    signature_name: str = "[user]"
    output_filename: str = "cover_letter"
    output_dir: str | None = None


class BuildCoverLetterDocumentResponse(BaseModel):
    docx_path: str
    pdf_path: str
    page_count: int
    fits_on_one_page: bool
    conversion_method: str
    page_count_method: str
    applied_design: dict[str, Any]


class CoverLetterGenerateRequest(BaseModel):
    jd_text: str
    profile: dict[str, Any]
    master_resume: dict[str, Any]
    company_context: dict[str, Any] = Field(default_factory=dict)
    company_background: str = ""
    output_filename: str = "cover_letter"
    output_dir: str | None = None
    date_text: str = ""
    recipient_lines: list[str] = Field(default_factory=list)


class CoverLetterGenerateResponse(BaseModel):
    generation_id: str
    role_bucket: str
    cover_letter: str
    selection_summary: dict[str, Any]
    document_result: dict[str, Any]
    learning_profile: dict[str, Any]


class ApplicationPacketRequest(BaseModel):
    jd_text: str
    profile: dict[str, Any]
    master_resume: dict[str, Any]
    company_context: dict[str, Any] = Field(default_factory=dict)
    company_background: str = ""
    output_basename: str = "application_packet"
    output_dir: str | None = None
    date_text: str = ""
    recipient_lines: list[str] = Field(default_factory=list)


class ApplicationPacketResponse(BaseModel):
    role_bucket: str
    generation_ids: dict[str, str]
    tailored_resume: dict[str, Any]
    cover_letter: str
    pdfs: dict[str, str]
    documents: dict[str, Any]
    selection_summaries: dict[str, Any]
    resume: dict[str, Any]
    cover_letter_result: dict[str, Any]
    suggested_review_commands: list[dict[str, str]]


class CoverLetterFeedbackRequest(BaseModel):
    generation_id: str
    decision: str
    tone: str = ""
    notes: str = ""
    kept_examples: list[str] = Field(default_factory=list)
    removed_examples: list[str] = Field(default_factory=list)
    kept_projects: list[str] = Field(default_factory=list)
    removed_projects: list[str] = Field(default_factory=list)
    kept_paragraph_emphasis: list[str] = Field(default_factory=list)
    removed_paragraph_emphasis: list[str] = Field(default_factory=list)


class CoverLetterFeedbackResponse(BaseModel):
    feedback_id: str
    generation_id: str
    decision: str
    applied_feedback: dict[str, Any]
    learning_profile: dict[str, Any]


class DraftOutreachRequest(BaseModel):
    recipient_name: str
    recipient_title: str
    recipient_company: str
    recipient_public_content: list[dict[str, Any]] = Field(default_factory=list)
    job_context: dict[str, Any] = Field(default_factory=dict)
    user_profile: dict[str, Any] = Field(default_factory=dict)
    outreach_angle: str = ""


class DraftOutreachResponse(BaseModel):
    subject_line: str
    body: str
    personalization_proof: list[str]


class QualityCheckRequest(BaseModel):
    subject_line: str
    body: str
    personalization_proof: list[str] = Field(default_factory=list)


class QualityCheckResponse(BaseModel):
    approved: bool
    scores: dict[str, int]
    feedback: list[str]


class RenderPDFRequest(BaseModel):
    title: str = "Generated Document"
    sections: list[dict[str, Any]]


class BuildATSResumePDFRequest(BaseModel):
    tailored_resume: dict[str, Any]
    output_filename: str = "resume"
    output_dir: str | None = None


class BuildATSResumePDFResponse(BaseModel):
    docx_path: str
    pdf_path: str
    page_count: int
    fits_on_one_page: bool
    applied_layout: dict[str, Any]
    conversion_method: str
    page_count_method: str


class ResumeGenerateRequest(BaseModel):
    jd_text: str
    master_resume: dict[str, Any]
    company_context: dict[str, Any] = Field(default_factory=dict)
    company_background: str = ""
    output_filename: str = "resume"
    output_dir: str | None = None


class ResumeGenerateResponse(BaseModel):
    generation_id: str
    role_bucket: str
    selected_summary: str
    keyword_hits: list[str]
    tailored_resume: dict[str, Any]
    ats_notes: list[str]
    guardrails: dict[str, Any]
    selection_summary: dict[str, Any]
    jd_parse: dict[str, Any]
    pdf_result: dict[str, Any]
    learning_profile: dict[str, Any]


class ResumeFeedbackRequest(BaseModel):
    generation_id: str
    decision: str
    notes: str = ""
    kept_experience: list[str] = Field(default_factory=list)
    removed_experience: list[str] = Field(default_factory=list)
    kept_projects: list[str] = Field(default_factory=list)
    removed_projects: list[str] = Field(default_factory=list)
    kept_publications: list[str] = Field(default_factory=list)
    removed_publications: list[str] = Field(default_factory=list)
    kept_leadership: list[str] = Field(default_factory=list)
    removed_leadership: list[str] = Field(default_factory=list)


class ResumeFeedbackResponse(BaseModel):
    feedback_id: str
    generation_id: str
    decision: str
    applied_feedback: dict[str, Any]
    learning_profile: dict[str, Any]


class ReviewCommandRequest(BaseModel):
    command: str
    generation_id: str = ""
    role_bucket: str = ""


class ReviewCommandResponse(BaseModel):
    command: str
    action: str
    result: dict[str, Any]


class ReviewInboxRequest(BaseModel):
    limit: int = 20
    statuses: list[str] = Field(default_factory=list)


class ReviewInboxResponse(BaseModel):
    count: int
    applied_count: int
    retention_policy: dict[str, Any]
    statuses: list[str]
    items: list[dict[str, Any]]


class ReviewInboxActionRequest(BaseModel):
    job_id: str
    target: str
    action: str
    notes: str = ""
    command: str = ""
    tone: str = ""
    kept_experience: list[str] = Field(default_factory=list)
    removed_experience: list[str] = Field(default_factory=list)
    kept_projects: list[str] = Field(default_factory=list)
    removed_projects: list[str] = Field(default_factory=list)
    kept_publications: list[str] = Field(default_factory=list)
    removed_publications: list[str] = Field(default_factory=list)
    kept_leadership: list[str] = Field(default_factory=list)
    removed_leadership: list[str] = Field(default_factory=list)
    kept_examples: list[str] = Field(default_factory=list)
    removed_examples: list[str] = Field(default_factory=list)
    kept_paragraph_emphasis: list[str] = Field(default_factory=list)
    removed_paragraph_emphasis: list[str] = Field(default_factory=list)
    contact_selector: str = ""


class ReviewInboxActionResponse(BaseModel):
    job_id: str
    target: str
    action: str
    result: dict[str, Any]
    retention: dict[str, Any]
    autofill: dict[str, Any] = Field(default_factory=dict)
    item: dict[str, Any]


class WhatsAppDailyReviewRequest(BaseModel):
    sender_id: str = ""
    greenhouse_companies: list[str] = Field(default_factory=list)
    lever_companies: list[str] = Field(default_factory=list)
    workday_companies: list[str] = Field(default_factory=list)
    limit_per_source: int = 20
    max_packets: int = 5
    output_dir: str | None = None
    date_text: str = ""


class WhatsAppReplyRequest(BaseModel):
    sender_id: str = ""
    message_text: str


class WhatsAppReviewResponse(BaseModel):
    message_text: str
    attachments: list[str]
    context: str
    review_queue: list[dict[str, Any]] = Field(default_factory=list)
    generated_packets: int = 0
    result: dict[str, Any] = Field(default_factory=dict)


class WhatsAppInstantReviewResponse(BaseModel):
    generated_packets: int
    messages: list[dict[str, Any]] = Field(default_factory=list)


class ReviewEmailRequest(BaseModel):
    recipient_email: str = ""
    subject: str = "JobAgent review-ready matches"
    limit: int = 3
    attach_files: bool = True
    min_match_score: float = 0.0
    run_pipeline_first: bool = False
    greenhouse_companies: list[str] = Field(default_factory=list)
    lever_companies: list[str] = Field(default_factory=list)
    workday_companies: list[str] = Field(default_factory=list)
    limit_per_source: int = 20
    max_packets: int = 5
    output_dir: str | None = None
    date_text: str = ""


class ReviewEmailResponse(BaseModel):
    sent: bool
    recipient_email: str
    item_count: int
    attachments: list[str] = Field(default_factory=list)
    message: str
    pipeline_result: dict[str, Any] = Field(default_factory=dict)


class PeopleEmailRequest(BaseModel):
    job_id: str
    recipient_email: str = ""
    subject: str = ""


class PeopleEmailResponse(BaseModel):
    sent: bool
    recipient_email: str
    item_count: int
    attachments: list[str] = Field(default_factory=list)
    message: str
    people_result: dict[str, Any] = Field(default_factory=dict)


class FindPeopleForJobRequest(BaseModel):
    job_id: str
    limit: int = 3


class FindPeopleForJobResponse(BaseModel):
    job_id: str
    company: str
    job_title: str
    company_domain: str = ""
    organization: dict[str, Any] = Field(default_factory=dict)
    people: list[dict[str, Any]] = Field(default_factory=list)
    outreach_drafts: list[dict[str, Any]] = Field(default_factory=list)


class EmailReplyProcessRequest(BaseModel):
    limit: int = 10
    unseen_only: bool = True
    mailbox_name: str = "INBOX"


class EmailReplyProcessResponse(BaseModel):
    mailbox: str
    processed_count: int
    skipped_count: int
    processed: list[dict[str, Any]] = Field(default_factory=list)
    skipped: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Autofill
# ---------------------------------------------------------------------------


class AutofillRequest(BaseModel):
    job_url: str = Field(..., min_length=8)
    profile: dict[str, Any] = Field(default_factory=dict)
    resume_pdf_path: str | None = None
    cover_letter_pdf_path: str | None = None
    resume_docx_path: str = ""
    cover_letter_docx_path: str = ""
    prefer_docx: bool = True


class AutofillResponse(BaseModel):
    status: str
    screenshot_path: str = ""
    filled_fields: list[str] = Field(default_factory=list)
    needs_review: list[dict[str, str]] = Field(default_factory=list)
    platform_detected: str = "generic"


class StoreAnswerRequest(BaseModel):
    question_pattern: str = Field(..., min_length=3)
    answer: str
    scope: str = "global"


class StoreAnswerResponse(BaseModel):
    id: str
    prompt_key: str
    scope: str
    status: str


# ---------------------------------------------------------------------------
# Re-score
# ---------------------------------------------------------------------------


class ScoreChange(BaseModel):
    job_id: str
    title: str
    company: str
    old_score: float
    new_score: float


class RescoreRequest(BaseModel):
    min_old_score: float = 0.0


class RescoreResponse(BaseModel):
    rescored_count: int
    score_changes: list[ScoreChange]


# ---------------------------------------------------------------------------
# Application Tracking
# ---------------------------------------------------------------------------


class TrackApplicationRequest(BaseModel):
    job_id: str
    applied_via: str = ""
    notes: str = ""


class TrackApplicationResponse(BaseModel):
    tracking: dict[str, Any]


class UpdateTrackingRequest(BaseModel):
    tracking_id: str
    status: str | None = None
    response_type: str | None = None
    response_received_at: str | None = None
    interview_scheduled_at: str | None = None
    interview_notes: str | None = None
    offer_received_at: str | None = None
    offer_details: str | None = None
    outcome: str | None = None
    notes: str | None = None


class UpdateTrackingResponse(BaseModel):
    tracking: dict[str, Any]


class ListApplicationsRequest(BaseModel):
    status: str | None = None
    limit: int = 50


class ListApplicationsResponse(BaseModel):
    count: int
    items: list[dict[str, Any]]


class FollowupsDueResponse(BaseModel):
    count: int
    items: list[dict[str, Any]]


class ApplicationStatsResponse(BaseModel):
    stats: dict[str, Any]


# ---------------------------------------------------------------------------
# Parse JD
# ---------------------------------------------------------------------------


class ParseJDRequest(BaseModel):
    jd_text: str = Field(..., min_length=20)
    company_context: dict[str, Any] = Field(default_factory=dict)


class SalaryInfo(BaseModel):
    min_salary: int | None = None
    max_salary: int | None = None
    currency: str = "USD"
    period: str = "annual"


class VisaInfo(BaseModel):
    sponsors: bool | None = None
    blocked: bool = False
    signals: list[str] = Field(default_factory=list)


class YearsRequired(BaseModel):
    min_years: int | None = None
    max_years: int | None = None
    raw_text: str = ""


class EducationInfo(BaseModel):
    min_degree: str | None = None
    preferred_degree: str | None = None
    fields: list[str] = Field(default_factory=list)


class ParseJDResponse(BaseModel):
    company_name: str = ""
    role_title: str = ""
    required_skills: list[str] = Field(default_factory=list)
    preferred_qualifications: list[str] = Field(default_factory=list)
    tone: str = ""
    industry: str = ""
    seniority_level: str = ""
    role_type: str = ""
    role_type_label: str = ""
    salary: SalaryInfo = Field(default_factory=SalaryInfo)
    visa_info: VisaInfo = Field(default_factory=VisaInfo)
    years_required: YearsRequired = Field(default_factory=YearsRequired)
    education: EducationInfo = Field(default_factory=EducationInfo)
    work_mode: str = "unknown"
    tools: list[str] = Field(default_factory=list)
