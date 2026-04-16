"use client";

import { Coins, Send } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

/**
 * Persistent credit + applications badge. Shows on every signed-in page.
 */
export function CreditBadge() {
  const ready = isSupabaseConfigured();
  const [balance, setBalance] = useState<number | null>(null);
  const [appCount, setAppCount] = useState<number | null>(null);

  useEffect(() => {
    if (!ready) {
      setBalance(3);
      setAppCount(7);
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

      const [{ data: bal }, { count }] = await Promise.all([
        supabase.rpc("get_credit_balance", { p_user_id: user.id }),
        supabase
          .from("applications")
          .select("id", { count: "exact", head: true })
          .eq("user_id", user.id)
          .in("status", ["submitted", "confirmed"]),
      ]);

      if (!cancelled) {
        setBalance(typeof bal === "number" ? bal : 0);
        setAppCount(count ?? 0);
      }
    })();
    return () => { cancelled = true; };
  }, [ready]);

  if (balance === null) return null;

  return (
    <div className="credit-badges">
      <Link href="/billing" className="credit-badge" title="View billing">
        <Coins size={14} />
        <span className="credit-badge-count">{balance}</span>
        <span className="credit-badge-label">credits</span>
      </Link>
      <Link href="/applications" className="credit-badge credit-badge-apps" title="View applications">
        <Send size={13} />
        <span className="credit-badge-count">{appCount ?? 0}</span>
        <span className="credit-badge-label">submitted</span>
      </Link>
    </div>
  );
}
