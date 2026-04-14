from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class PortalId(str, Enum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    WORKDAY = "workday"
    ASHBY = "ashby"
    SMARTRECRUITERS = "smartrecruiters"
    JOBVITE = "jobvite"
    ICIMS = "icims"
    TALEO = "taleo"


class RunMode(str, Enum):
    SEARCH_ONLY = "search_only"
    SEARCH_AND_PACKET = "search_and_packet"
    APPLY_PLAN_ONLY = "apply_plan_only"
    DRY_RUN_APPLY = "dry_run_apply"
    SUPPORTED_APPLY = "supported_apply"
    OUTREACH_ONLY = "outreach_only"
    FULL_AGENT_CYCLE = "full_agent_cycle"


class PipelineStage(str, Enum):
    SEARCH = "search"
    ENRICH = "enrich"
    RANK = "rank"
    TAILOR_PACKET = "tailor_packet"
    PICK_APPLY_CANDIDATES = "pick_apply_candidates"
    PREFLIGHT_FILTER = "preflight_filter"
    APPLY_PLAN = "apply_plan"
    ANSWER_VAULT = "answer_vault"
    PORTAL_AUTOFILL = "portal_autofill"
    CAPTCHA_AND_SUBMIT = "captcha_and_submit"
    SUPPORTED_APPLY = "supported_apply"
    REPORT_OUTCOME = "report_outcome"


class UtilityAction(str, Enum):
    DRY_RUN = "dry_run"
    RETRY_STAGE = "retry_stage"
    MARK_APPLIED = "mark_applied"
    MARK_BLOCKED = "mark_blocked"
    RESET_FAILED_ATTEMPT = "reset_failed_attempt"
    SKIP_COMPANY = "skip_company"
    SAVE_ANSWER_FOR_FUTURE = "save_answer_for_future"


class CandidatePreferenceSchema(BaseModel):
    sections: List[str] = Field(
        default_factory=lambda: [
            "identity",
            "authorization",
            "job_search_preferences",
            "resume_preferences",
            "cover_letter_preferences",
            "application_profile",
            "automation_policy",
        ]
    )
    required_high_risk_fields: List[str] = Field(
        default_factory=lambda: [
            "legal_full_name",
            "primary_email",
            "phone_number",
            "work_authorization_summary",
            "requires_sponsorship",
            "portal_selections",
            "preferred_run_mode",
        ]
    )
    mcp_privacy_boundary: str = Field(
        default="MCP tools should expose only route metadata and task status. Identity, contact details, resumes, cover letters, and answer memory stay server-side."
    )
    never_expose_fields: List[str] = Field(
        default_factory=lambda: [
            "legal_full_name",
            "primary_email",
            "secondary_email",
            "phone_number",
            "linkedin_url",
            "github_url",
            "resume_content",
            "cover_letter_content",
            "answer_vault_entries",
        ]
    )


class SearchJobsRequest(BaseModel):
    user_id: str
    run_mode: RunMode = RunMode.SEARCH_ONLY
    portals: List[PortalId] = Field(default_factory=list)
    target_roles: List[str] = Field(default_factory=list)
    preferred_locations: List[str] = Field(default_factory=list)
    company_allowlist: List[str] = Field(default_factory=list)
    company_denylist: List[str] = Field(default_factory=list)
    max_companies: int = 200
    recent_posting_days: int = 7


class GeneratePacketRequest(BaseModel):
    user_id: str
    job_id: str
    resume_format: Optional[str] = None
    cover_letter_format: Optional[str] = None


class PlanSupportedApplyRequest(BaseModel):
    user_id: str
    job_id: str
    run_mode: RunMode = RunMode.APPLY_PLAN_ONLY
    allow_autosubmit: bool = False


class ReviewBlockedQuestionsRequest(BaseModel):
    user_id: str
    job_id: Optional[str] = None


class SaveAnswerRequest(BaseModel):
    user_id: str
    question_key: str
    source_portal: Literal[
        "greenhouse",
        "lever",
        "workday",
        "ashby",
        "smartrecruiters",
        "jobvite",
        "icims",
        "taleo",
        "unknown",
    ] = "unknown"
    answer: str
    notes: Optional[str] = None


class MCPToolResult(BaseModel):
    ok: bool = True
    summary: str
    data: dict = Field(default_factory=dict)


class WorkflowOutput(str, Enum):
    PRE_SUBMIT_SCREENSHOT = "pre_submit_screenshot"
    POST_SUBMIT_SCREENSHOT = "post_submit_screenshot"
    FILLED_FIELDS = "filled_fields"
    BLOCKED_QUESTIONS = "blocked_questions"
    TRACKING_RECORD = "tracking_record"
    APPLICATION_STATUS = "application_status"
