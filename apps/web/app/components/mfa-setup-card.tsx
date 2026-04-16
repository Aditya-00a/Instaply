"use client";

import { Check, Loader2, ShieldCheck, ShieldOff, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

type Factor = {
  id: string;
  friendly_name?: string;
  factor_type: string;
  status: string;
  created_at: string;
};

type EnrollState =
  | { kind: "idle" }
  | { kind: "starting" }
  | { kind: "ready"; factorId: string; qr: string; secret: string }
  | { kind: "verifying" }
  | { kind: "error"; message: string };

/**
 * 2FA via Supabase Auth TOTP.
 *
 * Flow:
 *   1. supabase.auth.mfa.enroll({ factorType: 'totp' })
 *      → returns factor id, otpauth URL, base32 secret, QR (data URL)
 *   2. User scans QR with Authenticator / 1Password / Authy
 *   3. User enters first 6-digit code
 *   4. supabase.auth.mfa.challenge + verify → factor goes from
 *      'unverified' to 'verified'
 *
 * After enrollment, sign-in requires the code on every login.
 */
export function MfaSetupCard() {
  const ready = isSupabaseConfigured();
  const [factors, setFactors] = useState<Factor[] | null>(ready ? null : []);
  const [enroll, setEnroll] = useState<EnrollState>({ kind: "idle" });
  const [code, setCode] = useState("");
  const [verified, setVerified] = useState(false);

  const load = useCallback(async () => {
    if (!ready) return;
    const supabase = getBrowserSupabase();
    if (!supabase) return;
    const { data, error } = await supabase.auth.mfa.listFactors();
    if (!error && data) {
      // listFactors returns { totp: Factor[], phone: Factor[] }
      const totps = (data.totp ?? []) as Factor[];
      setFactors(totps);
    }
  }, [ready]);

  useEffect(() => {
    load();
  }, [load]);

  const startEnrollment = async () => {
    if (!ready) {
      setEnroll({
        kind: "error",
        message: "Sign in to a real account to enable 2FA.",
      });
      return;
    }
    setEnroll({ kind: "starting" });
    const supabase = getBrowserSupabase();
    if (!supabase) {
      setEnroll({ kind: "error", message: "Auth unavailable." });
      return;
    }

    const { data, error } = await supabase.auth.mfa.enroll({
      factorType: "totp",
      friendlyName: `Instaply (${new Date().toLocaleDateString()})`,
    });
    if (error || !data) {
      setEnroll({ kind: "error", message: error?.message ?? "Enroll failed." });
      return;
    }
    setEnroll({
      kind: "ready",
      factorId: data.id,
      qr: data.totp.qr_code,
      secret: data.totp.secret,
    });
  };

  const verifyEnrollment = async () => {
    if (enroll.kind !== "ready") return;
    if (code.length !== 6) {
      setEnroll({ ...enroll });
      return;
    }
    setEnroll({ kind: "verifying" });
    const supabase = getBrowserSupabase();
    if (!supabase) {
      setEnroll({ kind: "error", message: "Auth unavailable." });
      return;
    }
    const factorId = (enroll as { factorId: string }).factorId;
    const { data: chal, error: chalErr } = await supabase.auth.mfa.challenge({
      factorId,
    });
    if (chalErr || !chal) {
      setEnroll({ kind: "error", message: chalErr?.message ?? "Challenge failed." });
      return;
    }
    const { error: verifyErr } = await supabase.auth.mfa.verify({
      factorId,
      challengeId: chal.id,
      code,
    });
    if (verifyErr) {
      setEnroll({ kind: "error", message: verifyErr.message });
      return;
    }
    setVerified(true);
    setCode("");
    setEnroll({ kind: "idle" });
    await load();
    setTimeout(() => setVerified(false), 4000);
  };

  const removeFactor = async (id: string) => {
    if (!confirm("Disable 2FA? You'll only need a password to sign in."))
      return;
    const supabase = getBrowserSupabase();
    if (!supabase) return;
    const { error } = await supabase.auth.mfa.unenroll({ factorId: id });
    if (error) {
      alert("Could not remove: " + error.message);
      return;
    }
    await load();
  };

  const enrolled = (factors ?? []).filter((f) => f.status === "verified");

  return (
    <article className="glass settings-card">
      <div className="console-card-header">
        <div>
          <div className="panel-kicker">Security</div>
          <h3>Two-factor authentication</h3>
        </div>
        {enrolled.length > 0 ? (
          <ShieldCheck size={18} color="#10b981" />
        ) : (
          <ShieldOff size={18} />
        )}
      </div>

      <p className="mcp-tokens-intro">
        Add a code from an authenticator app (Google Authenticator,
        1Password, Authy, etc.) on every sign-in. Strongly recommended —
        protects your account if your password is ever leaked.
      </p>

      {verified && (
        <div className="resume-upload-ok">
          <Check size={14} /> 2FA enabled. You&apos;ll need a code on next sign-in.
        </div>
      )}

      {enroll.kind === "ready" && (
        <div className="mfa-enroll">
          <div className="mfa-enroll-row">
            <div className="mfa-qr-wrap">
              {/* Supabase returns a data URL */}
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={enroll.qr} alt="2FA QR code" className="mfa-qr" />
            </div>
            <div className="mfa-enroll-instructions">
              <strong>1. Scan with your authenticator app</strong>
              <p>Or enter this code manually:</p>
              <code className="mfa-secret">{enroll.secret}</code>
              <strong style={{ marginTop: 12 }}>2. Enter the 6-digit code</strong>
              <input
                type="text"
                inputMode="numeric"
                pattern="[0-9]{6}"
                maxLength={6}
                value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                placeholder="123456"
                className="mfa-code-input"
                autoFocus
              />
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  type="button"
                  className="btn-primary"
                  onClick={verifyEnrollment}
                  disabled={code.length !== 6}
                >
                  Verify and enable
                </button>
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={() => {
                    setEnroll({ kind: "idle" });
                    setCode("");
                  }}
                >
                  Cancel
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {enroll.kind === "verifying" && (
        <div className="ats-scoring-row">
          <Loader2 size={14} className="spin" />
          Verifying…
        </div>
      )}

      {enroll.kind === "error" && (
        <div className="mcp-token-error">{enroll.message}</div>
      )}

      {enroll.kind === "idle" && enrolled.length === 0 && (
        <button
          type="button"
          className="btn-primary"
          onClick={startEnrollment}
          disabled={!ready}
          style={{ alignSelf: "flex-start" }}
        >
          Enable 2FA
        </button>
      )}

      {enroll.kind === "starting" && (
        <div className="ats-scoring-row">
          <Loader2 size={14} className="spin" />
          Generating QR code…
        </div>
      )}

      {enrolled.length > 0 && (
        <div className="mcp-token-list" style={{ marginTop: 8 }}>
          {enrolled.map((f) => (
            <div className="mcp-token-row" key={f.id}>
              <div className="mcp-token-row-main">
                <div className="mcp-token-row-label">
                  {f.friendly_name || "Authenticator"}
                </div>
                <div className="mcp-token-row-meta">
                  <span>Active · enrolled {new Date(f.created_at).toLocaleDateString()}</span>
                </div>
              </div>
              <button
                type="button"
                className="mcp-token-revoke"
                onClick={() => removeFactor(f.id)}
              >
                <Trash2 size={14} />
                Remove
              </button>
            </div>
          ))}
        </div>
      )}

      {!ready && (
        <div className="resume-upload-note">
          Sign in to a real account to enable 2FA.
        </div>
      )}
    </article>
  );
}
