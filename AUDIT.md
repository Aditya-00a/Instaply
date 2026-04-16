# Instaply launch audit

Last updated: 2026-04-15
Branch: main
Latest commit at audit: `8a4f152` (closed-beta invite codes)

This is an honest assessment of where the product stands, written
after one focused build session. Sections are ordered by what would
block a launch / paid customer, not by what was hardest to build.

---

## 1. What's shipping today

### 1.1 Public marketing surface — DONE

- Landing `/` with hero, live-feel queue card, portal strip, stat
  band, testimonials, trust band, final CTA
- `/about`, `/how-it-works` (with visual workflow diagram), `/pricing`
  (with bonus tiers + custom calculator), `/integrations`, `/security`,
  `/status`, `/changelog`, `/careers`, `/contact` (real form)
- Legal pages `/terms`, `/privacy`, `/refund` — scrubbed of personal
  info, single contact: hello@asion.ai
- Custom 404, sitemap, robots.txt, dynamic OG image
- Cookie banner with localStorage persistence
- Sticky blurred header, brand dot mark, hover-lift cards
- Pulsing accent dots, gradient stat band, blue-header tables on legal

### 1.2 Auth — DONE

- Email + password signup with required ToS/Privacy/Refund acceptance
  (legal_accepted_at + version recorded on profile row)
- Sign-in with optional 2FA (TOTP, Supabase MFA)
- Forgot password → reset password flow
- Google OAuth + email magic link (require enabling Google provider in
  Supabase dashboard)
- /auth/callback handles OAuth + email confirmation
- Real sign-out (calls supabase.auth.signOut)
- Middleware protects /dashboard, /applications, /review, /documents,
  /onboarding, /billing, /settings; redirects unsigned to
  /sign-in?next=<path>; bounces signed-in away from /sign-in
- Demo-mode fallback when env vars missing — local dev never breaks

### 1.3 Signed-in surface — DONE

- `/dashboard` — empty-state hero for new users with credit balance,
  live data when applications exist
- `/onboarding` — 3-step wizard (resume upload → confirm basics →
  target roles + locations) with ATS scoring on PDF resumes
- `/billing` — credit balance + ledger history + pack cards + custom
  top-up, all wired to Paddle.js checkout
- `/applications` — real applications table with status pills, filter
  bar, fit score, external open links
- `/documents` — uploaded resumes + cover letters with signed-URL
  download
- `/settings` — 2FA enrollment + management, MCP token CRUD
- `/review` — saved screening answers with empty state

### 1.4 Closed-beta infrastructure — DONE

- `invite_codes` table + `redeem_invite_code` RPC
- Atomic redemption with idempotency + race protection
- Configurable credit grant per code (default 1000)
- `mint_invite_codes` SQL helper for batch generation
- Frontend gates signup behind code when
  `NEXT_PUBLIC_INVITE_REQUIRED=true`

### 1.5 Security — DONE

- HSTS preload (2yr), X-Frame-Options, X-Content-Type-Options
- Referrer-Policy: strict-origin-when-cross-origin
- Permissions-Policy: deny camera/mic/geo
- Content-Security-Policy scoped to first-party + Supabase + Paddle +
  fonts
- Row-level security on every Supabase table; storage policies enforce
  per-uid folder isolation
- Salted IP hash on legal acceptance; no raw IP storage
- Append-only credit ledger
- 2FA available account-wide

### 1.6 Payments — CODE COMPLETE, PADDLE PENDING

- Paddle.js loaded lazily from CDN
- Pack Buy buttons + custom calculator wired
- Bonus tiers (10% / 15% / 20%) computed client-side, will be
  re-computed server-side in webhook
- /billing/success page handles Paddle redirect
- BLOCKED on Paddle merchant verification (1-3 days, your end)
- BLOCKED on webhook backend deploy (Fly.io, your end)

---

## 2. Outstanding gaps (in priority order)

### Priority 1 — required to take real money

1. **Paddle live verification.** Sandbox works; production requires
   their KYC review. Status: pending.
2. **Webhook backend deployed.** Without it, payments succeed but
   credits don't grant. Code lives in `C:\Ravendise\Instaply\api\`,
   needs `fly deploy`.
3. **Webhook signature verification.** Already in `paddle.py`; just
   needs `PADDLE_WEBHOOK_SECRET` set in Fly secrets.

### Priority 2 — required to verify confirmation-pricing model

4. **Gmail OAuth integration.** The pay-per-confirmation model
   requires reading the user's inbox for ATS confirmation emails.
   Without it, every submission stays in "submitted" state and never
   advances to "confirmed", so credits never get consumed.

### Priority 3 — quality of life pre-public-launch

5. **Transactional email.** No welcome email, no receipt, no
   confirmation-of-confirmation. Recommend Resend ($0 to start, scales
   cleanly). ~30 min to wire on /sign-in success and webhook handler.
6. **Real /status feed.** Currently static. Wire to UptimeRobot or a
   /health aggregator on the API.
7. **First-time user product tour.** Even one inline coachmark on the
   dashboard pointing at the empty-state CTA would help conversion.

### Priority 4 — nice to have

