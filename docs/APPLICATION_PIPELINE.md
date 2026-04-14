# Application Pipeline

## Product Stages

Instaply should expose a clear staged pipeline instead of one opaque "agent run."

The canonical stages are:

1. `search`
2. `enrich`
3. `rank`
4. `tailor_packet`
5. `apply_plan`
6. `supported_apply`
7. `report_outcome`

## Why This Matters

- users can understand what happened
- agents can stop at safe boundaries
- blocked states stay inspectable
- support teams can debug stage by stage
- pricing and credit usage can map to real product value

## Stage Definitions

### Search

Responsibilities:

- company-first discovery
- portal selection filtering
- official careers and ATS resolution
- freshness and location gating

### Enrich

Responsibilities:

- normalize posting fields
- capture job description content
- add sponsorship and company metadata
- collect recruiter or people context when allowed

### Rank

Responsibilities:

- score role fit
- reject senior and weak-fit roles
- apply account-specific preferences
- decide whether a packet should be generated

### Tailor Packet

Responsibilities:

- generate tailored resume
- generate tailored cover letter
- respect user-selected template and tone preferences
- persist packet versions and evidence

### Apply Plan

Responsibilities:

- decide supported portal strategy
- gather required answers from the application vault
- surface unknown or risky questions
- respect company allowlists and denylists
- stop before browser execution if needed

### Supported Apply

Responsibilities:

- execute browser automation only for supported portals
- upload packet files
- answer repeatable questions
- stop on risky or ambiguous submit states

### Report Outcome

Responsibilities:

- mark applied, skipped, blocked, or failed
- attach evidence
- show credits used
- update user-visible history
- persist unanswered-question review items for future runs

## Required UI Visibility

The dashboard should let users inspect:

- current stage
- latest result per stage
- blockers
- screenshots and evidence for apply stages
- credits spent by stage

## ApplyPilot Lesson We Should Keep

The strongest lesson from ApplyPilot is the staged mental model, not the exact implementation.

Instaply should copy:

- explicit phases
- dry-run and apply-plan boundaries
- stage-specific retries

Instaply should avoid:

- pretending all portals are equally automatable
- hiding failures behind a vague "agent ran" message
