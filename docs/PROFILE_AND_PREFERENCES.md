# Profile And Preferences

## Product Rule

Candidate preferences should be first-class product data, not buried in config files.

Instaply should collect and store:

- identity
- authorization
- job search preferences
- resume preferences
- cover-letter preferences
- application answers
- automation policy

## Identity

Collect:

- first name
- last name
- legal full name
- primary email
- phone number
- city, region, country
- LinkedIn
- portfolio
- GitHub

## Authorization

Collect:

- work authorization summary
- whether sponsorship is required
- whether OPT or STEM OPT support matters
- relocation preference
- remote, hybrid, onsite openness

## Job Search Preferences

Collect:

- target roles
- target industries
- preferred locations
- excluded locations
- experience level
- portal selections
- suggested companies
- user-added companies
- company allowlist
- company denylist
- whether the agent may recommend companies
- recency requirement
- minimum company revenue filter

## Resume Preferences

Collect:

- preferred resume format
- one-page versus flexible length
- emphasis tracks
- pinned bullets or experiences
- topics to avoid
- writing voice notes

## Cover-Letter Preferences

Collect:

- preferred cover-letter format
- tone tags
- whether to include a personal story
- whether to include company research
- maximum paragraph target
- phrases to avoid

## Application Profile

Collect:

- current title
- years of experience claim
- education summary
- compensation notes
- signature default
- reusable answers for recurring application prompts

## Automation Policy

Collect:

- whether auto-apply is enabled
- whether final auto-submit is enabled
- whether outreach is enabled
- preferred run mode
- whether dry run is the default
- max applications per run
- daily apply cap
- daily outreach cap

## Blocked Question Review

Instaply should also maintain a user-visible review list for:

- unanswered application questions
- ambiguous dropdowns
- signature or disclosure prompts that need confirmation
- risky questions where the agent has a guess but should not silently use it

Each review item should capture:

- portal
- company
- role
- label
- type
- available options when detectable
- suggested answer
- whether human review is required

## Product Implication

The same shared profile contract should be used by:

- web onboarding
- settings pages
- API validation
- MCP tools
- worker execution

That keeps user intent stable across the product.
