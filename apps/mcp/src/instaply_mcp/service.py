from __future__ import annotations

import os
from typing import Any

from .models import (
    CandidatePreferenceSchema,
    GeneratePacketRequest,
    MCPToolResult,
    PipelineStage,
    PlanSupportedApplyRequest,
    PortalId,
    ReviewBlockedQuestionsRequest,
    RunMode,
    SaveAnswerRequest,
    SearchJobsRequest,
    UtilityAction,
    WorkflowOutput,
)


def _environment() -> str:
    return os.getenv("INSTAPLY_ENVIRONMENT", "development")


def _private_route(next_hop: str, **data: Any) -> MCPToolResult:
    return MCPToolResult(
        summary="Request accepted with private candidate data boundary.",
        data={
            "next_hop": next_hop,
            "candidate_data_exposed": False,
            "privacy_mode": "server_side_candidate_vault",
            **data,
        },
    )


def health_check() -> MCPToolResult:
    return MCPToolResult(
        summary="Instaply MCP server is reachable.",
        data={
            "environment": _environment(),
            "agentic_mode": "server_orchestrated",
            "llm_provider_target": os.getenv("INSTAPLY_LLM_PROVIDER", "nvidia_nim"),
            "candidate_data_exposed": False,
        },
    )


def list_agent_capabilities() -> MCPToolResult:
    return MCPToolResult(
        summary="Instaply MCP capabilities enumerated.",
        data={
            "tool_families": [
                "search",
                "queue",
                "packet_generation",
                "apply_planning",
                "workflow_introspection",
                "blocked_question_review",
                "answer_memory",
            ],
            "run_modes": [mode.value for mode in RunMode],
            "pipeline_stages": [stage.value for stage in PipelineStage],
            "utility_actions": [action.value for action in UtilityAction],
        },
    )


def get_profile_schema() -> MCPToolResult:
    schema = CandidatePreferenceSchema()
    return MCPToolResult(
        summary="Candidate workspace profile schema returned.",
        data=schema.model_dump(),
    )


def get_run_modes() -> MCPToolResult:
    return MCPToolResult(
        summary="Run modes returned.",
        data={
            "run_modes": [
                {
                    "id": RunMode.SEARCH_ONLY.value,
                    "purpose": "Find and rank roles only.",
                },
                {
                    "id": RunMode.SEARCH_AND_PACKET.value,
                    "purpose": "Search and generate tailored packet only.",
                },
                {
                    "id": RunMode.APPLY_PLAN_ONLY.value,
                    "purpose": "Prepare portal strategy and blockers without browser execution.",
                },
                {
                    "id": RunMode.DRY_RUN_APPLY.value,
                    "purpose": "Rehearse apply flow without final submit.",
                },
                {
                    "id": RunMode.SUPPORTED_APPLY.value,
                    "purpose": "Run supported portal automation with evidence-backed outcomes.",
                },
                {
                    "id": RunMode.OUTREACH_ONLY.value,
                    "purpose": "Run only the outreach lane.",
                },
                {
                    "id": RunMode.FULL_AGENT_CYCLE.value,
                    "purpose": "Run allowed end-to-end agent flow.",
                },
            ]
        },
    )


