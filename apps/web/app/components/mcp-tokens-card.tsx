"use client";

import { Copy, KeyRound, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { getBrowserSupabase, isSupabaseConfigured } from "../lib/supabase-browser";

type TokenRow = {
  id: string;
  label: string | null;
  token_prefix: string;
  created_at: string;
  expires_at: string;
  last_used_at: string | null;
  revoked_at: string | null;
};

const TOKEN_PREFIX = "ia_";

/**
 * Generate an opaque token, return both the cleartext (for the user to
 * copy once) and its sha256 hash (which is what we store).
 */
async function mintToken(): Promise<{ cleartext: string; hash: string; prefix: string }> {
  // 32 random bytes → 64 hex chars
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  const hex = Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
  const cleartext = `${TOKEN_PREFIX}${hex}`;

  const encoder = new TextEncoder();
  const digest = await crypto.subtle.digest("SHA-256", encoder.encode(cleartext));
  const hash = Array.from(new Uint8Array(digest))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");

  return {
    cleartext,
    hash,
    prefix: cleartext.slice(0, 11), // "ia_" + 8 hex chars
  };
}

function fmtDate(iso: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function McpTokensCard() {
  const supabaseReady = isSupabaseConfigured();
  const [tokens, setTokens] = useState<TokenRow[] | null>(null);
  const [label, setLabel] = useState("");
  const [cleartext, setCleartext] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!supabaseReady) {
      setTokens([]);
      return;
    }
    const supabase = getBrowserSupabase();
    if (!supabase) return;
    const { data, error } = await supabase
      .from("mcp_tokens")
      .select("id,label,token_prefix,created_at,expires_at,last_used_at,revoked_at")
      .order("created_at", { ascending: false });
    if (error) {
      setError(error.message);
      return;
    }
    setTokens((data ?? []) as TokenRow[]);
  }, [supabaseReady]);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = async () => {
    setError(null);
    setCleartext(null);
    setCopied(false);

    if (!supabaseReady) {
      setError(
        "Connect the Supabase backend (env vars) to create real MCP tokens."
      );
      return;
    }

    setLoading(true);
    try {
      const supabase = getBrowserSupabase();
      if (!supabase) throw new Error("Auth unavailable");

      const {
        data: { user },
      } = await supabase.auth.getUser();
      if (!user) throw new Error("Not signed in");

      const minted = await mintToken();
      const { error: insertErr } = await supabase.from("mcp_tokens").insert({
        user_id: user.id,
        token_hash: minted.hash,
        token_prefix: minted.prefix,
        label: label.trim() || null,
      });
      if (insertErr) throw insertErr;

      setCleartext(minted.cleartext);
      setLabel("");
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create token.");
    } finally {
      setLoading(false);
    }
  };

  const handleRevoke = async (id: string) => {
    if (!supabaseReady) return;
    if (!confirm("Revoke this token? Any integration using it will stop working.")) return;
    const supabase = getBrowserSupabase();
    if (!supabase) return;
    const { error } = await supabase
      .from("mcp_tokens")
      .update({ revoked_at: new Date().toISOString() })
      .eq("id", id);
    if (error) {
      setError(error.message);
      return;
    }
    await load();
  };

  const copy = async (value: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      // ignore
    }
  };

  const activeTokens = (tokens ?? []).filter((t) => !t.revoked_at);

  return (
    <article className="glass settings-card">
      <div className="console-card-header">
        <div>
          <div className="panel-kicker">Integrations</div>
          <h3>MCP access tokens</h3>
        </div>
        <KeyRound size={18} />
      </div>

      <p className="mcp-tokens-intro">
        Use these tokens to connect Instaply to Claude Desktop (via MCP) or
        the ChatGPT Connector. Tokens expire after 180 days. Treat them like
        passwords — copy once, store in a secret manager.
      </p>

      {cleartext && (
        <div className="mcp-token-reveal">
          <div className="mcp-token-reveal-head">
            <strong>Your new token</strong>
            <span>Shown once — copy it now.</span>
          </div>
          <div className="mcp-token-reveal-value">
            <code>{cleartext}</code>
            <button
              type="button"
              className="mcp-token-copy"
              onClick={() => copy(cleartext)}
            >
              <Copy size={14} />
              {copied ? "Copied" : "Copy"}
            </button>
          </div>
          <button
            type="button"
            className="mcp-token-dismiss"
            onClick={() => setCleartext(null)}
          >
            I&apos;ve copied it — hide
          </button>
        </div>
      )}

      <div className="mcp-token-create-row">
        <input
          type="text"
          className="mcp-token-label-input"
          placeholder='Label (e.g. "My Mac", "Claude Desktop")'
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          maxLength={60}
        />
        <button
          type="button"
          className="btn-primary"
          onClick={handleCreate}
          disabled={loading}
        >
          {loading ? "Generating…" : "Generate new token"}
        </button>
      </div>

      {error && <div className="mcp-token-error">{error}</div>}

      <div className="mcp-token-list">
        {tokens === null ? (
          <div className="mcp-token-empty">Loading…</div>
        ) : activeTokens.length === 0 ? (
          <div className="mcp-token-empty">
            No active tokens yet. Generate one above to connect Claude
            Desktop or the ChatGPT Connector.
          </div>
        ) : (
          activeTokens.map((t) => (
            <div className="mcp-token-row" key={t.id}>
              <div className="mcp-token-row-main">
                <div className="mcp-token-row-label">
                  {t.label || "Unnamed token"}
                </div>
                <div className="mcp-token-row-meta">
                  <code>{t.token_prefix}…</code>
                  <span>· created {fmtDate(t.created_at)}</span>
                  <span>· expires {fmtDate(t.expires_at)}</span>
                  {t.last_used_at && (
                    <span>· last used {fmtDate(t.last_used_at)}</span>
                  )}
                </div>
              </div>
              <button
                type="button"
                className="mcp-token-revoke"
                onClick={() => handleRevoke(t.id)}
                aria-label="Revoke token"
                title="Revoke"
              >
                <Trash2 size={14} />
                Revoke
              </button>
            </div>
          ))
        )}
      </div>
    </article>
  );
}
