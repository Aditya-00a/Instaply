# Run Modes

## Goal

Instaply should let users and operators choose how far the agent is allowed to go.

That means exposing clear run modes instead of one all-or-nothing automation switch.

## Canonical Run Modes

### `search_only`

Use when the user wants:

- company-first job discovery
- ranking
- no document generation
- no apply actions

### `search_and_packet`

Use when the user wants:

- search
- ranking
- tailored resume and cover letter
- no apply execution

### `apply_plan_only`

Use when the user wants:

- portal strategy
- required answers
- blocker identification
- no browser execution yet

### `dry_run_apply`

Use when the user wants:

- browser rehearsal
- portal validation
- no final submit

### `supported_apply`

Use when the user wants:

- full supported-portal execution
- evidence-backed results
- blocked or failed states surfaced honestly

### `outreach_only`

Use when the user wants:

- people discovery
- outreach drafting
- sending within outreach guardrails

### `full_agent_cycle`

Use only when the account and plan explicitly allow:

- search
- packet generation
- apply planning
- supported apply
- outreach

## Utility Actions

Instaply should also expose safe utility actions:

- dry run
- retry failed stage
- mark applied
- mark blocked
- reset failed attempt
- skip company
- save answer for future

## Search Control Patterns

Borrow the operational patterns, not the local-bot architecture:

- allowlist companies the user wants to prioritize
- denylist companies the user never wants resurfaced
- cap applications per run
- keep dry run available as a normal operator mode
- store unanswered questions in a reusable review queue

## ApplyPilot Lesson We Should Keep

ApplyPilot gets one thing very right here: stages and utility actions stay separate.

Instaply should preserve that clarity in both UI and MCP tools.
