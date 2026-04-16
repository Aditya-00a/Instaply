"use client";
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import { apiGet, apiPost } from "@/lib/api";

type Pack = { id: string; label: string; price_usd: number; credits: number; bonus_pct: number };
type Credits = { balance: number; plan: string; used?: number };

export default function BillingPage() {
  const [packs, setPacks] = useState<Pack[] | null>(null);
  const [credits, setCredits] = useState<Credits | null>(null);
  const [buying, setBuying] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  useEffect(() => {
    // Check URL params for post-checkout status
    const params = new URLSearchParams(window.location.search);
    if (params.get("success") === "1") setSuccess(true);

    (async () => {
      const { data: { user } } = await supabase().auth.getUser();
      if (!user) { window.location.href = "/signup"; return; }
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

  async function buy(pack: Pack) {
    setBuying(pack.id);
    setErr(null);
    try {
      const res = await apiPost<{ checkout_url: string }>("/billing/create-checkout", {
        pack_id: pack.id,
      });
      // Redirect to Stripe Checkout
      window.location.href = res.checkout_url;
    } catch (e: any) {
      setErr(e.message || "Checkout failed");
      setBuying(null);
    }
  }

  return (
    <div>
      <h1 className="text-3xl font-semibold">Billing</h1>

      {success && (
        <div className="mt-4 rounded-md border border-emerald-500/30 bg-emerald-500/10 p-4 text-sm text-emerald-300">
          Payment successful! Credits will appear in a few seconds.
        </div>
      )}

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
              disabled={buying !== null}
              className="mt-5 w-full rounded-md bg-accent px-4 py-2 text-sm font-medium disabled:opacity-50"
            >
              {buying === p.id ? "Redirecting…" : "Buy"}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
