# Instaply

Instaply is a new standalone product workspace for a private, agentic job-application platform.

This folder is intentionally separate from the older Revize workspace so it can evolve into a secure, sellable product without inheriting the old local-machine assumptions.

## Product Goal

Instaply should become:

- private and multi-tenant
- MCP-native for Claude/Desktop or ChatGPT-style clients
- cross-platform for Windows and macOS users
- backed by hosted open-weight model APIs
- capable of supported auto-apply on selected portals

## Target Architecture

- `apps/web`: customer-facing web app
- `apps/mcp`: MCP server surface for assistant clients
- `apps/api`: control plane and business API
- `apps/worker`: background jobs and browser automation workers
- `docs`: product, security, deployment, and monetization docs

## Chosen Defaults

- Product name: `Instaply`
- Primary model provider: `NVIDIA NIM`
- Fallback model provider: `Fireworks`
- Auth: `Supabase Auth` with Google sign-in + email/password
- Billing: `Stripe` with PayPal enabled where supported
- Web deploy: `Vercel`
- API / worker / MCP deploy: `Railway`
- Data + auth + storage: `Supabase`

## Current Build Status

This is the product skeleton stage. The folder includes:

- a polished cross-platform web shell
- onboarding and dashboard shells
- shared contracts for candidate preferences and agent stages
- a formal product architecture
- environment contracts
- deployment guidance
- auth/billing/tester strategy
- roadmap and packaging docs

## Included Product Docs

- [Architecture](./docs/ARCHITECTURE.md)
- [Application pipeline](./docs/APPLICATION_PIPELINE.md)
- [Profile and preferences](./docs/PROFILE_AND_PREFERENCES.md)
- [Run modes](./docs/RUN_MODES.md)
- [NIM + MCP integration](./docs/NIM_MCP_INTEGRATION.md)
- [Auth and billing](./docs/AUTH_BILLING.md)
- [Security](./docs/SECURITY.md)
- [Deployment](./docs/DEPLOYMENT.md)
- [Pricing](./docs/PRICING.md)
- [Go to market](./docs/GO_TO_MARKET.md)
- [Roadmap](./docs/ROADMAP.md)
- [Tester program](./docs/TESTER_PROGRAM.md)
- [Feature matrix](./docs/FEATURE_MATRIX.md)
- [Rate limits](./docs/RATE_LIMITS.md)
- [Outreach agent](./docs/OUTREACH_AGENT.md)
- [Dashboard structure](./docs/DASHBOARD_STRUCTURE.md)
- [Admin and operations](./docs/ADMIN_OPS.md)

## Next Build Stages

1. wire the web app to Supabase auth
2. implement shared API and worker contracts on top of `@instaply/contracts`
3. add MCP endpoints for search, packet generation, and apply planning
4. add supported auto-apply execution on selected portals

## Vercel Note

Because the web app will live on a Vercel-hosted website, NVIDIA NIM credentials must stay server-side only.

- safe: Vercel server env vars, API routes, MCP service, workers
- unsafe: `NEXT_PUBLIC_*` secrets or direct browser calls to NVIDIA NIM

Use the deployment doc for the exact environment variable list.
