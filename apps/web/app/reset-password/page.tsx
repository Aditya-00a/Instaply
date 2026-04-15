"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { LockKeyhole, MoveRight, Sparkles } from "lucide-react";
import { useState } from "react";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

export default function ResetPasswordPage() {
  const router = useRouter();
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  const supabaseReady = isSupabaseConfigured();

  const onSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError("");

    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords don't match.");
      return;
    }

    if (!supabaseReady) {
      setDone(true);
      setTimeout(() => router.push("/sign-in"), 1500);
      return;
    }

    const supabase = getBrowserSupabase();
    if (!supabase) {
      setError("Auth service unavailable.");
      return;
    }

    setLoading(true);
    try {
      const { error: err } = await supabase.auth.updateUser({ password });
      if (err) {
        setError(err.message);
        setLoading(false);
        return;
      }
      setDone(true);
      setTimeout(() => router.push("/sign-in"), 1500);
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
              <h1 className="auth-heading">Set a new password</h1>
              <p className="auth-copy">
                Choose a password you&apos;ll remember. At least 8
                characters.
              </p>
            </div>

            {done ? (
              <div className="auth-notice">
                Password updated. Redirecting to sign-in…
              </div>
            ) : (
              <form className="auth-form" onSubmit={onSubmit}>
                <label className="auth-field">
                  <span>New password</span>
                  <div className="auth-input-shell">
                    <LockKeyhole size={16} />
                    <input
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      required
                      minLength={8}
                      autoComplete="new-password"
                      placeholder="At least 8 characters"
                    />
                  </div>
                </label>

                <label className="auth-field">
                  <span>Confirm new password</span>
                  <div className="auth-input-shell">
                    <LockKeyhole size={16} />
                    <input
                      type="password"
                      value={confirm}
                      onChange={(e) => setConfirm(e.target.value)}
                      required
                      minLength={8}
                      autoComplete="new-password"
                      placeholder="Type it again"
                    />
                  </div>
                </label>

                {error ? <div className="auth-error">{error}</div> : null}

                <button
                  type="submit"
                  className="auth-button auth-button-primary"
                  disabled={loading}
                >
                  {loading ? "Updating…" : "Update password"}
                  <MoveRight size={16} />
                </button>

                <div className="auth-helper">
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
                <p className="eyebrow">Almost there</p>
                <h2>One password away from getting back in.</h2>
              </div>
              <div className="auth-visual-note">
                We hash passwords with bcrypt and never store them in
                plain text. Your new password takes effect immediately.
              </div>
            </div>
          </aside>
        </article>
      </section>
    </main>
  );
}
