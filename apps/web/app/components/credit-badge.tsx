"use client";

import { Coins } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

/**
 * Persistent credit balance badge. Shows the user's current credit
 * count everywhere in the signed-in shell.
 */
export function CreditBadge() {
  const ready = isSupabaseConfigured();
  const [balance, setBalance] = useState<number | null>(null);

  useEffect(() => {
    if (!ready) {
      setBalance(3); // demo
      return;
    }
    let cancelled = false;
    (async () => {
      const supabase = getBrowserSupabase();
      if (!supabase) return;
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user || cancelled) return;
      const { data } = await supabase.rpc("get_credit_balance", {
        p_user_id: user.id,
      });
      if (!cancelled) setBalance(typeof data === "number" ? data : 0);
    })();
    return () => { cancelled = true; };
  }, [ready]);

  if (balance === null) return null;

  return (
    <Link href="/billing" className="credit-badge" title="View billing">
      <Coins size={14} />
      <span className="credit-badge-count">{balance}</span>
      <span className="credit-badge-label">credits</span>
    </Link>
  );
}
