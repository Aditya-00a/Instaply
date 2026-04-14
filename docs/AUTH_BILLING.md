# Auth and Billing

## Auth Choice

Use Supabase Auth first.

Why:

- Google sign-in is straightforward
- email/password is supported
- email-based account creation is supported
- cheap/free enough for MVP
- integrates naturally with Postgres and storage

## Billing Choice

Use Stripe first.

Why:

- easiest subscription flow for MVP
- standard tooling
- supports adding PayPal as a payment method in supported regions
- easier to scale than building custom payment handling

## Product Plan Rules

- allow free starter application credits
- allow internal tester accounts
- allow feature flags by account

## Suggested Entitlements

- `free_application_credits`
- `free_packet_credits`
- `plan_name`
- `auto_apply_enabled`
- `portal_access`
- `tester_mode`

## Recommended MVP Account Types

- `starter`
- `pro`
- `agentic_apply`
- `internal_tester`
- `admin`

