# ─── Instaply web dashboard — Next.js 14 standalone ──────────────
# NEXT_PUBLIC_* vars must be present at build time (inlined by Next.js).
# Pass them as build args from fly.toml [build.args].
# This Dockerfile is meant to be built from the web/ directory as context.

FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Build-time public env vars — declared as ARGs so `next build` can inline them
ARG NEXT_PUBLIC_SUPABASE_URL
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY
ARG NEXT_PUBLIC_API_BASE=https://api.asion.ai
ARG NEXT_PUBLIC_PADDLE_ENV=production
ARG NEXT_PUBLIC_PADDLE_CLIENT_TOKEN
ARG NEXT_PUBLIC_PADDLE_PRICE_STARTER
ARG NEXT_PUBLIC_PADDLE_PRICE_PLUS
ARG NEXT_PUBLIC_PADDLE_PRICE_PRO

ENV NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL \
    NEXT_PUBLIC_SUPABASE_ANON_KEY=$NEXT_PUBLIC_SUPABASE_ANON_KEY \
    NEXT_PUBLIC_API_BASE=$NEXT_PUBLIC_API_BASE \
    NEXT_PUBLIC_PADDLE_ENV=$NEXT_PUBLIC_PADDLE_ENV \
    NEXT_PUBLIC_PADDLE_CLIENT_TOKEN=$NEXT_PUBLIC_PADDLE_CLIENT_TOKEN \
    NEXT_PUBLIC_PADDLE_PRICE_STARTER=$NEXT_PUBLIC_PADDLE_PRICE_STARTER \
    NEXT_PUBLIC_PADDLE_PRICE_PLUS=$NEXT_PUBLIC_PADDLE_PRICE_PLUS \
    NEXT_PUBLIC_PADDLE_PRICE_PRO=$NEXT_PUBLIC_PADDLE_PRICE_PRO

RUN npm run build

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production PORT=3000
RUN addgroup -S nodejs && adduser -S next -G nodejs
COPY --from=builder /app/public ./public
COPY --from=builder --chown=next:nodejs /app/.next/standalone ./
COPY --from=builder --chown=next:nodejs /app/.next/static ./.next/static
USER next
EXPOSE 3000
CMD ["node", "server.js"]
