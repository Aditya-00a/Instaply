"use client";

import { Coins, CreditCard, Wallet } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { ConsoleShell } from "../components/console-shell";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

type Pack = {
  id: string;
  label: string;
  usd: number;
  credits: number;
  bonus: number;
  per: number;
  featured?: boolean;
};

const PACKS: Pack[] = [
  { id: "starter", label: "Starter", usd: 10, credits: 10, bonus: 0, per: 1.0 },
  { id: "plus", label: "Plus", usd: 25, credits: 30, bonus: 17, per: 0.83, featured: true },
  { id: "pro", label: "Pro", usd: 50, credits: 70, bonus: 40, per: 0.71 },
];

type LedgerRow = {
  id: string;
  delta: number;
  reason: string;
  note: string | null;
  created_at: string;
};

type State =
  | { kind: "demo" }
  | { kind: "loading" }
  | { kind: "live"; balance: number; ledger: LedgerRow[] }
  | { kind: "error"; message: string };

const DEMO_LEDGER: LedgerRow[] = [
  { id: "1", delta: 3, reason: "signup_bonus", note: "Welcome bonus", created_at: new Date().toISOString() },
];

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function humanReason(reason: string): string {
  const map: Record<string, string> = {
    signup_bonus: "Signup bonus",
    topup: "Top-up",
    paddle_topup: "Top-up (Paddle)",
    application_confirmed: "Confirmed application",
    refund: "Refund",
    adjustment: "Admin adjustment",
  };
  return map[reason] || reason.replaceAll("_", " ");
}

