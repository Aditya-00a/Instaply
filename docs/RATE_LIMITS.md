# Rate Limits

## Core Rule

Do not sell unlimited automation early.

Instaply should use a hybrid model:

- base subscription
- included credits
- daily safety caps
- optional add-on credit packs

## Suggested Limits

### Free Trial

- search runs: `3/day`
- packet generations: `5 total`
- auto-apply attempts: `3 total`
- people lookups: `3 total`
- outreach sends: `0 to 2 total`

### Starter

- search runs: `10/day`
- packet generations: `30/month`
- auto-apply attempts: `0`
- people lookups: `10/month`
- outreach sends: `0 to 10/month`

### Apply Pro

- search runs: `20/day`
- packet generations: `100/month`
- auto-apply attempts: `40/month`
- max auto-apply attempts per day: `5`
- max applications per run: `5`
- max concurrent browser runs: `1`

### Outreach Pro

- search runs: `20/day`
- packet generations: `100/month`
- people lookups: `150/month`
- outreach sends: `40/day`
- max new outreach threads per day: `20`
- same-contact cooldown: `30 days`

### Agent Suite

- search runs: `30/day`
- packet generations: `150/month`
- auto-apply attempts: `80/month`
- outreach sends: `40/day`
- max applications per run: `8`
- max concurrent browser runs: `2`

### Team

- pooled credits
- role-based limits
- org-level caps
- admin-defined tester overrides

## Credit Unit Suggestions

- 1 credit = one deep packet generation
- 1 credit = one people lookup set
- 2 credits = one supported auto-apply attempt
- 1 credit = one outreach send batch entry

## Safety Limits

- hard cap browser jobs per user
- cool down repeated outreach to the same contact
- no uncontrolled parallel applies
- no auto-apply on unsupported portals
- keep dry run available as a default-safe mode
- persist unanswered questions instead of forcing silent guesses
