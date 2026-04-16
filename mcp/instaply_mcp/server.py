"""Instaply MCP server.

Exposes 5 tools to Claude Desktop (stdio transport). Each tool is a thin
HTTP shell over our existing FastAPI at api.asion.ai — the MCP server holds
NO business logic. Business rules (credit gate, fit threshold, per-company
cap, anti-abuse) all live in the API where they can be enforced once and
shared with the web dashboard.

Auth model:
  The user pastes their JWT (Supabase access token) into the MCP config as
  INSTAPLY_TOKEN env var. They get this token from their dashboard at
  instaply.asion.ai/settings/mcp — it's long-lived (6 months) and revocable.

Config snippet for ~/.config/claude/claude_desktop_config.json (mac/linux)
or %APPDATA%/Claude/claude_desktop_config.json (windows):

  {
    "mcpServers": {
      "instaply": {
        "command": "uvx",
        "args": ["instaply-mcp"],
        "env": {
          "INSTAPLY_TOKEN": "eyJ..."
        }
      }
    }
  }
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Optional

import httpx
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool


API_BASE = os.environ.get("INSTAPLY_API_BASE", "https://api.asion.ai")
TOKEN = os.environ.get("INSTAPLY_TOKEN", "")
TIMEOUT = httpx.Timeout(20.0, connect=5.0)


def _headers() -> dict[str, str]:
    if not TOKEN:
        raise RuntimeError(
            "INSTAPLY_TOKEN env var is not set. "
            "Get your token from https://instaply.asion.ai/settings/mcp"
        )
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "instaply-mcp/0.1.0",
    }


# ─── Tool implementations ────────────────────────────────────────
async def _search_jobs(query: str, location: Optional[str] = None, limit: int = 20) -> dict:
    payload = {"query": query, "limit": min(max(limit, 1), 50)}
    if location:
        payload["location"] = location
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(f"{API_BASE}/jobs/search", headers=_headers(), json=payload)
        r.raise_for_status()
        return r.json()


async def _queue_application(
    job_id: Optional[str] = None,
    job_url: Optional[str] = None,
    resume_id: Optional[str] = None,
) -> dict:
    if not job_id and not job_url:
        raise ValueError("Provide either job_id or job_url")
    payload: dict[str, Any] = {}
    if job_id:
        payload["job_id"] = job_id
    if job_url:
        payload["job_url"] = job_url
    if resume_id:
        payload["resume_id"] = resume_id
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.post(
            f"{API_BASE}/applications/queue", headers=_headers(), json=payload
        )
        if r.status_code == 402:
            return {
                "error": "out_of_credits",
                "message": "You're out of credits. Buy a pack at https://instaply.asion.ai/billing "
                           "(10 credits for $10, 30 for $25, or 70 for $50).",
            }
        r.raise_for_status()
        return r.json()


async def _list_applications(status: Optional[str] = None, limit: int = 50) -> dict:
    params: dict[str, Any] = {"limit": min(max(limit, 1), 200)}
    if status:
        params["status_filter"] = status
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(f"{API_BASE}/applications", headers=_headers(), params=params)
        r.raise_for_status()
        return r.json()


async def _get_credits() -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.get(f"{API_BASE}/credits", headers=_headers())
        r.raise_for_status()
        return r.json()


async def _update_profile(patch: dict) -> dict:
    async with httpx.AsyncClient(timeout=TIMEOUT) as c:
        r = await c.patch(f"{API_BASE}/profile", headers=_headers(), json=patch)
        r.raise_for_status()
        return r.json()


# ─── MCP wiring ──────────────────────────────────────────────────
server = Server("instaply")


TOOLS: list[Tool] = [
    Tool(
        name="search_jobs",
        description=(
            "Search the Instaply job catalog by title and optional location. "
            "Returns up to 50 matching jobs with company, title, location, and job_id. "
            "Use this before queue_application when the user describes a role in natural language."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Job title or keywords (e.g. 'senior software engineer')"},
                "location": {"type": "string", "description": "Optional location filter (e.g. 'New York' or 'Remote')"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="queue_application",
        description=(
            "Queue a job application. Provide either job_id (from search_jobs) or a job_url "
            "(must already exist in Instaply's catalog). Consumes one credit when the submission "
            "is confirmed via email — never before. Returns an application record with status='queued'."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "UUID from search_jobs results"},
                "job_url": {"type": "string", "description": "Full application URL (alternative to job_id)"},
                "resume_id": {"type": "string", "description": "Optional non-default resume UUID"},
            },
        },
    ),
    Tool(
        name="list_applications",
        description=(
            "List the user's applications, newest first. Each application row includes status, "
            "company, title, fit_score, and timestamps. Status values: queued, in_progress, "
            "submitted, confirmed, failed, needs_review, skipped."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["queued", "in_progress", "submitted", "confirmed", "failed", "needs_review", "skipped"],
                    "description": "Optional status filter",
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 200, "default": 50},
            },
        },
    ),
    Tool(
        name="get_credits",
        description=(
            "Get the user's current credit balance, plan, and free-tier usage. "
            "Call this before big batch operations to check if the user has enough credits."
        ),
        inputSchema={"type": "object", "properties": {}},
    ),
    Tool(
        name="update_profile",
        description=(
            "Partially update the user's profile. Only include fields to change. "
            "Fields: first_name, last_name, phone_e164, linkedin_url, github_url, portfolio_url, "
            "city, state, country, postal_code, work_auth_status ('citizen'|'gc'|'h1b'|'opt'|'cpt'|'other'|'none'), "
            "needs_sponsorship (bool), current_company, current_title, years_experience (int), "
            "school, degree, major, graduation_year (int), willing_to_relocate (bool), "
            "salary_expectation_usd (int), earliest_start_date (ISO date)."
        ),
        inputSchema={
            "type": "object",
            "properties": {"patch": {"type": "object", "description": "Sparse dict of fields to update"}},
            "required": ["patch"],
        },
    ),
]


@server.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if name == "search_jobs":
            result = await _search_jobs(**arguments)
        elif name == "queue_application":
            result = await _queue_application(**arguments)
        elif name == "list_applications":
            result = await _list_applications(**arguments)
        elif name == "get_credits":
            result = await _get_credits()
        elif name == "update_profile":
            result = await _update_profile(arguments.get("patch", {}))
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
    except httpx.HTTPStatusError as e:
        try:
            detail = e.response.json()
        except Exception:
            detail = {"status": e.response.status_code, "text": e.response.text[:500]}
        return [TextContent(type="text", text=f"API error: {json.dumps(detail, indent=2)}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {type(e).__name__}: {e}")]


async def _run() -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