8. **Skeleton loaders** instead of plain "Loading…" text. Higher
   perceived performance.
9. **Dark mode.** All tokens are CSS variables already, ~1hr lift.
10. **Loom demo video** embedded on `/how-it-works`. Single highest-
    impact conversion asset for SaaS at this stage.
11. **Analytics.** Plausible or Vercel Analytics. Need to measure
    landing → signup → first-purchase conversion.
12. **Failed-payment retry copy.** If Paddle returns an error, current
    UX is generic "Something went wrong." Improve.
13. **Reset password expired link** state.
14. **Better mobile signup form** — works but tight at < 380px width.

---

## 3. Known weaknesses worth being honest about

### 3.1 ATS scoring is heuristic

The ATS score on resume upload is a 10-check rule-based scorer running
client-side. It's directionally correct (catches the obvious things:
no contact info, no quantified impact, image-only PDFs) but not as
sharp as a real LLM-based ATS evaluation. Good enough for v1; should
be replaced with a server-side LLM call before charging users for
"resume optimization" as a separate product.

### 3.2 Bonus tiers are client-side advertised, not yet server-enforced

The pricing-custom calculator shows "+15% bonus at $50" etc. The
webhook handler that translates a Paddle payment into credits *also*
needs to apply that bonus math. Code is documented in `lib/paddle.ts`
(`bonusForAmount`) but the API webhook hasn't been updated to call it
yet. Right now if someone paid $100 via custom, the webhook would grant
100 credits not 120. **Fix before shipping the API.**

### 3.3 Cover letter parsing isn't done

Resumes get text-extracted and ATS-scored. Cover letters get uploaded
and stored, but no parsing or scoring runs. Acceptable for v1 — cover
letters are AI-generated per-application anyway.

### 3.4 No per-organization seat / team support

Single-user accounts only. If a recruiter wanted to use Instaply on
behalf of multiple candidates, they'd need separate accounts. Out of
scope for v1.

### 3.5 No undo for any destructive action

MCP token revocation, resume delete, account delete (when added) are
all final. Most tools at this stage do the same; flagging because
support tickets often start with "I deleted X by accident."

---

## 4. Performance baseline

- Initial JS bundle for landing: well under 200KB (Next 16 turbopack
  build)
- Largest dynamic chunk: pdfjs-dist (only loaded after a resume drop)
- All public pages prerender as static (`○`)
- Middleware adds ~30ms per request (Supabase getUser)

No performance fires. Page weights are reasonable for a marketing +
console hybrid.

---

## 5. Compliance posture

- **DPDP Act (India)**: privacy policy lists controller, sub-processors,
  legal basis, retention, user rights, grievance contact (email only —
  consider whether DPDP requires a physical address you're willing to
  publish)
- **GDPR**: same coverage; cookie banner asks for consent
- **CCPA / Paddle MoR**: Paddle handles consumer privacy disclosures
  for paying US customers
- **PCI-DSS**: Paddle is PCI Level 1; we never see card numbers
- **Storage at rest encryption**: Supabase AES-256
- **Transit encryption**: TLS 1.3 (Vercel + Supabase enforced)

---

## 6. Operational readiness

- Vercel auto-deploys on every push to main
- Supabase has all migrations applied (0001-0010)
- Logging: Vercel function logs + Supabase activity log; nothing
  centralized yet (not blocking for v1)
- Error tracking: none. Recommend Sentry once real users land.
- Backup strategy: Supabase Pro plan includes daily PITR backups for 7
  days. Sufficient for v1.
- Status page: static; upgrade to live feed once API deploys

---

## 7. Recommended pre-launch checklist

In the order you'd actually do them:

1. ☐ Wait for Paddle merchant verification
2. ☐ Deploy API to Fly.io (`cd Instaply/api && fly deploy`)
3. ☐ Set `PADDLE_API_KEY` + `PADDLE_WEBHOOK_SECRET` in Fly secrets
4. ☐ Configure Paddle webhook → `https://instaply-api.fly.dev/billing/paddle/webhook`
5. ☐ Update webhook handler to apply bonus tiers (see weakness 3.2)
6. ☐ Wire Gmail OAuth for confirmation verification
7. ☐ Wire Resend for transactional email
8. ☐ Mint 20-50 beta invite codes, share with first cohort
9. ☐ Set `NEXT_PUBLIC_INVITE_REQUIRED=true` in Vercel + redeploy
10. ☐ Test end-to-end as a real beta user (signup → onboarding →
    submit application → wait for confirmation → see credit consumed)
11. ☐ Open public when first 3 testers complete the flow successfully

---

## 8. Verdict

The web product is shippable to a closed beta tonight. The
money-taking flow is gated only by Paddle's verification and the
webhook backend deploy — both manual steps that take hours, not days.

The product surface is consistent, the auth is real, the data is real,
the security baseline is reasonable for a v1 SaaS. The largest
remaining product risk is Gmail OAuth + confirmation polling — that's
the mechanism that justifies the entire pay-per-confirmation pricing
model.

**Recommendation:** ship the closed beta with invite codes + 1000 free
credits per tester. Use feedback to harden the auto-apply pipeline
before opening payments to anyone outside the cohort.
