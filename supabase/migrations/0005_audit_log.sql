-- ─────────────────────────────────────────────────────────────────
-- Audit log — append-only record of security/financial events.
--
-- Write these from the API for every sensitive action:
--   auth.mcp_token_created / revoked
--   billing.paddle_credited / replay_ignored / bad_signature
--   application.submitted / confirmed / failed
--   profile.updated
--
-- Users can read their own rows (receipt + transparency). Service
-- role writes. No UPDATE or DELETE.
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS audit_log (
  id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id     UUID REFERENCES public.profiles(id) ON DELETE SET NULL,
  event       TEXT NOT NULL,                  -- dotted name, e.g. 'billing.paddle_credited'
  subject_id  TEXT,                           -- txn_id, application_id, token_id, etc.
  ip_hash     TEXT,                           -- sha256(ip + rotating_salt) — pseudonymous
  user_agent  TEXT,
  meta        JSONB NOT NULL DEFAULT '{}',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS audit_log_user_idx
  ON audit_log (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS audit_log_event_idx
  ON audit_log (event, created_at DESC);

ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS audit_log_own_read ON audit_log;
CREATE POLICY audit_log_own_read ON audit_log
  FOR SELECT USING (auth.uid() = user_id);

-- Prevent accidental mutation even with service role typos.
CREATE OR REPLACE FUNCTION audit_log_immutable()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'audit_log is append-only';
END;
$$;

DROP TRIGGER IF EXISTS trg_audit_log_no_update ON audit_log;
CREATE TRIGGER trg_audit_log_no_update
  BEFORE UPDATE OR DELETE ON audit_log
  FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();
