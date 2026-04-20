"""Instaply MCP server.

Local-first by design:
  - profile, answers, jobs, and application history live in SQLite
  - no Instaply backend required
  - no API token required

This server is intended for local MCP clients such as Claude Desktop,
Claude Code, Codex, Cursor, Windsurf, and similar tools.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from . import db
from . import resume as resume_tools
from . import search as search_tools
from . import updates as update_tools


server = Server("instaply")


TOOLS: list[Tool] = [
    Tool(
        name="import_resume",
        description=(
            "Import a local resume into the Instaply profile. Accepts either resume_path "
            "(PDF, DOCX, TXT, or MD on disk) or raw resume_text. Extracts grounded fields "
            "like name, email, links, education, skills, titles, and role targets so the "
            "agent can find jobs on its own from the resume."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "resume_path": {"type": "string", "description": "Absolute path to a local resume file"},
                "resume_text": {"type": "string", "description": "Raw resume text if the client already has it"},
                "overwrite": {"type": "boolean", "description": "Overwrite existing profile fields with extracted values"},
            },
        },
    ),
    Tool(
        name="apply_chat_update",
        description=(
            "Apply a natural-language Instaply update from chat. Use this when the user says things like "
            "'Update my profile: I'm based in New York now', 'Remember this answer: ... -> ...', or "
            "'Mark application abc123 as submitted'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "Natural-language update text from the chat"},
            },
            "required": ["message"],
        },
    ),
    Tool(
        name="update_profile",
        description=(
            "Update the local Instaply profile. Sparse update only: include only the fields you want to change. "
            "Pass null to delete a field. Common fields: full_name, first_name, last_name, email, phone, "
            "phone_e164, linkedin_url, github_url, portfolio_url, city, state, country, postal_code, "
            "current_company, current_title, school, degree, major, work_auth_status, needs_sponsorship, "
            "willing_to_relocate, pronouns, gender, race_ethnicity, veteran_status, disability_status."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "patch": {"type": "object", "description": "Sparse dict of fields to update or null to delete"},
            },
            "required": ["patch"],
        },
    ),
    Tool(
        name="get_profile",
        description="Read the current local Instaply profile as a flat dict.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="search_jobs",
        description=(
            "Search public job sources from the user's machine. If query is omitted, Instaply derives likely "
            "role targets from the imported resume/profile and ranks results by title and skill overlap."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Optional explicit search query"},
                "location": {"type": "string", "description": "Optional explicit location"},
                "remote": {"type": "boolean", "description": "Prefer remote jobs"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
            },
        },
    ),
    Tool(
        name="save_answer",
        description=(
            "Teach the agent an answer to a screening question. The answer will be reused when the same "
            "question or a normalized variant appears on future applications."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Question text as it appears on the form"},
                "answer": {"type": "string", "description": "The answer to save and reuse"},
            },
            "required": ["question", "answer"],
        },
    ),
    Tool(
        name="list_answers",
        description="List saved answers in the local answer vault, newest first.",
        inputSchema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
            },
        },
    ),
    Tool(
        name="delete_answer",
        description="Forget a saved answer by id.",
        inputSchema={
            "type": "object",
            "properties": {
                "answer_id": {"type": "string", "description": "Answer id from list_answers"},
            },
            "required": ["answer_id"],
        },
    ),
    Tool(
        name="list_applications",
        description=(
            "Local audit trail of jobs the agent has acted on. Includes status, company_name, title, apply_url, "
            "queued_at, started_at, and completed_at."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Optional status filter"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100},
            },
        },
    ),
    Tool(
        name="get_status",
        description="Counts of applications by status, plus total jobs cached and total answers saved.",
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="apply_to_job",
        description=(
            "Open the apply_url in the user's local browser, parse the form via the Instaply rules engine, "
            "fill identity fields plus saved-answer reuse, and leave the browser open so the user can solve "
            "captcha and click Submit."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "apply_url": {"type": "string", "description": "Full URL of the application form"},
                "company_name": {"type": "string", "description": "Optional company label for the audit trail"},
                "title": {"type": "string", "description": "Optional role label for the audit trail"},
                "headless": {"type": "boolean", "description": "Default false; keep visible so the user can solve captcha"},
            },
            "required": ["apply_url"],
        },
    ),
    Tool(
        name="mark_complete",
        description=(
            "Mark an application as submitted after the user has clicked Submit on the employer page and seen "
            "the confirmation."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "application_id": {"type": "string", "description": "ID from list_applications or apply_to_job"},
            },
            "required": ["application_id"],
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


def _result(payload: Any) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(payload, indent=2, default=str))]


@server.call_tool()
async def call_tool(name: str, arguments: dict | None) -> list[TextContent]:
    arguments = arguments or {}
    try:
        if name == "import_resume":
            result = resume_tools.import_resume(
                resume_path=arguments.get("resume_path"),
                resume_text=arguments.get("resume_text"),
                overwrite=bool(arguments.get("overwrite", False)),
            )
        elif name == "apply_chat_update":
            result = update_tools.apply_chat_update(arguments["message"])
        elif name == "update_profile":
            result = db.update_profile(arguments.get("patch", {}))
        elif name == "get_profile":
            result = db.get_profile()
        elif name == "search_jobs":
            result = await search_tools.search_jobs(
                query=arguments.get("query"),
                location=arguments.get("location"),
                remote=bool(arguments.get("remote", False)),
                limit=int(arguments.get("limit", 20)),
            )
        elif name == "save_answer":
            result = db.save_answer(arguments["question"], arguments["answer"])
        elif name == "list_answers":
            result = db.list_answers(arguments.get("limit", 100))
        elif name == "delete_answer":
            ok = db.delete_answer(arguments["answer_id"])
            result = {"ok": ok, "deleted": ok}
        elif name == "list_applications":
            result = db.list_applications(
                status=arguments.get("status"),
                limit=arguments.get("limit", 100),
            )
        elif name == "get_status":
            result = db.get_status_summary()
        elif name == "apply_to_job":
            apply_url = arguments["apply_url"]
            headless = bool(arguments.get("headless", False))
            existing_job = db.find_job_by_apply_url(apply_url)
            if existing_job:
                job_id = existing_job["id"]
            else:
                company = arguments.get("company_name") or _domain_of(apply_url) or "Unknown"
                title = arguments.get("title") or "Untitled role"

                import hashlib

                ext_id = "url:" + hashlib.sha256(apply_url.encode("utf-8")).hexdigest()[:16]
                job_id = db.upsert_job(
                    source="manual",
                    external_id=ext_id,
                    company_name=company,
                    title=title,
                    apply_url=apply_url,
                )
            queued = db.queue_application(job_id)

            from . import runner

            runner_result = await runner.apply_locally(
                application_id=queued["application_id"],
                apply_url=apply_url,
                headless=headless,
            )
            result = {"queued": queued, "runner": runner_result}
        elif name == "mark_complete":
            from datetime import datetime, timezone

            app_id = arguments["application_id"]
            ok = db.update_application(
                app_id,
                status="submitted",
                completed_at=datetime.now(timezone.utc).isoformat(),
            )
            result = {"ok": ok, "application_id": app_id, "status": "submitted" if ok else "unchanged"}
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
        return _result(result)
    except KeyError as e:
        return [TextContent(type="text", text=f"Missing required argument: {e}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {type(e).__name__}: {e}")]


def _domain_of(url: str) -> str:
    try:
        from urllib.parse import urlparse

        host = urlparse(url).netloc or ""
        return host.split(".")[-2] if host.count(".") >= 1 else host
    except Exception:
        return ""


async def _run() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
