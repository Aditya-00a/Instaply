"use client";

import Link from "next/link";
import { CheckCircle2, Loader2 } from "lucide-react";
import { useEffect } from "react";

import { ConsoleShell } from "../../components/console-shell";

/**
 * Razorpay Checkout success redirect lands here. Razorpay has already
 * processed the payment; the credit grant happens server-side via the
 * Razorpay webhook (see api/app/razorpay_webhook.py). This page is
 * purely the user-facing confirmation while the webhook completes.
 *
 * The legacy Paddle path that used to terminate here has been removed
 * (2026-04-19). Old Paddle success URLs continue to work because the
 * route just redirects back to /billing after 6 seconds regardless.
 */
export default function BillingSuccessPage() {
  useEffect(() => {
    const t = setTimeout(() => {
      window.location.href = "/billing";
    }, 6000);
    return () => clearTimeout(t);
  }, []);

  return (
    <ConsoleShell
      activePath="/billing"
      eyebrow="Billing"
      title="Payment received"
      description=""
    >
      <section className="console-section">
        <article className="glass dashboard-empty-hero">
          <div className="dashboard-empty-icon" aria-hidden>
            <CheckCircle2 size={26} />
          </div>
          <div className="dashboard-empty-copy">
            <span className="eyebrow">Thanks!</span>
            <h2>Your payment went through.</h2>
            <p>
              Credits typically land within 30 seconds. If your balance
              hasn&apos;t updated in a minute, refresh this page or email{" "}
              <a href="mailto:hello@asion.ai" className="link-accent">
                hello@asion.ai
              </a>
              .
            </p>
            <p style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--muted)", marginTop: 8 }}>
              <Loader2 size={14} className="spin" />
              Auto-redirecting to billing…
            </p>
          </div>
          <div className="dashboard-empty-actions">
            <Link href="/billing" className="btn-primary">
              Go to billing now
            </Link>
            <Link href="/dashboard" className="btn-secondary">
              Back to dashboard
            </Link>
          </div>
        </article>
      </section>
    </ConsoleShell>
  );
}
