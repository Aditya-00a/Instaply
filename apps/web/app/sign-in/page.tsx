"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Chrome, LockKeyhole, Mail, MoveRight, Sparkles } from "lucide-react";
import { useState } from "react";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

const DEMO_EMAIL = "demo@instaply.app";
const DEMO_PASSWORD = "InstaplyDemo123!";
const POLICY_VERSION = "2026-04-14";

export default function SignInPage() {
  const router = useRouter();
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [acceptLegal, setAcceptLegal] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");

  const supabaseReady = isSupabaseConfigured();

  // In demo mode (no env vars), prefill demo creds so local previews
  // still let you through.
  const emailValue = !supabaseReady && mode === "signin" && !email
    ? DEMO_EMAIL : email;
  const passwordValue = !supabaseReady && mode === "signin" && !password
    ? DEMO_PASSWORD : password;

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    setNotice("");

    if (mode === "signup" && !acceptLegal) {
      setError(
        "You must accept the Terms of Service, Privacy Policy, and Refund Policy to create an account."
      );
      return;
    }

    // Demo fallback when Supabase isn't configured (local dev, preview builds)
    if (!supabaseReady) {
      if (mode === "signin") {
        if (
          emailValue.trim().toLowerCase() === DEMO_EMAIL.toLowerCase() &&
          passwordValue === DEMO_PASSWORD
        ) {
          router.push("/dashboard");
          return;
        }
        setError(
          "Supabase is not configured in this environment. Use the demo credentials shown below."
        );
        return;
      }
      // signup demo: just take them to dashboard
      router.push("/dashboard");
      return;
    }

    // Real Supabase auth path
    const supabase = getBrowserSupabase();
    if (!supabase) {
      setError("Auth service unavailable. Try again shortly.");
      return;
    }

    setLoading(true);
    try {
      if (mode === "signin") {
        const { error: err } = await supabase.auth.signInWithPassword({
          email: email.trim(),
          password,
        });
        if (err) {
          setError(err.message);
          setLoading(false);
          return;
        }
        router.push("/dashboard");
        router.refresh();
        return;
      }

      // Signup
      const { data, error: err } = await supabase.auth.signUp({
        email: email.trim(),
        password,
        options: {
          emailRedirectTo:
            typeof window !== "undefined"
              ? `${window.location.origin}/dashboard`
              : undefined,
          data: {
            legal_accepted_at: new Date().toISOString(),
            legal_accepted_version: POLICY_VERSION,
          },
        },
      });
      if (err) {
        setError(err.message);
        setLoading(false);
        return;
      }

      // Write the acceptance details onto the profile row created by
      // the handle_new_user trigger.
      if (data.user) {
        await supabase
          .from("profiles")
          .update({
            legal_accepted_at: new Date().toISOString(),
            legal_accepted_version: POLICY_VERSION,
          })
          .eq("id", data.user.id);
      }

      if (data.session) {
        router.push("/dashboard");
        router.refresh();
      } else {
        setNotice(
          "Account created. Check your email to confirm your address, then sign in."
        );
        setMode("signin");
      }
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
              <h1 className="auth-heading">
                {mode === "signin" ? "Welcome back" : "Create your account"}
              </h1>
              <p className="auth-copy">
                {mode === "signin"
                  ? "Sign in to manage your applications, answers, documents, and billing in one place."
                  : "Get 3 free applications to try Instaply. No credit card required."}
              </p>
            </div>

            <div className="auth-tab-row" aria-label="Authentication mode">
              <button
                className={`auth-tab${mode === "signin" ? " auth-tab-active" : ""}`}
                type="button"
                onClick={() => { setMode("signin"); setError(""); setNotice(""); }}
              >
                Sign in
              </button>
              <button
                className={`auth-tab${mode === "signup" ? " auth-tab-active" : ""}`}
                type="button"
                onClick={() => { setMode("signup"); setError(""); setNotice(""); }}
              >
                Create account
              </button>
            </div>

            {mode === "signin" && !supabaseReady && (
              <div className="auth-demo-credentials">
                <strong>Demo access</strong>
                <span>{DEMO_EMAIL}</span>
                <span>{DEMO_PASSWORD}</span>
              </div>
            )}

            {notice ? <div className="auth-notice">{notice}</div> : null}

            <form className="auth-form" onSubmit={handleSubmit}>
              <label className="auth-field">
                <span>Email address</span>
                <div className="auth-input-shell">
                  <Mail size={16} />
                  <input
                    placeholder="you@domain.com"
                    type="email"
                    value={emailValue}
                    onChange={(event) => setEmail(event.target.value)}
                    required
                    autoComplete="email"
                  />
                </div>
              </label>

              <label className="auth-field">
                <span>Password</span>
                <div className="auth-input-shell">
                  <LockKeyhole size={16} />
                  <input
                    placeholder={mode === "signup" ? "At least 8 characters" : "Your password"}
                    type="password"
                    value={passwordValue}
                    onChange={(event) => setPassword(event.target.value)}
                    required
                    minLength={mode === "signup" ? 8 : undefined}
                    autoComplete={mode === "signup" ? "new-password" : "current-password"}
                  />
                </div>
              </label>

              {mode === "signin" ? (
                <div className="auth-row">
                  <label className="auth-checkbox">
                    <input type="checkbox" />
                    <span>Remember me</span>
                  </label>
                  <Link href="/">Forgot password?</Link>
                </div>
              ) : (
                <label className="auth-checkbox auth-checkbox-legal">
                  <input
                    type="checkbox"
                    checked={acceptLegal}
                    onChange={(event) => setAcceptLegal(event.target.checked)}
                    required
                  />
                  <span>
                    I have read and agree to the{" "}
                    <Link href="/terms" target="_blank">Terms of Service</Link>,{" "}
                    <Link href="/privacy" target="_blank">Privacy Policy</Link>, and{" "}
                    <Link href="/refund" target="_blank">Refund Policy</Link>.
                  </span>
                </label>
              )}

              {error ? <div className="auth-error">{error}</div> : null}

              <button
                className="auth-button auth-button-primary"
                type="submit"
                disabled={loading}
              >
                {loading
                  ? "Working…"
                  : mode === "signin"
                  ? "Sign in"
                  : "Create account"}
                <MoveRight size={16} />
              </button>
            </form>

            <div className="auth-divider">
              <span>or continue with</span>
            </div>

            <div className="auth-actions">
              <button className="auth-button auth-button-secondary" type="button">
                <Chrome size={16} />
                Continue with Google
              </button>
              <button className="auth-button auth-button-secondary" type="button">
                <Mail size={16} />
                Continue with email link
              </button>
            </div>

            <div className="auth-helper">
              <span>
                {supabaseReady
                  ? "Your account works across the web dashboard, Claude Desktop MCP, and the ChatGPT Connector."
                  : "Preview mode — connect Supabase env vars to enable real accounts."}
              </span>
              <Link href="/">Back to website</Link>
            </div>
          </div>

          <aside className="auth-visual-panel">
            <div className="auth-visual-surface">
              <div className="auth-orb auth-orb-large" />
              <div className="auth-orb auth-orb-small" />
              <div className="auth-visual-copy">
                <p className="eyebrow">Private workspace</p>
                <h2>Review strong matches, clear blocked answers, and move tailored applications forward.</h2>
                <div className="auth-visual-pills">
                  <span className="auth-visual-pill">Matched roles</span>
                  <span className="auth-visual-pill">Saved answers</span>
                  <span className="auth-visual-pill">Tailored packets</span>
                </div>
              </div>
              <div className="auth-visual-note">Sign in to manage your profile, review queue, documents, credits, and application progress.</div>
            </div>
          </aside>
        </article>
      </section>
    </main>
  );
}
