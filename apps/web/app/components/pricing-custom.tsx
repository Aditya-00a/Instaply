"use client";

import Link from "next/link";
import { useState } from "react";

/**
 * Custom top-up calculator.
 *
 * Rule: $1 = 1 credit at the standard rate, minimum $10.
 * The three preset packs are bulk discounts — the custom option is the
 * straight rate so it never undercuts a pack.
 */
const MIN = 10;
const STEP = 5;

export function PricingCustom() {
  const [amount, setAmount] = useState<number>(15);

  const clamped = Math.max(MIN, Math.floor(amount || 0));
  const credits = clamped;
  const perApp = 1.0;

  return (
    <section className="pricing-custom">
      <div className="pricing-custom-head">
        <div className="pricing-card-label">Custom</div>
        <p className="pricing-custom-sub">
          Pick any amount. $1 = 1 application. Minimum $10.
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
          <strong>{credits}</strong>
          <span>
            {credits === 1 ? "application" : "applications"} ·{" "}
            ${perApp.toFixed(2)} per application
          </span>
        </div>

        <Link href="/sign-in" className="pricing-card-cta">
          Sign up to buy
        </Link>
      </div>

      {amount < MIN && (
        <div className="pricing-custom-note">
          Minimum top-up is ${MIN}. Rounded up.
        </div>
      )}
    </section>
  );
}