export default function BillingPage() {
  const [state, setState] = useState<State>(
    isSupabaseConfigured() ? { kind: "loading" } : { kind: "demo" }
  );
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    if (!isSupabaseConfigured()) return;
    let cancelled = false;

    (async () => {
      const supabase = getBrowserSupabase();
      if (!supabase) {
        if (!cancelled) setState({ kind: "demo" });
        return;
      }

      try {
        const {
          data: { user },
        } = await supabase.auth.getUser();
        if (!user) {
          if (!cancelled) setState({ kind: "demo" });
          return;
        }

        const [{ data: balData }, { data: ledgerData, error: ledgerErr }] =
          await Promise.all([
            supabase.rpc("get_credit_balance", { p_user_id: user.id }),
            supabase
              .from("credit_ledger")
              .select("id, delta, reason, note, created_at")
              .order("created_at", { ascending: false })
              .limit(20),
          ]);

        if (ledgerErr) throw ledgerErr;

        if (!cancelled)
          setState({
            kind: "live",
            balance: typeof balData === "number" ? balData : 0,
            ledger: (ledgerData ?? []) as LedgerRow[],
          });
      } catch (e) {
        if (!cancelled)
          setState({
            kind: "error",
            message: e instanceof Error ? e.message : "Unknown error",
          });
      }
    })();

    return () => {
      cancelled = true;
    };
  }, []);

  const handleCheckout = (packId: string) => {
    // Paddle.js integration lands once the price IDs are in place.
    // For now, surface a deterministic "coming soon" toast so the
    // UI flow is complete and reviewable.
    setToast(
      `Checkout for "${packId}" will open in Paddle once billing is live. Contact hello@asion.ai if you'd like early access.`
    );
    setTimeout(() => setToast(null), 4800);
  };

  const balance =
    state.kind === "live" ? state.balance : state.kind === "demo" ? 3 : null;
  const ledger =
    state.kind === "live"
      ? state.ledger
      : state.kind === "demo"
      ? DEMO_LEDGER
      : [];

  return (
    <ConsoleShell
      activePath="/billing"
      eyebrow="Billing"
      title="Credits & billing"
      description="Pay only for applications that land. Credits never expire while your account is active."
      actions={[
        { href: "/pricing", label: "Public pricing", variant: "secondary" },
      ]}
    >
      {toast && <div className="billing-toast">{toast}</div>}

      {state.kind === "error" && (
        <section className="console-section">
          <div className="dashboard-error">
            Couldn&apos;t load billing — {state.message}
          </div>
        </section>
      )}

      <section className="console-section">
        <div className="billing-summary-grid">
          <article className="billing-summary-card billing-summary-accent">
            <div className="billing-summary-ico">
              <Coins size={20} />
            </div>
            <div className="billing-summary-body">
              <span>Current balance</span>
              <strong>
                {state.kind === "loading" ? "…" : balance} <em>credits</em>
              </strong>
              <p>1 credit = 1 confirmed application</p>
            </div>
          </article>

          <article className="billing-summary-card">
            <div className="billing-summary-ico">
              <Wallet size={20} />
            </div>
            <div className="billing-summary-body">
              <span>Lifetime purchased</span>
              <strong>
                {ledger
                  .filter((l) => l.reason === "topup" || l.reason === "paddle_topup")
                  .reduce((s, l) => s + Math.max(l.delta, 0), 0)}{" "}
                <em>credits</em>
              </strong>
              <p>From top-up packs</p>
            </div>
          </article>

          <article className="billing-summary-card">
            <div className="billing-summary-ico">
              <CreditCard size={20} />
            </div>
            <div className="billing-summary-body">
              <span>Confirmed applications</span>
              <strong>
                {
                  ledger.filter((l) => l.reason === "application_confirmed")
                    .length
                }{" "}
                <em>total</em>
              </strong>
              <p>1 credit each, only after confirmation</p>
            </div>
          </article>
        </div>
      </section>

      <section className="console-section">
        <div className="section-intro">
          <div>
            <p className="eyebrow">Top up</p>
            <h2>Pick a pack</h2>
          </div>
          <Link className="btn-secondary" href="/pricing">
            Compare packs
          </Link>
        </div>

        <div className="billing-pack-grid">
          {PACKS.map((p) => (
            <div
              key={p.id}
              className={`billing-pack-card${p.featured ? " billing-pack-card-featured" : ""}`}
            >
              {p.featured && <div className="pack-card-tag">Most popular</div>}
              <div className="pack-card-label">{p.label}</div>
              <div className="pack-card-price">
                <strong>${p.usd}</strong>
                <span>USD, one-time</span>
              </div>
              <div className="pack-card-credits">{p.credits} applications</div>
              <div className="pack-card-per">
                ${p.per.toFixed(2)} effective per application
              </div>
              {p.bonus > 0 && (
                <div className="pack-card-bonus">+{p.bonus}% bonus</div>
              )}
              <button
                type="button"
                onClick={() => handleCheckout(p.id)}
                className={p.featured ? "btn-primary" : "btn-secondary"}
              >
                Buy now
              </button>
            </div>
          ))}
        </div>
      </section>

      <section className="console-section">
        <article className="glass workspace-table-card">
          <div className="console-card-header">
            <div>
              <div className="panel-kicker">Activity</div>
              <h3>Credit history</h3>
            </div>
          </div>

          <div className="billing-ledger">
            {state.kind === "loading" ? (
              <div className="workspace-empty">Loading your history…</div>
            ) : ledger.length === 0 ? (
              <div className="workspace-empty">
                No credit activity yet. Your signup bonus lands the first
                time you sign in.
              </div>
            ) : (
              <div className="billing-ledger-list">
                {ledger.map((l) => (
                  <div className="billing-ledger-row" key={l.id}>
                    <div>
                      <strong>{humanReason(l.reason)}</strong>
                      <p>{l.note || "—"}</p>
                    </div>
                    <div className="billing-ledger-right">
                      <span
                        className={
                          l.delta >= 0
                            ? "billing-ledger-delta billing-ledger-delta-pos"
                            : "billing-ledger-delta billing-ledger-delta-neg"
                        }
                      >
                        {l.delta >= 0 ? "+" : ""}
                        {l.delta}
                      </span>
                      <span className="billing-ledger-date">{fmtDate(l.created_at)}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </article>
      </section>
    </ConsoleShell>
  );
}
