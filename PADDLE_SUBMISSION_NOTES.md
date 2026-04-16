# Paddle Merchant-of-Record Submission — Instaply

_Prepared 2026-04-15 night. Site is live, all required pages present and CCPA-patched._

## URLs to give Paddle

| Field | Value |
|---|---|
| Website / homepage | https://instaply.asion.ai/ |
| Pricing page | https://instaply.asion.ai/pricing |
| Terms of Service | https://instaply.asion.ai/terms |
| Privacy Policy | https://instaply.asion.ai/privacy |
| Refund Policy | https://instaply.asion.ai/refund |
| Support / contact email | hello@asion.ai |

## Business details (have these ready for the form)

- **Legal entity:** Ravendise (proprietorship, registered in India)
- **Business address:** Pune, Maharashtra, India *(use full registered address from your Udyam/GST docs — don't paste here, keep private)*
- **Tax ID:** GSTIN / Udyam number from your business records
- **Bank for payouts:** Indian business account in Ravendise's name
- **Product type:** Digital service / SaaS (job-application automation)
- **Business model:** Prepaid credit packs, no subscriptions
- **Pricing:** $1 USD per confirmed application, packs from $10–$50 + custom top-ups
- **Currency:** USD (Paddle handles FX to INR for payout)

## Cover note for Paddle's reviewer (paste into the "tell us about your business" field)

> Instaply is a digital service that automates job applications on major ATS platforms (Workday, Greenhouse, Lever, SmartRecruiters) on behalf of its users. We charge $1 USD per *confirmed* application — a credit is only consumed when an employer confirmation email is received. We sell prepaid credit packs ($10/$25/$50) and custom top-ups; there are no subscriptions or recurring charges.
>
> The legal entity is Ravendise, an Indian proprietorship. Paddle will be named as merchant of record in our Terms (already published). All credit-card data is processed by Paddle — we never store card numbers. We comply with India's DPDP Act 2023, GDPR (where applicable), and CCPA/CPRA for California residents (privacy policy section 7.1). We do not sell or share personal data.
>
> Refunds: full refund within 14 days if the user has consumed 5 or fewer credits; pro-rata thereafter at our discretion. Service-failure protection: credits are automatically returned if an application doesn't reach "confirmed" status. Full refund policy at https://instaply.asion.ai/refund.
>
> Primary contact: hello@asion.ai. Privacy contact: privacy@asion.ai.

## Pre-submission checklist (last sanity pass)

- [x] Pricing page renders cleanly with all tiers and per-unit cost ($1)
- [x] Terms names Paddle as merchant of record
- [x] Privacy policy lists Paddle as a sub-processor
- [x] Refund policy with explicit timeframes and request process
- [x] Contact email present on every legal page
- [x] CCPA / California section present (section 7.1, just patched)
- [x] DPDP + GDPR coverage
- [x] Liability cap stated (greater of 12-month payments or USD 120)
- [x] Prohibited use clauses (no fraud, no scraping, no impersonation, no ATS abuse)
- [x] DNS resolved, Vercel build green, all pages return 200
- [ ] **Push the CCPA patch to GitHub + redeploy on Vercel before submitting** ← do this first
- [ ] Have your GSTIN/Udyam + business bank details handy
- [ ] Submit at https://vendors.paddle.com/

## Things Paddle reviewers commonly flag (you're clean on all of these)

- ✅ Clear unit pricing — yes ($1/app)
- ✅ No misleading "free" claims — yes (3 free credits clearly bounded)
- ✅ Cancellation/refund mechanism — yes
- ✅ Working contact channel — yes
- ✅ AI-content disclosure — terms include this
- ✅ No prohibited verticals (gambling, adult, regulated finance) — clean
- ⚠️ AI-tool category increasingly scrutinized — your "human-in-the-loop only confirms after employer reply" framing protects you here. Lean on it if asked.

## After approval (set yourself a reminder)

- Add Paddle pay link / checkout to /pricing CTAs
- Wire webhooks: `transaction.completed` → credit ledger top-up
- Test sandbox transaction end-to-end before going live
- Add invoice download / billing portal link to user account page
