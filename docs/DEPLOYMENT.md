# Deployment

## Recommended MVP Stack

### Web

- Vercel

Why:

- fast deploys
- good global connectivity
- simple for Next.js
- hobby plan is enough to start

### API + MCP + Workers

- Railway

Why:

- easy to deploy Python services
- cheap enough for MVP
- good DX for background services
- simpler than full Kubernetes while you are still validating the product

### Auth + Postgres + Storage

- Supabase

Why:

- Google sign-in + email/password
- managed Postgres
- object storage
- cheap/free enough for early stage

### Model Provider

- NVIDIA NIM primary
- Fireworks fallback

Why:

- hosted inference works better for lightweight laptops
- the MCP/API layer can remain model-provider agnostic
- the app can swap providers without changing the customer-facing product surface

## Suggested Service Split

- `instaply-web` on Vercel
- `instaply-api` on Railway
- `instaply-mcp` on Railway
- `instaply-worker` on Railway
- `supabase` managed
- `nvidia-nim` hosted API external dependency

## Vercel Environment Variables

If `instaply-web` is rendered inside a page on your main Vercel-hosted site, keep the NVIDIA key server-side only.

Use these environment variables in Vercel:

- `INSTAPLY_LLM_PROVIDER=nvidia_nim`
- `INSTAPLY_LLM_BASE_URL=https://integrate.api.nvidia.com/v1`
- `INSTAPLY_LLM_API_KEY=your_nvidia_nim_key`
- `INSTAPLY_LLM_MODEL=openai/gpt-oss-20b`
- `INSTAPLY_LLM_MODE=hosted`
- `INSTAPLY_LLM_FALLBACK_PROVIDER=fireworks`
- `INSTAPLY_LLM_FALLBACK_BASE_URL=https://api.fireworks.ai/inference/v1`
- `INSTAPLY_LLM_FALLBACK_API_KEY=your_fireworks_key`
- `INSTAPLY_LLM_FALLBACK_MODEL=accounts/fireworks/models/deepseek-v3p1`

Security rule:

- browser page -> your server route / API / MCP
- server route / API / MCP -> NVIDIA NIM

Do not:

- expose `INSTAPLY_LLM_API_KEY` through any `NEXT_PUBLIC_*` variable
- call NVIDIA NIM directly from browser code

## Production Direction Later

When the product hardens:

- move workers to isolated containers
- move long-running apply execution to queue-based jobs
- add better observability
- add signed audit logs for critical actions
- add provider failover and cost-based routing between NIM and fallback providers
