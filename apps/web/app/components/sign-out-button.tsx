"use client";

import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

/**
 * Real sign-out: calls supabase.auth.signOut() then pushes to /sign-in.
 * Falls back to plain navigation in demo mode.
 */
export function SignOutButton() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  const onClick = async () => {
    if (busy) return;
    setBusy(true);
    try {
      if (isSupabaseConfigured()) {
        const supabase = getBrowserSupabase();
        await supabase?.auth.signOut();
      }
    } finally {
      router.push("/sign-in");
      router.refresh();
    }
  };

  return (
    <button
      type="button"
      onClick={onClick}
      className="console-logout-button"
      disabled={busy}
    >
      <LogOut size={15} />
      <span>{busy ? "Signing out…" : "Log out"}</span>
    </button>
  );
}
