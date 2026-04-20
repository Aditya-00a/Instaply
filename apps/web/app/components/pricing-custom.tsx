"use client";

import Link from "next/link";
import { useState } from "react";
import { bonusForAmount, totalCreditsForCustom } from "../lib/paddle";

/**
 * Custom top-up calculator.
 *
 * Rule: $1 = 1 credit at the standard rate, minimum $10.
 * Bonuses: +10% at $25, +15% at $50, +20% at $100. Capped at +20%.
 *
 * Payment is handled on /billing via Razorpay (see
 * apps/web/app/billing/page.tsx). This component only renders the
 * pricing preview and routes — public pages link to /sign-in, and the
 * signed-in /billing page passes `inApp` to swap the CTA to a direct
 * "Open billing" button that scrolls the user to their pack choices.
 */
const MIN = 10;
const STEP = 5;

type Props = {
  /** When true, sends the user to /billing to check out via Razorpay. */
  inApp?: boolean;
};

export function PricingCustom({ inApp = false }: Props) {
  const [amount, setAmount] = useState<number>(15);

  const clamped = Math.max(MIN, Math.floor(amount || 0));
  const bonus = bonusForAmount(clamped);
  const totalCredits = totalCreditsForCustom(clamped);
  const baseCredits = clamped;
  const bonusCredits = totalCredits - baseCredits;
  const perApp = clamped / totalCredits;

  const handleCheckout = () => {
    // Razorpay checkout lives on /billing — route there with the
    // chosen amount hinted in the query string. Billing page picks
    // up ?amount=N and pre-selects the matching pack.
    if (typeof window !== "undefined") {
      window.location.href = `/billing?amount=${clamped}`;
    }
  };

  return (
    <section className="pricing-custom">
      <div className="pricing-custom-head">
        <div className="pricing-card-label">Custom</div>
        <p className="pricing-custom-sub">
          Pick any amount. Bonuses unlock at $25, $50, and $100. Min $10.
        </p>
      </div>

      <div className="pricing-custom-body">
        <div className="pricing-custom-input-row">
          <span className="pricing-custom-currency">$</span>
          <input
            type="number"
            min={MIN}
            step={STEP}
            value={amount}
            onChange={(e) => {
              const v = Number(e.target.value);
              setAmount(Number.isFinite(v) ? v : MIN);
            }}
            className="pricing-custom-input"
            aria-label="Custom top-up amount in USD"
          />
          <span className="pricing-custom-unit">USD</span>
        </div>

        <div className="pricing-custom-result">
          <strong>{totalCredits}</strong>
          <span>
            {totalCredits === 1 ? "application" : "applications"}
            {bonusCredits > 0 ? ` · ${baseCredits} base + ${bonusCredits} bonus` : ""}
            {" · "}
            ${perApp.toFixed(2)} per application
          </span>
        </div>

        {bonus.pct > 0 && (
          <div className="pricing-custom-bonus-pill">🎉 {bonus.label} unlocked</div>
        )}

        {inApp ? (
          <button
            type="button"
            className="pricing-card-cta"
            onClick={handleCheckout}
          >
            {`Buy ${totalCredits} credits — $${clamped}`}
          </button>
        ) : (
          <Link href="/sign-in" className="pricing-card-cta">
            Sign up to buy
          </Link>
        )}
      </div>

      {amount < MIN && (
        <div className="pricing-custom-note">
          Minimum top-up is ${MIN}. Rounded up.
        </div>
      )}
    </section>
  );
}
