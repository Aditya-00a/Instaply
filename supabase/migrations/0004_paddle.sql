-- ─────────────────────────────────────────────────────────────────
-- Paddle billing integration — idempotent transaction ingest.
--
-- Paddle may redeliver webhooks (network glitch, their retry). We
-- MUST NOT double-credit on retries. Dedupe by paddle_transaction_id
-- with a UNIQUE constraint, then insert ledger row in same txn.
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS paddle_transactions (
  id                       UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  paddle_transaction_id    TEXT NOT NULL UNIQUE,   -- txn_*  — Paddle's id
  paddle_event_id          TEXT,                    -- evt_*  (for debug)
  user_id                  UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
  pack_id                  TEXT NOT NULL REFERENCES public.credit_packs(id),
  credits                  INTEGER NOT NULL,
  price_usd                INTEGER NOT NULL,
  status                   TEXT NOT NULL CHECK (status IN ('completed','refunded','disputed')),
  raw_payload              JSONB NOT NULL,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS paddle_transactions_user_idx
  ON paddle_transactions (user_id, created_at DESC);

ALTER TABLE paddle_transactions ENABLE ROW LEVEL SECURITY;

-- Users can read their own transactions (receipts in UI).
DROP POLICY IF EXISTS paddle_tx_own_read ON paddle_transactions;
CREATE POLICY paddle_tx_own_read ON paddle_transactions
  FOR SELECT USING (auth.uid() = user_id);

-- Only service role writes (via webhook handler).
-- No INSERT/UPDATE policy for authenticated users = implicit deny.

-- ─────────────────────────────────────────────────────────────────
-- Apply-credits RPC. Called by webhook handler in a single txn so
-- the unique constraint on paddle_transaction_id is the atomicity
-- guarantee against double-credit.
-- ─────────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION apply_paddle_topup(
  p_paddle_transaction_id TEXT,
  p_paddle_event_id       TEXT,
  p_user_id               UUID,
  p_pack_id               TEXT,
  p_credits               INTEGER,
  p_price_usd             INTEGER,
  p_raw                   JSONB
) RETURNS UUID
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_tx_id UUID;
BEGIN
  -- Insert with ON CONFLICT DO NOTHING; if we hit the unique constraint
  -- on paddle_transaction_id, the webhook was a replay — skip silently.
  INSERT INTO paddle_transactions (
    paddle_transaction_id, paddle_event_id, user_id,
    pack_id, credits, price_usd, status, raw_payload
  ) VALUES (
    p_paddle_transaction_id, p_paddle_event_id, p_user_id,
    p_pack_id, p_credits, p_price_usd, 'completed', p_raw
  )
  ON CONFLICT (paddle_transaction_id) DO NOTHING
  RETURNING id INTO v_tx_id;

  IF v_tx_id IS NULL THEN
    -- Replay — do nothing, return sentinel.
    RETURN NULL;
  END IF;

  -- First-time insert: credit the user.
  INSERT INTO credit_ledger (user_id, delta, reason, note)
  VALUES (
    p_user_id,
    p_credits,
    'paid_topup',
    format('Paddle %s — %s credits ($%s)', p_pack_id, p_credits, p_price_usd)
  );

  RETURN v_tx_id;
END;
$$;

REVOKE ALL ON FUNCTION apply_paddle_topup(TEXT, TEXT, UUID, TEXT, INTEGER, INTEGER, JSONB) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION apply_paddle_topup(TEXT, TEXT, UUID, TEXT, INTEGER, INTEGER, JSONB) TO service_role;