def describe_auto_apply_workflow() -> MCPToolResult:
    return MCPToolResult(
        summary="Instaply MCP now reflects Revize's actual auto-apply workflow.",
        data={
            "entry_condition": {
                "job_status": "packet_generated",
                "requires_packet_files": True,
                "must_not_have_tracking_record": True,
                "minimum_score_source": "settings.auto_apply_min_score",
                "cycle_limit_source": "settings.auto_apply_max_per_cycle",
            },
            "stages": [
                {
                    "id": PipelineStage.PICK_APPLY_CANDIDATES.value,
                    "name": "Pick apply candidates",
                    "details": [
                        "Selects packet-generated jobs above the score threshold.",
                        "Skips jobs already present in application tracking.",
                        "Over-fetches candidates so post-filtering does not starve a run.",
                    ],
                },
                {
                    "id": PipelineStage.PREFLIGHT_FILTER.value,
                    "name": "Preflight filter",
                    "details": [
                        "Rejects clearance-required roles using both title and JD text.",
                        "Skips blocked companies and company cooldowns.",
                        "Skips LinkedIn-only apply URLs and queues company ATS discovery instead.",
                    ],
                },
                {
                    "id": PipelineStage.TAILOR_PACKET.value,
                    "name": "Resolve application packet",
                    "details": [
                        "Loads resume and cover letter paths from generation tables.",
                        "Prefers DOCX for submission when the portal accepts it.",
                        "Merges profile and master-resume contact data before browser execution.",
                    ],
                },
                {
                    "id": PipelineStage.ANSWER_VAULT.value,
                    "name": "Answer vault and autofill",
                    "details": [
                        "Looks up reusable answers from application_answers with global/company/job scope.",
                        "Runs portal-specific handlers for Greenhouse, Lever, Workday, iCIMS, Ashby, and SmartRecruiters.",
                        "Applies common work-authorization and EEO fill rules after the platform handler.",
                    ],
                },
                {
                    "id": PipelineStage.PORTAL_AUTOFILL.value,
                    "name": "Persistent browser autofill",
                    "details": [
                        "Uses a persistent real Chrome profile to preserve cookies and trust signals.",
                        "Captures pre-submit screenshots and stores unknown questions for review.",
                        "Retries transient browser failures up to two attempts.",
                    ],
                },
                {
                    "id": PipelineStage.CAPTCHA_AND_SUBMIT.value,
                    "name": "Captcha and submit verification",
                    "details": [
                        "Attempts CapSolver when reCAPTCHA blocks the form or submit.",
                        "Only treats the run as submitted after URL/text/button-state confirmation.",
                        "Captures post-submit screenshots when a submit path succeeds.",
                    ],
                },
                {
                    "id": PipelineStage.REPORT_OUTCOME.value,
                    "name": "Persist outcome",
                    "details": [
                        "Marks successful runs as applied in jobs and application_tracking.",
                        "Marks submit_not_found and needs_review failures as rejected to avoid loops.",
                        "Returns screenshots, filled fields, review blockers, and tracking metadata.",
                    ],
                },
            ],
            "outputs": [output.value for output in WorkflowOutput],
        },
    )


def get_supported_portal_matrix() -> MCPToolResult:
    return MCPToolResult(
        summary="Supported portal behavior returned.",
        data={
            "portals": [
                {
                    "id": PortalId.GREENHOUSE.value,
                    "status": "supported",
                    "notes": [
                        "Handles direct Greenhouse boards and embedded Greenhouse iframes.",
                        "Security-code verification flow is implemented after submit when required.",
                    ],
                },
                {
                    "id": PortalId.LEVER.value,
                    "status": "supported",
                    "notes": [
                        "Uses a dedicated Lever handler for standard profile, radio, and EEO fields.",
                    ],
                },
                {
                    "id": PortalId.WORKDAY.value,
                    "status": "advanced_supported",
                    "notes": [
                        "Supports login/create-account flows, multi-step wizard navigation, education, experience, and custom questions.",
                        "Uses Workday-specific click_filter and React-select workarounds.",
                    ],
                },
                {
                    "id": PortalId.ICIMS.value,
                    "status": "supported",
                    "notes": [
                        "Covered by the platform handler list in the autofill service.",
                    ],
                },
                {
                    "id": PortalId.ASHBY.value,
                    "status": "supported",
                    "notes": [
                        "Covered by the platform handler list in the autofill service.",
                    ],
                },
                {
                    "id": PortalId.SMARTRECRUITERS.value,
                    "status": "supported",
                    "notes": [
                        "Detected and handled through the shared autofill pipeline.",
                    ],
                },
                {
                    "id": PortalId.JOBVITE.value,
                    "status": "search_only",
                    "notes": [
                        "Present in Instaply search preferences, but not in the current autofill platform-handler map.",
                    ],
                },
                {
                    "id": PortalId.TALEO.value,
                    "status": "search_only",
                    "notes": [
                        "Present in Instaply search preferences, but not in the current autofill platform-handler map.",
                    ],
                },
            ]
        },
    )


