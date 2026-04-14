from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .models import (
    GeneratePacketRequest,
    PlanSupportedApplyRequest,
    ReviewBlockedQuestionsRequest,
    SaveAnswerRequest,
    SearchJobsRequest,
)
from .service import (
    describe_auto_apply_workflow,
    generate_packet,
    get_answer_memory_policy,
    get_apply_guardrails,
    get_profile_schema,
    get_run_modes,
    get_supported_portal_matrix,
    health_check,
    list_agent_capabilities,
    list_job_queue,
    plan_supported_apply,
    review_blocked_questions,
    save_answer_for_future,
    search_jobs,
)

mcp = FastMCP("Instaply MCP")


@mcp.tool()
def health_check_tool() -> dict:
    return health_check().model_dump()


@mcp.tool()
def list_agent_capabilities_tool() -> dict:
    return list_agent_capabilities().model_dump()


@mcp.tool()
def get_profile_schema_tool() -> dict:
    return get_profile_schema().model_dump()


@mcp.tool()
def get_run_modes_tool() -> dict:
    return get_run_modes().model_dump()


@mcp.tool()
def describe_auto_apply_workflow_tool() -> dict:
    return describe_auto_apply_workflow().model_dump()


@mcp.tool()
def get_supported_portal_matrix_tool() -> dict:
    return get_supported_portal_matrix().model_dump()


@mcp.tool()
def get_answer_memory_policy_tool() -> dict:
    return get_answer_memory_policy().model_dump()


@mcp.tool()
def get_apply_guardrails_tool() -> dict:
    return get_apply_guardrails().model_dump()


@mcp.tool()
def search_jobs_tool(
    user_id: str,
    run_mode: str = "search_only",
    portals: list[str] | None = None,
    target_roles: list[str] | None = None,
    preferred_locations: list[str] | None = None,
    company_allowlist: list[str] | None = None,
    company_denylist: list[str] | None = None,
    max_companies: int = 200,
    recent_posting_days: int = 7,
) -> dict:
    request = SearchJobsRequest(
        user_id=user_id,
        run_mode=run_mode,
        portals=portals or [],
        target_roles=target_roles or [],
        preferred_locations=preferred_locations or [],
        company_allowlist=company_allowlist or [],
        company_denylist=company_denylist or [],
        max_companies=max_companies,
        recent_posting_days=recent_posting_days,
    )
    return search_jobs(request).model_dump()


@mcp.tool()
def list_job_queue_tool(user_id: str) -> dict:
    return list_job_queue(user_id).model_dump()


@mcp.tool()
def generate_packet_tool(
    user_id: str,
    job_id: str,
    resume_format: str | None = None,
    cover_letter_format: str | None = None,
) -> dict:
    request = GeneratePacketRequest(
        user_id=user_id,
        job_id=job_id,
        resume_format=resume_format,
        cover_letter_format=cover_letter_format,
    )
    return generate_packet(request).model_dump()


@mcp.tool()
def plan_supported_apply_tool(
    user_id: str,
    job_id: str,
    run_mode: str = "apply_plan_only",
    allow_autosubmit: bool = False,
) -> dict:
    request = PlanSupportedApplyRequest(
        user_id=user_id,
        job_id=job_id,
        run_mode=run_mode,
        allow_autosubmit=allow_autosubmit,
    )
    return plan_supported_apply(request).model_dump()


@mcp.tool()
def review_blocked_questions_tool(user_id: str, job_id: str | None = None) -> dict:
    request = ReviewBlockedQuestionsRequest(user_id=user_id, job_id=job_id)
    return review_blocked_questions(request).model_dump()


@mcp.tool()
def save_answer_for_future_tool(
    user_id: str,
    question_key: str,
    answer: str,
    source_portal: str = "unknown",
    notes: str | None = None,
) -> dict:
    request = SaveAnswerRequest(
        user_id=user_id,
        question_key=question_key,
        answer=answer,
        source_portal=source_portal,
        notes=notes,
    )
    return save_answer_for_future(request).model_dump()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
