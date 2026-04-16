"use client";

import { Gift, Loader2 } from "lucide-react";
import { useState } from "react";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

/**
 * Lets signed-in users redeem an invite code from /settings.
 * Useful for users who signed up before the invite system existed,
 * or who received a code after signup.
 */
export function InviteCodeCard() {
  const ready = isSupabaseConfigured();
  const [code, setCode] = useState("");
  const [status, setStatus] = useState<
    | { kind: "idle" }
    | { kind: "loading" }
    | { kind: "success"; message: string }
    | { kind: "error"; message: string }
  >({ kind: "idle" });

  const redeem = async () => {
    setStatus({ kind: "loading" });

    if (!ready) {
      setStatus({ kind: "error", message: "Not available in preview mode." });
      return;
    }

    if (!code.trim()) {
      setStatus({ kind: "error", message: "Enter a code." });
      return;
    }

    const supabase = getBrowserSupabase();
    if (!supabase) {
      setStatus({ kind: "error", message: "Auth unavailable." });
      return;
    }

    try {
      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) {
        setStatus({ kind: "error", message: "Please sign in first." });
        return;
      }

      const { data: result, error } = await supabase.rpc("redeem_invite_code", {
        p_code: code.trim().toUpperCase(),
        p_user_id: user.id,
      });

      if (error) {
        setStatus({ kind: "error", message: error.message });
        return;
      }

      if (result === true) {
        setStatus({
          kind: "success",
          message: "Code redeemed! Credits have been added to your balance.",
        });
        setCode("");
      } else {
        setStatus({
          kind: "error",
          message:
            "That code is invalid, expired, already used, or you've already redeemed it.",
        });
      }
    } catch (e) {
      setStatus({
        kind: "error",
        message: e instanceof Error ? e.message : "Redemption failed.",
      });
    }
  };

  return (
    <article className="glass settings-card">
      <div className="console-card-header">
        <div>
          <div className="panel-kicker">Credits</div>
          <h3>Redeem invite code</h3>
        </div>
        <Gift size={18} />
      </div>

      <p className="mcp-tokens-intro">
        Have an invite or promo code? Enter it below to add credits to
        your account. Each code can only be used once.
      </p>

      <div className="account-section-row">
        <input
          type="text"
          value={code}
          onChange={(e) => {
            setCode(e.target.value.toUpperCase().replace(/\s+/g, ""));
            if (status.kind !== "idle") setStatus({ kind: "idle" });
          }}
          placeholder="ABCD2345"
          maxLength={12}
          className="account-input"
          style={{
            fontFamily: "var(--font-mono)",
            letterSpacing: "0.12em",
            textTransform: "uppercase",
          }}
          onKeyDown={(e) => e.key === "Enter" && redeem()}
        />
        <button
          type="button"
          className="btn-primary"
          onClick={redeem}
          disabled={status.kind === "loading" || !code.trim()}
        >
          {status.kind === "loading" ? (
            <>
              <Loader2 size={14} className="spin" /> Redeeming…
            </>
          ) : (
            "Redeem"
          )}
        </button>
      </div>

      {status.kind === "success" && (
        <div className="resume-upload-ok" style={{ marginTop: 10 }}>
          <Gift size={14} /> {status.message}
        </div>
      )}

      {status.kind === "error" && (
        <div className="mcp-token-error" style={{ marginTop: 10 }}>
          {status.message}
        </div>
      )}
    </article>
  );
}
