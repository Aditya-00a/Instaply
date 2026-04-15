"use client";

import Link from "next/link";
import { LockKeyhole, Mail, MoveRight, Sparkles } from "lucide-react";
import { useState } from "react";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  const [loading, setLoading] = useState(false);

  const supabaseReady = isSupabaseConfigured();

  const onSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError("");

    if (!supabaseReady) {
      setSent(true); // fake success for demo
      return;
    }

    const supabase = getBrowserSupabase();
    if (!supabase) {
      setError("Auth service unavailable.");
      return;
    }

    setLoading(true);
    try {
      const redirectTo =
        typeof window !== "undefined"
          ? `${window.location.origin}/reset-password`
          : undefined;

      const { error: err } = await supabase.auth.resetPasswordForEmail(
        email.trim(),
        { redirectTo }
      );
      if (err) {
        setError(err.message);
        setLoading(false);
        return;
      }
      setSent(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="auth-shell auth-shell-brand">
      <section className="auth-frame">
        <article className="auth-split-card">
          <div className="auth-form-panel">
            <div className="auth-brand-row">
              <Link className="auth-brand-mark" href="/">
                <Sparkles size={16} />
                <span>Instaply</span>
              </Link>
            </div>

            <div className="auth-copy-block">
              <h1 className="auth-heading">Forgot your password?</h1>
              <p className="auth-copy">
                Enter the email on your account and we&apos;ll send you a
                secure link to set a new one.
              </p>
            </div>

            {sent ? (
              <div className="auth-notice">
                If an account exists for <strong>{email}</strong>, a reset
                link is on its way. Check your inbox and spam folder.
                <br />
                <Link
                  href="/sign-in"
                  style={{
                    color: "var(--accent)",
                    textDecoration: "none",
                    fontWeight: 500,
                    marginTop: 8,
                    display: "inline-block",
                  }}
                >
                  Back to sign in →
                </Link>
              </div>
            ) : (
              <form className="auth-form" onSubmit={onSubmit}>
                <label className="auth-field">
                  <span>Email address</span>
                  <div className="auth-input-shell">
                    <Mail size={16} />
                    <input
                      placeholder="you@domain.com"
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      required
                      autoComplete="email"
                    />
                  </div>
                </label>

                {error ? <div className="auth-error">{error}</div> : null}

                <button
                  type="submit"
                  className="auth-button auth-button-primary"
                  disabled={loading}
                >
                  {loading ? "Sending…" : "Send reset link"}
                  <MoveRight size={16} />
                </button>

                <div className="auth-helper">
                  <span>Remembered it?</span>
                  <Link href="/sign-in">Back to sign in</Link>
                </div>
              </form>
            )}
          </div>

          <aside className="auth-visual-panel">
            <div className="auth-visual-surface">
              <div className="auth-orb auth-orb-large" />
              <div className="auth-orb auth-orb-small" />
              <div className="auth-visual-copy">
                <p className="eyebrow">Account recovery</p>
                <h2>
                  <LockKeyhole size={18} /> Resets are one click away.
                </h2>
                <div className="auth-visual-pills">
                  <span className="auth-visual-pill">Email link</span>
                  <span className="auth-visual-pill">Secure</span>
                  <span className="auth-visual-pill">Instant</span>
                </div>
              </div>
              <div className="auth-visual-note">
                We never store your password in plain text. Reset links
                expire after one hour.
              </div>
            </div>
          </aside>
        </article>
      </section>
    </main>
  );
}
