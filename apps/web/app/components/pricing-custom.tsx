"use client";

import Link from "next/link";
import { useState } from "react";
import { bonusForAmount, getPaddle, isPaddleConfigured, totalCreditsForCustom } from "../lib/paddle";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

/**
 * Custom top-up calculator.
 *
 * Rule: $1 = 1 credit at the standard rate, minimum $10.
 * Bonuses: +10% at $25, +15% at $50, +20% at $100. Capped at +20%.
 *
 * On the public /pricing page we link to /sign-in. On the signed-in
 * /billing page we open the Paddle overlay directly.
 */
const MIN = 10;
const STEP = 5;

type Props = {
  /** When true, opens Paddle Checkout instead of routing to /sign-in. */
  inApp?: boolean;
};

export function PricingCustom({ inApp = false }: Props) {
  const [amount, setAmount] = useState<number>(15);
  const [busy, setBusy] = useState(false);

  const clamped = Math.max(MIN, Math.floor(amount || 0));
  const bonus = bonusForAmount(clamped);
  const totalCredits = totalCreditsForCustom(clamped);
  const baseCredits = clamped;
  const bonusCredits = totalCredits - baseCredits;
  const perApp = clamped / totalCredits;

  const customPriceId = process.env.NEXT_PUBLIC_PADDLE_PRICE_CREDIT;

  const handleCheckout = async () => {
    if (!isPaddleConfigured() || !customPriceId) {
      alert("Checkout isn't fully configured yet. Email hello@asion.ai.");
      return;
    }
    setBusy(true);
    try {
      const paddle = await getPaddle();
      if (!paddle) {
        alert("Could not load Paddle. Try again in a moment.");
        return;
      }

      let customerEmail: string | undefined;
      let customerId: string | undefined;
      if (isSupabaseConfigured()) {
        const supabase = getBrowserSupabase();
        if (supabase) {
          const {
            data: { user },
          } = await supabase.auth.getUser();
          customerEmail = user?.email ?? undefined;
          customerId = user?.id;
        }
      }

      paddle.Checkout.open({
        items: [{ priceId: customPriceId, quantity: clamped }],
        customer: customerEmail ? { email: customerEmail } : undefined,
        customData: customerId
          ? { user_id: customerId, pack: "custom", base_credits: clamped }
          : { pack: "custom", base_credits: clamped },
        settings: {
          displayMode: "overlay",
          theme: "light",
          successUrl:
            typeof window !== "undefined"
              ? `${window.location.origin}/billing/success`
              : undefined,
        },
      });
    } finally {
      setBusy(false);
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
            disabled={busy}
          >
            {busy ? "Opening checkout…" : `Buy ${totalCredits} credits — $${clamped}`}
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
