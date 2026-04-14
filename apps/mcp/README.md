# Instaply MCP

This app is the assistant-facing MCP service for Instaply.

It is the product boundary between:

- Claude/Desktop or ChatGPT-style clients
- Instaply's private API and worker services
- the reasoning model layer such as NVIDIA NIM

## Product Rule

NVIDIA NIM is the reasoning layer.

Instaply MCP is the tool surface.

That means:

- MCP defines the tools
- MCP enforces run-mode and plan policy
- MCP authenticates the user context
- MCP forwards approved actions to API and worker services
- MCP returns auditable results back to the client

## Initial Tool Families

- `health_check`
- `list_agent_capabilities`
- `get_profile_schema`
- `get_run_modes`
- `describe_auto_apply_workflow`
- `get_supported_portal_matrix`
- `get_answer_memory_policy`
- `get_apply_guardrails`
- `search_jobs`
- `list_job_queue`
- `generate_packet`
- `plan_supported_apply`
- `review_blocked_questions`
- `save_answer_for_future`

## Revize Workflow Mapping

The MCP surface now reflects the actual legacy Revize apply pipeline instead of a generic placeholder:

- select `packet_generated` jobs above the configured score threshold
- skip tracked jobs, blocked companies, cooldown companies, LinkedIn-only apply URLs, and clearance-heavy roles
- resolve packet files before browser execution
- reuse stored answers from the answer vault with global/company/job scope
- run ATS-specific autofill for Greenhouse, Lever, Workday, iCIMS, Ashby, and SmartRecruiters
- use a persistent Chrome profile for browser trust and continuity
- attempt captcha solving when needed
- capture pre-submit and post-submit screenshots
- verify submission before marking a job as applied
- send failures with unknown questions into review-oriented handling

## Runtime

- Python
- stdio MCP server
- Railway deployment later
- authenticated HTTP calls into the API service

## Current Build Status

This folder now contains:

- a Python MCP app skeleton
- shared model definitions
- mock service layer boundaries
- initial agentic tool surface
- local run scripts

It is not yet wired to Supabase auth or the real Instaply API.
