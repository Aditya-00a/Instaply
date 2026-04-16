"use client";
import { useState } from "react";
import { supabase } from "@/lib/supabase";

export default function SignupPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      const { error } = await supabase().auth.signInWithOtp({
        email,
        options: { emailRedirectTo: `${window.location.origin}/onboarding` },
      });
      if (error) throw error;
      setSent(true);
    } catch (e: any) {
      setErr(e.message || "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-md mx-auto">
      <h1 className="text-3xl font-semibold">Sign in to Instaply</h1>
      <p className="mt-2 text-white/60 text-sm">
        We'll email you a magic link. New accounts start with 3 free applications.
      </p>

      {sent ? (
        <div className="mt-8 rounded-md border border-white/10 p-5 text-sm">
          Check <span className="font-mono">{email}</span> for a sign-in link.
        </div>
      ) : (
        <form onSubmit={onSubmit} className="mt-8 space-y-4">
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            className="w-full rounded-md bg-white/5 border border-white/10 px-3 py-3 text-sm"
          />
          <button
            disabled={busy}
            className="w-full rounded-md bg-accent px-5 py-3 text-sm font-medium disabled:opacity-50"
          >
            {busy ? "Sending…" : "Send magic link"}
          </button>
          {err && <div className="text-red-400 text-sm">{err}</div>}
        </form>
      )}
    </div>
  );
}
