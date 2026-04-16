"use client";
import { useEffect, useState } from "react";
import { apiDelete, apiGet, apiPost } from "@/lib/api";

type Summary = {
  id: string; label?: string; token_prefix: string;
  created_at: string; expires_at: string;
  last_used_at?: string | null; revoked_at?: string | null;
};

export default function McpSettingsPage() {
  const [tokens, setTokens] = useState<Summary[] | null>(null);
  const [newToken, setNewToken] = useState<string | null>(null);
  const [label, setLabel] = useState("");
  const [err, setErr] = useState<string | null>(null);

  const load = () =>
    apiGet<{ tokens: Summary[] }>("/auth/mcp-tokens")
      .then((d) => setTokens(d.tokens))
      .catch((e) => setErr(String(e)));

  useEffect(() => { load(); }, []);

  async function mint() {
    setErr(null);
    try {
      const r = await apiPost<{ token: string }>("/auth/mcp-tokens", { label });
      setNewToken(r.token);
      setLabel("");
      load();
    } catch (e: any) { setErr(String(e)); }
  }

  async function revoke(id: string) {
    if (!confirm("Revoke this token? MCP clients using it will stop working.")) return;
    await apiDelete(`/auth/mcp-tokens/${id}`);
    load();
  }

  return (
    <div>
      <h1 className="text-3xl font-semibold">MCP access</h1>
      <p className="mt-2 text-white/60 text-sm max-w-2xl">
        Long-lived tokens let Claude Desktop (or any MCP client) run Instaply
        tools on your behalf. Add this to your Claude Desktop config under{" "}
        <span className="font-mono">mcpServers</span>.
      </p>

      {newToken && (
        <div className="mt-6 rounded-lg border border-accent/50 bg-accent/10 p-4">
          <div className="text-sm text-white/80">Copy this now — you won't see it again:</div>
          <code className="mt-2 block break-all font-mono text-sm">{newToken}</code>
          <button onClick={() => setNewToken(null)} className="mt-3 text-xs underline">
            Hide
          </button>
        </div>
      )}

      <div className="mt-6 flex gap-3">
        <input value={label} onChange={(e) => setLabel(e.target.value)}
               placeholder="Label (e.g. 'MacBook Pro')"
               className="flex-1 rounded-md bg-white/5 border border-white/10 px-3 py-2 text-sm" />
        <button onClick={mint}
                className="rounded-md bg-accent px-4 py-2 text-sm font-medium">
          Generate token
        </button>
      </div>

      {err && <div className="mt-3 text-red-400 text-sm">{err}</div>}

      <h2 className="mt-10 text-xl font-semibold">Active tokens</h2>
      <div className="mt-4 divide-y divide-white/5 rounded-lg border border-white/10">
        {(tokens || []).length === 0 && (
          <div className="p-4 text-sm text-white/60">No tokens yet.</div>
        )}
        {(tokens || []).map((t) => (
          <div key={t.id} className="flex items-center justify-between p-4">
            <div>
              <div className="text-sm">
                {t.label || <span className="text-white/60">(unlabeled)</span>}
                <span className="ml-2 text-xs font-mono text-white/50">ia_{t.token_prefix}…</span>
                {t.revoked_at && <span className="ml-2 text-xs text-red-400">revoked</span>}
              </div>
              <div className="text-xs text-white/50">
                Created {new Date(t.created_at).toLocaleDateString()} ·{" "}
                Expires {new Date(t.expires_at).toLocaleDateString()}
              </div>
            </div>
            {!t.revoked_at && (
              <button onClick={() => revoke(t.id)}
                      className="text-xs text-red-400 underline">
                Revoke
              </button>
            )}
          </div>
        ))}
      </div>

      <h2 className="mt-10 text-xl font-semibold">Claude Desktop config</h2>
      <pre className="mt-3 overflow-x-auto rounded-lg border border-white/10 bg-white/5 p-4 text-xs">
{`{
  "mcpServers": {
    "instaply": {
      "command": "uvx",
      "args": ["instaply-mcp"],
      "env": {
        "INSTAPLY_TOKEN": "ia_...",
        "INSTAPLY_API_BASE": "https://api.asion.ai"
      }
    }
  }
}`}
      </pre>
    </div>
  );
}
