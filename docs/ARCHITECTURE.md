# Instaply Architecture

## Goal

Build Instaply as a private, multi-tenant, agentic application platform that is not tied to any one laptop.

## Recommended Runtime

- `apps/web`: Next.js on Vercel
- `apps/api`: Python API service on Railway
- `apps/mcp`: Python MCP server on Railway
- `apps/worker`: Python browser automation workers on Railway or dedicated containers
- `auth + postgres + storage`: Supabase
- `billing`: Stripe
- `model providers`: NVIDIA NIM primary, Fireworks fallback

## Core Orchestration Rule

Instaply should treat NVIDIA NIM as the reasoning engine, not as the MCP server.

That means:

- MCP exposes the tool surface
- the API/MCP layer translates available tools into model-usable tool definitions
- NVIDIA NIM performs reasoning and returns tool calls
- Instaply executes those tool calls in its own services and workers

This keeps the product private, auditable, and portable across model providers.

## Core Services

### 1. Web App

Responsibilities:

- onboarding
- auth
- profile management
- resume and cover-letter preference management
- portal selection
- company suggestions
- application data collection
- queue and results UI
- billing and account pages

### 2. API Service

Responsibilities:

- business logic
- job search orchestration
- ranking
- packet generation
- company recommendation logic
- account and plan rules
- secure state transitions
- validation against shared contracts

### 3. MCP Service

Responsibilities:

- assistant-facing tool surface
- authenticated per-user operations
- search tools
- queue tools
- packet tools
- later apply-planning and execution tools
- tool schema translation for model-facing orchestration
- server-side tool execution policy
- explicit run-mode boundaries

### 4. Worker Service

Responsibilities:

- async job fetching
- packet generation
- browser execution
- screenshot/evidence capture
- retries and failure handling

### 5. Shared Contracts Package

Responsibilities:

- candidate profile shape
- preferences schema
- portal and plan enums
- pipeline stage definitions
- run-mode definitions

This package should be consumed by:

- web
- API
- MCP
- workers

## Security Boundaries

- no direct dependency on a founder laptop
- no local SQLite as the product database
- no personal SMTP credentials embedded in runtime
- no broad filesystem access in production
- per-user data isolation
- encrypted secrets
- event/audit logs

## Auto-Apply Design

The correct rollout is:

1. apply planning only
2. supported portal execution
3. blocked-question review
4. evidence-backed submission confirmation

Do not expose broad unrestricted auto-apply as a first release.

## Pipeline Model

Instaply should standardize on these stages:

1. `search`
2. `enrich`
3. `rank`
4. `tailor_packet`
5. `apply_plan`
6. `supported_apply`
7. `report_outcome`

This keeps the product explainable and makes MCP tool orchestration easier to audit.

## NIM Fit

NVIDIA NIM fits well because it provides hosted LLM endpoints and tool-calling support. But Instaply still owns:

- MCP
- tool definitions
- execution policy
- browser workers
- final application state
