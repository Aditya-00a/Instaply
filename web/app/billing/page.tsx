"use client";
import { useEffect, useState } from "react";
import Script from "next/script";
import { supabase } from "@/lib/supabase";
import { apiGet } from "@/lib/api";

type Pack = { id: string; label: string; price_usd: number; credits: number; bonus_pct: number };
type Credits = { balance: number; plan: string; used?: number };

// Paddle product → price IDs are set at build time (env vars).
const PRICE_ID: Record<string, string | undefined> = {
  starter: process.env.NEXT_PUBLIC_PADDLE_PRICE_STARTER,
  plus:    process.env.NEXT_PUBLIC_PADDLE_PRICE_PLUS,
  pro:     process.env.NEXT_PUBLIC_PADDLE_PRICE_PRO,
};

declare global {
  interface Window {
    Paddle?: any;
  }
}

export default function BillingPage() {
  const [packs, setPacks] = useState<Pack[] | null>(null);
  const [credits, setCredits] = useState<Credits | null>(null);
  const [userId, setUserId] = useState<string | null>(null);
  const [email, setEmail] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      const { data: { user } } = await supabase().auth.getUser();
      if (!user) { window.location.href = "/signup"; return; }
      setUserId(user.id);
      setEmail(user.email || null);
      try {
        const [p, c] = await Promise.all([
          apiGet<{ packs: Pack[] }>("/billing/packs"),
          apiGet<Credits>("/credits"),
        ]);
        setPacks(p.packs);
        setCredits(c);
      } catch (e: any) { setErr(String(e)); }
    })();
  }, []);

  function initPaddle() {
    if (!window.Paddle) return;
    const env = process.env.NEXT_PUBLIC_PADDLE_ENV;
    if (env && env !== "production") window.Paddle.Environment.set(env);
    window.Paddle.Initialize({
      token: process.env.NEXT_PUBLIC_PADDLE_CLIENT_TOKEN,
    });
    setReady(true);
  }

  function buy(pack: Pack) {
    const priceId = PRICE_ID[pack.id];
    if (!priceId) { alert("Price not configured yet — set NEXT_PUBLIC_PADDLE_PRICE_* in env."); return; }
    if (!ready || !window.Paddle || !userId) return;
    window.Paddle.Checkout.open({
      items: [{ priceId, quantity: 1 }],
      customer: email ? { email } : undefined,
      // custom_data is what the webhook uses to credit the right user + pack.
      customData: { user_id: userId, pack_id: pack.id },
      settings: { theme: "dark", displayMode: "overlay" },
    });
  }

  return (
    <div>
      <Script src="https://cdn.paddle.com/paddle/v2/paddle.js" onLoad={initPaddle} />
      <h1 className="text-3xl font-semibold">Billing</h1>

      <div className="mt-6 rounded-lg border border-white/10 p-5 flex items-baseline justify-between">
        <div>
          <div className="text-sm text-white/60">Current balance</div>
          <div className="mt-1 text-4xl font-semibold">
            {credits?.balance ?? "—"} <span className="text-base text-white/60">credits</span>
          </div>
        </div>
        <div className="text-sm text-white/60">
          Plan: <span className="text-white">{credits?.plan || "free"}</span>
        </div>
      </div>

      {err && <div className="mt-4 text-red-400 text-sm">{err}</div>}

      <h2 className="mt-10 text-xl font-semibold">Top up</h2>
      <p className="text-white/60 text-sm">
        $1 per application. Minimum $10. Credits are deducted only after the
        employer confirmation email lands.
      </p>

      <div className="mt-5 grid md:grid-cols-3 gap-4">
        {(packs || []).map((p) => (
          <div key={p.id} className="rounded-xl border border-white/10 p-6">
            <div className="text-sm text-white/60">{p.label}</div>
            <div className="mt-2 text-3xl font-semibold">${p.price_usd}</div>
            <div className="mt-1 text-white/80">{p.credits} applications</div>
            {p.bonus_pct > 0 && (
              <div className="mt-1 text-xs text-accent">+{p.bonus_pct}% bonus</div>
            )}
            <button
              onClick={() => buy(p)}
              disabled={!ready}
              className="mt-5 w-full rounded-md bg-accent px-4 py-2 text-sm font-medium disabled:opacity-50"
            >
              {ready ? "Buy" : "Loading…"}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
