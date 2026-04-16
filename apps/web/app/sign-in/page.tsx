"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Chrome, LockKeyhole, Mail, MoveRight, Sparkles } from "lucide-react";
import { Suspense, useState } from "react";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

const DEMO_EMAIL = "demo@instaply.app";
const DEMO_PASSWORD = "InstaplyDemo123!";
const POLICY_VERSION = "2026-04-14";

export default function SignInPage() {
  return (
    <Suspense fallback={<main className="auth-shell auth-shell-brand" />}>
      <SignInContent />
    </Suspense>
  );
}

function SignInContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = searchParams.get("next") || "/dashboard";
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [acceptLegal, setAcceptLegal] = useState(false);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [notice, setNotice] = useState("");
  const [mfaFactorId, setMfaFactorId] = useState<string | null>(null);
  const [mfaCode, setMfaCode] = useState("");
  const [inviteCode, setInviteCode] = useState("");

  const inviteRequired = process.env.NEXT_PUBLIC_INVITE_REQUIRED === "true";

  const submitMfa = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError("");
    if (!mfaFactorId) return;
    if (mfaCode.length !== 6) {
      setError("Enter the 6-digit code from your authenticator app.");
      return;
    }
    const supabase = getBrowserSupabase();
    if (!supabase) return;
    setLoading(true);
    const { data: chal, error: chalErr } = await supabase.auth.mfa.challenge({
      factorId: mfaFactorId,
    });
    if (chalErr || !chal) {
      setError(chalErr?.message ?? "Could not start MFA challenge.");
      setLoading(false);
      return;
    }
    const { error: verr } = await supabase.auth.mfa.verify({
      factorId: mfaFactorId,
      challengeId: chal.id,
      code: mfaCode,
    });
    if (verr) {
      setError(verr.message);
      setLoading(false);
      return;
    }
    router.push(nextPath);
    router.refresh();
  };

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

    if (mode === "signup" && inviteRequired && !inviteCode.trim()) {
      setError("This is a closed beta — please enter your invite code to sign up.");
      return;
    }

    // Demo fallback when Supabase isn't configured (local dev, preview builds)
    if (!supabaseReady) {
      if (mode === "signin") {
        if (
          emailValue.trim().toLowerCase() === DEMO_EMAIL.toLowerCase() &&
          passwordValue === DEMO_PASSWORD
        ) {
          router.push(nextPath);
          return;
        }
        setError(
          "Supabase is not configured in this environment. Use the demo credentials shown below."
        );
        return;
      }
      // signup demo: just take them to dashboard
      router.push(nextPath);
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

        // Check if account has 2FA — if so, surface a code prompt before
        // we route to the dashboard. Supabase requires aal2 once a TOTP
        // factor is enrolled.
        const {
          data: aal,
        } = await supabase.auth.mfa.getAuthenticatorAssuranceLevel();
        if (aal && aal.nextLevel === "aal2" && aal.currentLevel !== "aal2") {
          const { data: factors } = await supabase.auth.mfa.listFactors();
          const totp = factors?.totp?.[0];
          if (totp) {
            setMfaFactorId(totp.id);
            setLoading(false);
            return;
          }
        }

        router.push(nextPath);
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

        // Redeem the invite code (if provided) to grant tester credits.
        if (inviteCode.trim()) {
          const { data: redeemed } = await supabase.rpc("redeem_invite_code", {
            p_code: inviteCode.trim().toUpperCase(),
            p_user_id: data.user.id,
          });
          if (redeemed === false && inviteRequired) {
            setError(
              "That invite code is invalid, expired, or already used. Contact hello@asion.ai if you think this is wrong."
            );
            setLoading(false);
            return;
          }
        }
      }

      // Fire welcome email (best-effort, don't block signup on failure)
      if (data.user?.email) {
        fetch("/api/email/welcome", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            email: data.user.email,
            name: data.user.user_metadata?.full_name,
          }),
        }).catch(() => {});
      }

      if (data.session) {
        router.push(nextPath);
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

            {mfaFactorId ? (
              <form className="auth-form" onSubmit={submitMfa}>
                <div className="auth-notice">
                  <strong>Two-factor verification</strong>
                  <br />
                  Open your authenticator app and enter the 6-digit code
                  for Instaply.
                </div>
                <label className="auth-field">
                  <span>Authenticator code</span>
                  <div className="auth-input-shell">
                    <LockKeyhole size={16} />
                    <input
                      type="text"
                      inputMode="numeric"
                      pattern="[0-9]{6}"
                      maxLength={6}
                      value={mfaCode}
                      onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, ""))}
                      placeholder="123456"
                      required
                      autoFocus
                    />
                  </div>
                </label>
                {error ? <div className="auth-error">{error}</div> : null}
                <button
                  type="submit"
                  className="auth-button auth-button-primary"
                  disabled={loading || mfaCode.length !== 6}
                >
                  {loading ? "Verifying…" : "Verify"}
                  <MoveRight size={16} />
                </button>
                <button
                  type="button"
                  className="auth-button auth-button-secondary"
                  onClick={() => {
                    setMfaFactorId(null);
                    setMfaCode("");
                    setError("");
                  }}
                >
                  Cancel
                </button>
              </form>
            ) : (
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
                  <Link href="/forgot-password">Forgot password?</Link>
                </div>
              ) : (
                <>
                  {inviteRequired && (
                    <label className="auth-field">
                      <span>
                        Invite code <em style={{ color: "var(--accent)", fontStyle: "normal" }}>
                          (closed beta — testers get 1000 credits)
                        </em>
                      </span>
                      <div className="auth-input-shell">
                        <Sparkles size={16} />
                        <input
                          type="text"
                          value={inviteCode}
                          onChange={(e) =>
                            setInviteCode(e.target.value.toUpperCase().replace(/\s+/g, ""))
                          }
                          placeholder="ABCD2345"
                          maxLength={12}
                          required
                          autoCapitalize="characters"
                          style={{ fontFamily: "var(--font-mono)", letterSpacing: "0.1em" }}
                        />
                      </div>
                    </label>
                  )}
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
                </>
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
            )}

            {!mfaFactorId && (
              <>
            <div className="auth-divider">
              <span>or continue with</span>
            </div>

            <div className="auth-actions">
              <button
                className="auth-button auth-button-secondary"
                type="button"
                disabled={loading}
                onClick={async () => {
                  setError("");
                  if (!supabaseReady) {
                    setError(
                      "Google sign-in is unavailable in preview mode. Use the demo credentials."
                    );
                    return;
                  }
                  const supabase = getBrowserSupabase();
                  if (!supabase) {
                    setError("Auth service unavailable.");
                    return;
                  }
                  const redirectTo =
                    typeof window !== "undefined"
                      ? `${window.location.origin}/auth/callback?next=${encodeURIComponent(nextPath)}`
                      : undefined;
                  const { error: err } = await supabase.auth.signInWithOAuth({
                    provider: "google",
                    options: { redirectTo },
                  });
                  if (err) setError(err.message);
                }}
              >
                <Chrome size={16} />
                Continue with Google
              </button>
              <button
                className="auth-button auth-button-secondary"
                type="button"
                disabled={loading || !email}
                onClick={async () => {
                  setError("");
                  setNotice("");
                  if (!email) {
                    setError("Enter your email first to receive a magic link.");
                    return;
                  }
                  if (!supabaseReady) {
                    setError(
                      "Magic-link sign-in is unavailable in preview mode."
                    );
                    return;
                  }
                  const supabase = getBrowserSupabase();
                  if (!supabase) {
                    setError("Auth service unavailable.");
                    return;
                  }
                  const emailRedirectTo =
                    typeof window !== "undefined"
                      ? `${window.location.origin}/auth/callback?next=${encodeURIComponent(nextPath)}`
                      : undefined;
                  const { error: err } = await supabase.auth.signInWithOtp({
                    email: email.trim(),
                    options: { emailRedirectTo },
                  });
                  if (err) {
                    setError(err.message);
                  } else {
                    setNotice(
                      `Magic link sent to ${email}. Check your inbox.`
                    );
                  }
                }}
              >
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
              </>
            )}
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
