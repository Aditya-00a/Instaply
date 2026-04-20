"use client";

/**
 * Credit-pack math helpers.
 *
 * NOTE on the file name: this file is named `paddle.ts` for historical
 * reasons — Paddle was the original payment processor and several
 * components import from `../lib/paddle`. The Paddle SDK loader and
 * `getPaddle()` / `isPaddleConfigured()` were removed on 2026-04-19
 * after Razorpay became the sole live processor (see
 * `api/app/razorpay_webhook.py` and `apps/web/app/billing/page.tsx`).
 *
 * What remains are two pure, processor-agnostic functions used by
 * `components/pricing-custom.tsx`:
 *
 *   - `bonusForAmount(usd)` — bonus tier table:
 *     +10% at $25, +15% at $50, +20% at $100, capped at +20%.
 *   - `totalCreditsForCustom(usd)` — applies the bonus and floors to
 *     an integer credit count.
 *
 * Both stay here so the pricing-custom component keeps a single
 * import path and we don't churn the file tree just for a rename.
 */

export function bonusForAmount(amount: number): { pct: number; label: string } {
  if (amount >= 100) return { pct: 0.20, label: "+20% bonus" };
  if (amount >= 50) return { pct: 0.15, label: "+15% bonus" };
  if (amount >= 25) return { pct: 0.10, label: "+10% bonus" };
  return { pct: 0, label: "" };
}

export function totalCreditsForCustom(amount: number): number {
  const bonus = bonusForAmount(amount);
  return Math.floor(amount * (1 + bonus.pct));
}
