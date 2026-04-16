-- ─── Ravendise / Instaply — pricing & credit-pack adjustments ─────
-- Free credits: 10 → 3.  Adds credit-pack table + top-up minimum guard.
-- Safe to re-run (IF EXISTS / IF NOT EXISTS used throughout).

-- 1. Replace signup bonus trigger (10 → 3) ─────────────────────────
CREATE OR REPLACE FUNCTION grant_signup_bonus()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  INSERT INTO credit_ledger (user_id, delta, reason, note)
  VALUES (NEW.id, 3, 'signup_bonus', 'Welcome to Instaply — 3 free applications on us');
  RETURN NEW;
END;
$$;

-- 2. Credit packs catalog (immutable pricing ledger) ───────────────
CREATE TABLE IF NOT EXISTS credit_packs (
  id           TEXT PRIMARY KEY,              -- 'starter' | 'plus' | 'pro'
  label        TEXT NOT NULL,
  price_usd    INTEGER NOT NULL,              -- whole dollars
  credits      INTEGER NOT NULL,
  bonus_pct    INTEGER NOT NULL DEFAULT 0,
  is_active    BOOLEAN NOT NULL DEFAULT TRUE,
  sort_order   INTEGER NOT NULL DEFAULT 0,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO credit_packs (id, label, price_usd, credits, bonus_pct, sort_order) VALUES
  ('starter', 'Starter',  10, 10,  0, 1),
  ('plus',    'Plus',     25, 30, 17, 2),
  ('pro',     'Pro',      50, 70, 40, 3)
ON CONFLICT (id) DO UPDATE
  SET label      = EXCLUDED.label,
      price_usd  = EXCLUDED.price_usd,
      credits    = EXCLUDED.credits,
      bonus_pct  = EXCLUDED.bonus_pct,
      sort_order = EXCLUDED.sort_order,
      is_active  = TRUE;

-- 3. Enforce minimum top-up at ledger level (defense-in-depth) ─────
-- Paid top-ups must be from a known pack; ad-hoc amounts rejected.
CREATE OR REPLACE FUNCTION enforce_paid_topup_minimum()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  IF NEW.reason = 'paid_topup' AND NEW.delta < 10 THEN
    RAISE EXCEPTION 'Paid top-ups must be >= 10 credits (minimum $10 pack). Got: %', NEW.delta;
  END IF;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_enforce_paid_topup_minimum ON credit_ledger;
CREATE TRIGGER trg_enforce_paid_topup_minimum
  BEFORE INSERT ON credit_ledger
  FOR EACH ROW EXECUTE FUNCTION enforce_paid_topup_minimum();

-- 4. User prefs: review-before-send + model tier ──────────────────
ALTER TABLE preferences
  ADD COLUMN IF NOT EXISTS review_before_send BOOLEAN NOT NULL DEFAULT TRUE,
  ADD COLUMN IF NOT EXISTS model_tier TEXT NOT NULL DEFAULT 'standard'
    CHECK (model_tier IN ('standard', 'premium')),
  ADD COLUMN IF NOT EXISTS workday_enabled BOOLEAN NOT NULL DEFAULT FALSE;

-- 5. Anti-abuse: fingerprint duplicate-free-signup attempts ──────
-- We store a normalised email key + hashed device/network signals
-- so the same person can't harvest 3×N free credits via aliases.
CREATE TABLE IF NOT EXISTS signup_fingerprints (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  email_normalised  TEXT NOT NULL,                   -- lowercase, Gmail dot/+-stripped
  email_domain      TEXT NOT NULL,
  ip_hash           TEXT,                            -- sha256(ip + daily_salt)
  device_hash       TEXT,                            -- sha256(fp.js signals)
  phone_e164        TEXT,                            -- optional SMS verification
  is_disposable     BOOLEAN NOT NULL DEFAULT FALSE,  -- flagged against blocklist
  suspicion_score   INTEGER NOT NULL DEFAULT 0,      -- 0..100
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS signup_fp_user_unique
  ON signup_fingerprints (user_id);
CREATE INDEX IF NOT EXISTS signup_fp_email_normalised
  ON signup_fingerprints (email_normalised);
CREATE INDEX IF NOT EXISTS signup_fp_device_hash
  ON signup_fingerprints (device_hash) WHERE device_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS signup_fp_phone
  ON signup_fingerprints (phone_e164) WHERE phone_e164 IS NOT NULL;

-- Disposable / alias email domain blocklist (seed with common offenders).
CREATE TABLE IF NOT EXISTS blocked_email_domains (
  domain      TEXT PRIMARY KEY,
  reason      TEXT NOT NULL DEFAULT 'disposable',
  added_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO blocked_email_domains (domain, reason) VALUES
  ('mailinator.com',     'disposable'),
  ('guerrillamail.com',  'disposable'),
  ('guerrillamail.info', 'disposable'),
  ('tempmail.com',       'disposable'),
  ('temp-mail.org',      'disposable'),
  ('10minutemail.com',   'disposable'),
  ('yopmail.com',        'disposable'),
  ('trashmail.com',      'disposable'),
  ('sharklasers.com',    'disposable'),
  ('throwawaymail.com',  'disposable'),
  ('dispostable.com',    'disposable'),
  ('getnada.com',        'disposable'),
  ('maildrop.cc',        'disposable'),
  ('fakeinbox.com',      'disposable'),
  ('moakt.com',          'disposable')
ON CONFLICT (domain) DO NOTHING;

-- Guard the signup-bonus trigger: only grant if fingerprint is clean.
-- We re-bind the trigger to honour this gate.
CREATE OR REPLACE FUNCTION grant_signup_bonus()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_email       TEXT;
  v_normalised  TEXT;
  v_domain      TEXT;
  v_is_blocked  BOOLEAN;
  v_dup_count   INTEGER;
BEGIN
  -- Pull email from auth.users (created before profile insert).
  SELECT LOWER(email) INTO v_email FROM auth.users WHERE id = NEW.id;
  IF v_email IS NULL THEN
    RETURN NEW;  -- cannot evaluate; skip bonus silently
  END IF;

  v_domain := split_part(v_email, '@', 2);

  -- Normalise: strip '+tag' and (for gmail) dots in local-part.
  v_normalised := split_part(v_email, '+', 1);
  IF v_domain IN ('gmail.com', 'googlemail.com') THEN
    v_normalised := replace(split_part(v_normalised, '@', 1), '.', '') || '@gmail.com';
  END IF;

  -- Blocked domain?
  SELECT EXISTS (SELECT 1 FROM blocked_email_domains WHERE domain = v_domain)
    INTO v_is_blocked;

  -- Duplicate normalised-email across existing users?
  SELECT COUNT(*) INTO v_dup_count
    FROM signup_fingerprints
    WHERE email_normalised = v_normalised;

  -- Record fingerprint regardless (audit trail).
  INSERT INTO signup_fingerprints (user_id, email_normalised, email_domain, is_disposable, suspicion_score)
  VALUES (
    NEW.id, v_normalised, v_domain, v_is_blocked,
    (CASE WHEN v_is_blocked THEN 80 ELSE 0 END) + (v_dup_count * 40)
  );

  -- Only grant bonus if clean.  Otherwise account exists but starts at 0 credits.
  IF v_is_blocked OR v_dup_count > 0 THEN
    RETURN NEW;
  END IF;

  INSERT INTO credit_ledger (user_id, delta, reason, note)
  VALUES (NEW.id, 3, 'signup_bonus', 'Welcome to Instaply — 3 free applications on us');
  RETURN NEW;
END;
$$;

ALTER TABLE signup_fingerprints ENABLE ROW LEVEL SECURITY;
-- no policies = service role only; users cannot read each other's fingerprints.

-- 6. Public read of credit packs (no auth needed for pricing page) ─
ALTER TABLE credit_packs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS credit_packs_public_read ON credit_packs;
CREATE POLICY credit_packs_public_read ON credit_packs
  FOR SELECT USING (is_active = TRUE);
