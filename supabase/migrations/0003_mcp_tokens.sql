-- ─── MCP long-lived tokens ────────────────────────────────────
-- Opaque tokens (not JWTs) issued to users for Claude Desktop / future
-- ChatGPT MCP integration. Stored as sha256 hash; plaintext never persisted.
-- Revocable from the web dashboard.

CREATE TABLE IF NOT EXISTS mcp_tokens (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  token_hash     TEXT NOT NULL UNIQUE,            -- sha256 of the plaintext token
  token_prefix   TEXT NOT NULL,                   -- first 8 chars, for UI display
  label          TEXT,                            -- user-chosen ("My Mac", "Claude Desktop", etc.)
  created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at     TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '180 days'),
  last_used_at   TIMESTAMPTZ,
  revoked_at     TIMESTAMPTZ,
  user_agent     TEXT
);

CREATE INDEX IF NOT EXISTS mcp_tokens_user ON mcp_tokens (user_id) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS mcp_tokens_hash ON mcp_tokens (token_hash) WHERE revoked_at IS NULL;

ALTER TABLE mcp_tokens ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS mcp_tokens_self_read ON mcp_tokens;
CREATE POLICY mcp_tokens_self_read ON mcp_tokens
  FOR SELECT USING (auth.uid() = user_id);

DROP POLICY IF EXISTS mcp_tokens_self_insert ON mcp_tokens;
CREATE POLICY mcp_tokens_self_insert ON mcp_tokens
  FOR INSERT WITH CHECK (auth.uid() = user_id);

DROP POLICY IF EXISTS mcp_tokens_self_update ON mcp_tokens;
CREATE POLICY mcp_tokens_self_update ON mcp_tokens
  FOR UPDATE USING (auth.uid() = user_id);

-- Lookup + last-used bump in one RPC (service role only).
CREATE OR REPLACE FUNCTION resolve_mcp_token(p_token_hash TEXT)
RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_user_id UUID;
BEGIN
  UPDATE mcp_tokens
     SET last_used_at = NOW()
   WHERE token_hash = p_token_hash
     AND revoked_at IS NULL
     AND expires_at > NOW()
  RETURNING user_id INTO v_user_id;
  RETURN v_user_id;
END;
$$;