def get_answer_memory_policy() -> MCPToolResult:
    return MCPToolResult(
        summary="Answer-memory behavior returned.",
        data={
            "storage_model": "application_answers table",
            "scopes": ["global", "company", "job"],
            "resolution_order": [
                "matching scope answer first",
                "global fallback",
                "rule-based answer",
                "LLM answer",
                "human review queue",
            ],
            "what_is_saved": [
                "normalized prompt key",
                "original prompt text",
                "answer text",
                "scope",
                "active flag",
                "confidence/source metadata",
            ],
            "guardrails": [
                "Candidate identity and full answer vault remain server-side.",
                "MCP should expose only review-safe metadata, never raw private profile fields.",
            ],
        },
    )


def get_apply_guardrails() -> MCPToolResult:
    return MCPToolResult(
        summary="Auto-apply guardrails returned.",
        data={
            "hard_filters": [
                "clearance-required roles rejected",
                "blocked companies skipped",
                "company cooldowns enforced",
                "LinkedIn-only apply URLs skipped",
                "missing resume file skips execution",
            ],
            "runtime_safety": [
                "persistent Chrome profile",
                "transient retry limit of 2",
                "pre-submit screenshot capture",
                "post-submit verification before marking applied",
            ],
            "failure_handling": [
                "needs_review and submit_not_found are marked rejected to stop infinite retries",
                "unknown questions are collected for review and optional answer storage",
                "successful runs create tracking records",
            ],
        },
    )


def search_jobs(request: SearchJobsRequest) -> MCPToolResult:
    portals = request.portals or [PortalId.GREENHOUSE, PortalId.LEVER, PortalId.WORKDAY]
    return _private_route(
        "api.search_jobs",
        run_mode=request.run_mode.value,
        portals=[portal.value for portal in portals],
        portal_count=len(portals),
        max_companies=request.max_companies,
        recent_posting_days=request.recent_posting_days,
        company_allowlist_count=len(request.company_allowlist),
        company_denylist_count=len(request.company_denylist),
    )


def list_job_queue(user_id: str) -> MCPToolResult:
    return _private_route(
        "api.list_job_queue",
        expected_sections=["recommended", "packet_ready", "apply_planned", "blocked"],
    )


def generate_packet(request: GeneratePacketRequest) -> MCPToolResult:
    return _private_route(
        "worker.generate_packet",
        resume_format=request.resume_format,
        cover_letter_format=request.cover_letter_format,
    )


def plan_supported_apply(request: PlanSupportedApplyRequest) -> MCPToolResult:
    return _private_route(
        "api.plan_supported_apply",
        run_mode=request.run_mode.value,
        allow_autosubmit=request.allow_autosubmit,
        safety_checks=[
            "supported_portal_only",
            "blocked_question_review",
            "answer_vault_lookup",
            "cooldown_and_clearance_filter",
            "pre_post_submit_evidence",
            "evidence_required",
        ],
    )


def review_blocked_questions(request: ReviewBlockedQuestionsRequest) -> MCPToolResult:
    return _private_route(
        "api.review_blocked_questions",
        review_fields=[
            "question_label",
            "question_type",
            "available_options",
            "suggested_answer",
            "requires_human_review",
        ],
    )


def save_answer_for_future(request: SaveAnswerRequest) -> MCPToolResult:
    return _private_route(
        "api.save_answer_for_future",
        question_key=request.question_key,
        source_portal=request.source_portal,
    )
