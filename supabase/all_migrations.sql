-- ============================================================
-- Instaply / Ravendise — full bootstrap migration
-- Run this once in the Supabase SQL Editor on a fresh project.
-- Idempotent: safe to re-run; uses IF NOT EXISTS / OR REPLACE.
-- Order matters: 0001 → 0002 → 0003 → 0004 → 0005 → 0006 → 0007
-- ============================================================

-- ============================================================
-- 0001_init.sql
-- ============================================================
-- ============================================================
-- Ravendise / Instaply — initial schema
-- Multi-tenant. Row-level security everywhere. Credit ledger is append-only.
-- ============================================================

-- Extensions
create extension if not exists "uuid-ossp";
create extension if not exists "pgcrypto";
create extension if not exists "pg_trgm";  -- for fuzzy search on job titles

-- ============================================================
-- profiles: one row per user. Extends auth.users.
-- ============================================================
create table public.profiles (
  id                uuid primary key references auth.users(id) on delete cascade,
  email             text not null unique,
  full_name         text,
  phone             text,
  linkedin_url      text,
  github_url        text,
  website_url       text,

  -- Work authorization & visa (drives EEO autofill + filtering)
  work_auth_status  text check (work_auth_status in (
    'us_citizen','green_card','h1b','f1_opt','f1_cpt','other'
  )),
  needs_sponsorship boolean not null default false,
  willing_to_relocate boolean not null default true,

  -- Location
  current_city      text,
  current_state     text,
  current_country   text default 'US',
  zip_code          text,

  -- Demographics (for EEO — optional, encrypted at rest via Supabase vault ideally)
  gender            text,
  race              text,
  hispanic_ethnicity boolean,
  veteran_status    text,
  disability_status text,

  -- Plan
  plan              text not null default 'free' check (plan in ('free','pro','paused')),
  stripe_customer_id text,  -- reserved (future)
  paddle_customer_id text,

  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index on public.profiles (email);
create index on public.profiles (plan);

-- ============================================================
-- resumes: uploaded resume files + parsed profile data
-- ============================================================
create table public.resumes (
  id              uuid primary key default uuid_generate_v4(),
  user_id         uuid not null references public.profiles(id) on delete cascade,
  label           text not null default 'default',
  storage_path    text not null,           -- Supabase storage URI
  file_name       text not null,
  file_size_bytes integer,
  parsed_json     jsonb,                   -- structured resume (education, experience, skills)
  is_primary      boolean not null default false,
  created_at      timestamptz not null default now()
);

create unique index resumes_one_primary_per_user on public.resumes (user_id) where is_primary = true;
create index on public.resumes (user_id);

-- ============================================================
-- preferences: job search criteria
-- ============================================================
create table public.preferences (
  user_id            uuid primary key references public.profiles(id) on delete cascade,
  target_titles      text[] not null default '{}',      -- ["Software Engineer", "ML Engineer"]
  target_locations   text[] not null default '{}',
  remote_ok          boolean not null default true,
  salary_min_usd     integer,
  industries         text[] default '{}',
  excluded_companies text[] default '{}',
  fit_threshold      numeric(3,2) not null default 0.65,  -- 0.00 - 1.00
  per_company_cap    integer not null default 4,
  updated_at         timestamptz not null default now()
);

-- ============================================================
-- jobs: discovered postings (shared across users, deduped by source+external_id)
-- ============================================================
create table public.jobs (
  id              uuid primary key default uuid_generate_v4(),
  source          text not null check (source in (
    'greenhouse','lever','smartrecruiters','workday','ashby','icims','manual'
  )),
  external_id     text not null,
  company_slug    text not null,
  company_name    text not null,
  title           text not null,
  location        text,
  remote          boolean default false,
  description     text,
  apply_url       text not null,
  posted_at       timestamptz,
  discovered_at   timestamptz not null default now(),
  is_active       boolean not null default true,

  unique (source, external_id)
);

create index on public.jobs (company_slug);
create index on public.jobs (source);
create index on public.jobs using gin (title gin_trgm_ops);
create index on public.jobs (discovered_at desc);

-- ============================================================
-- applications: one row per user × job submission attempt
-- ============================================================
create table public.applications (
  id              uuid primary key default uuid_generate_v4(),
  user_id         uuid not null references public.profiles(id) on delete cascade,
  job_id          uuid not null references public.jobs(id),

  status          text not null default 'queued' check (status in (
    'queued','in_progress','submitted','confirmed','failed','needs_review','skipped'
  )),
  fit_score       numeric(3,2),

  -- Artifacts
  resume_id       uuid references public.resumes(id),
  cover_letter    text,
  submission_log  jsonb,                   -- step-by-step autofill trace
  screenshot_url  text,

  -- Verification (no credit decrement until confirmed)
  confirmation_email_id text,              -- Gmail msg id when matched
  confirmed_at    timestamptz,

  error_message   text,
  queued_at       timestamptz not null default now(),
  started_at      timestamptz,
  completed_at    timestamptz,

  unique (user_id, job_id)
);

create index on public.applications (user_id, status);
create index on public.applications (job_id);
create index on public.applications (status, queued_at);

-- ============================================================
-- credit_ledger: append-only. True balance = sum of deltas.
-- Never UPDATE. Never DELETE. Only INSERT.
-- ============================================================
create table public.credit_ledger (
  id              uuid primary key default uuid_generate_v4(),
  user_id         uuid not null references public.profiles(id) on delete cascade,
  delta           integer not null,                     -- +10 on signup, -1 per confirmed app
  reason          text not null check (reason in (
    'signup_bonus','paid_topup','plan_upgrade','application_confirmed',
    'refund','manual_adjustment','beta_grant'
  )),
  application_id  uuid references public.applications(id),
  note            text,
  created_at      timestamptz not null default now()
);

create index on public.credit_ledger (user_id, created_at desc);

-- Materialized view for fast balance lookups (refresh on every insert via trigger)
create or replace function public.get_credit_balance(p_user_id uuid)
returns integer
language sql
stable
as $$
  select coalesce(sum(delta), 0)::int
  from public.credit_ledger
  where user_id = p_user_id;
$$;

-- ============================================================
-- answers: user-specific responses to free-text questions
-- (e.g. "Why do you want to work here?")
-- Reused across applications to the same employer.
-- ============================================================
create table public.answers (
  id             uuid primary key default uuid_generate_v4(),
  user_id        uuid not null references public.profiles(id) on delete cascade,
  question_hash  text not null,           -- sha256(normalized(question))
  question_text  text not null,
  answer_text    text not null,
  company_slug   text,                    -- null = global; populated = company-specific
  times_used     integer not null default 0,
  last_used_at   timestamptz,
  created_at     timestamptz not null default now(),

  unique (user_id, question_hash, company_slug)
);

create index on public.answers (user_id, question_hash);

-- ============================================================
-- Triggers
-- ============================================================

-- Auto-grant 10 free credits on profile creation
create or replace function public.grant_signup_bonus()
returns trigger
language plpgsql
security definer
as $$
begin
  insert into public.credit_ledger (user_id, delta, reason, note)
  values (new.id, 10, 'signup_bonus', 'Welcome to Instaply — 10 free applications');
  return new;
end;
$$;

drop trigger if exists on_profile_created on public.profiles;
create trigger on_profile_created
  after insert on public.profiles
  for each row execute function public.grant_signup_bonus();

-- Touch updated_at on profile edits
create or replace function public.touch_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end;
$$;

create trigger profiles_touch
  before update on public.profiles
  for each row execute function public.touch_updated_at();

create trigger preferences_touch
  before update on public.preferences
  for each row execute function public.touch_updated_at();

-- Auto-decrement credits when application status -> confirmed
create or replace function public.decrement_on_confirm()
returns trigger
language plpgsql
security definer
as $$
begin
  if new.status = 'confirmed' and (old.status is null or old.status <> 'confirmed') then
    -- Check balance before decrementing (defensive; worker should pre-check)
    if public.get_credit_balance(new.user_id) <= 0 then
      raise exception 'Insufficient credits for user %', new.user_id;
    end if;
    insert into public.credit_ledger (user_id, delta, reason, application_id, note)
    values (new.user_id, -1, 'application_confirmed', new.id, 'Application confirmed via email');
    new.confirmed_at = now();
  end if;
  return new;
end;
$$;

create trigger applications_confirm_decrement
  before update on public.applications
  for each row execute function public.decrement_on_confirm();

-- ============================================================
-- Row-Level Security
-- ============================================================
alter table public.profiles       enable row level security;
alter table public.resumes        enable row level security;
alter table public.preferences    enable row level security;
alter table public.applications   enable row level security;
alter table public.credit_ledger  enable row level security;
alter table public.answers        enable row level security;
-- jobs: intentionally NOT RLS-protected (shared catalog, read-only to authed users)
alter table public.jobs           enable row level security;

-- Everyone sees their own rows
create policy "own profile"      on public.profiles      for all using (auth.uid() = id);
create policy "own resumes"      on public.resumes       for all using (auth.uid() = user_id);
create policy "own preferences"  on public.preferences   for all using (auth.uid() = user_id);
create policy "own applications" on public.applications  for all using (auth.uid() = user_id);
create policy "own ledger read"  on public.credit_ledger for select using (auth.uid() = user_id);
create policy "own answers"      on public.answers       for all using (auth.uid() = user_id);

-- Jobs: all authed users read; only service role writes
create policy "jobs read" on public.jobs for select using (auth.role() = 'authenticated');

-- Ledger: only service role can write (prevents client-side credit manipulation)
-- (no policy = denied for anon/authed; service role bypasses RLS)

-- ============================================================
-- Grants
-- ============================================================
grant usage on schema public to anon, authenticated, service_role;
grant select on public.jobs to authenticated;
grant all on all tables in schema public to service_role;

-- ============================================================
-- Done.
-- Apply with: supabase db push  (or paste into SQL editor)
-- ============================================================

-- ============================================================
-- 0002_pricing.sql
-- ============================================================
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

-- ============================================================
-- 0003_mcp_tokens.sql
-- ============================================================
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

-- ============================================================
-- 0004_paddle.sql
-- ============================================================
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

-- ============================================================
-- 0005_audit_log.sql
-- ============================================================
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

-- ============================================================
-- 0006_legal_acceptance.sql
-- ============================================================
-- ============================================================
-- 0006_legal_acceptance.sql
-- Track each user's acceptance of Terms, Privacy, and Refund
-- policies at signup. Required for DPDP Act / GDPR compliance
-- and Paddle merchant-of-record review.
-- ============================================================

alter table public.profiles
  add column if not exists legal_accepted_at        timestamptz,
  add column if not exists legal_accepted_ip_hash   text,
  add column if not exists legal_accepted_version   text;

comment on column public.profiles.legal_accepted_at is
  'UTC timestamp when the user accepted Terms, Privacy, and Refund policies. Null = pre-acceptance-flow user.';
comment on column public.profiles.legal_accepted_ip_hash is
  'Salted sha256 of the client IP at acceptance time. Never store raw IP.';
comment on column public.profiles.legal_accepted_version is
  'Version string of the policy bundle the user accepted (e.g. "2026-04-14").';

-- Trigger: when a new auth.users row lands, create a profile stub so
-- the app can rely on profiles row existing immediately after signup.
-- The legal_* columns are populated by the sign-up code path.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, email)
  values (new.id, new.email)
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ============================================================
-- 0007_resumes_bucket.sql
-- ============================================================
-- ============================================================
-- 0007_resumes_bucket.sql
-- Private Supabase Storage bucket for user resume uploads, plus
-- storage-level RLS so every user sees only their own files.
--
-- The path convention is `<user_id>/<timestamp>-<filename>` — policies
-- enforce that the first path segment matches auth.uid().
-- ============================================================

-- Create the bucket if it doesn't exist. Private by default.
insert into storage.buckets (id, name, public)
values ('resumes', 'resumes', false)
on conflict (id) do nothing;

-- Drop prior versions (idempotent redeploy)
drop policy if exists "resumes: own-read"     on storage.objects;
drop policy if exists "resumes: own-insert"   on storage.objects;
drop policy if exists "resumes: own-update"   on storage.objects;
drop policy if exists "resumes: own-delete"   on storage.objects;

-- Each user can only read/write files under a folder named by their uid.
create policy "resumes: own-read" on storage.objects
  for select
  using (
    bucket_id = 'resumes'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy "resumes: own-insert" on storage.objects
  for insert
  with check (
    bucket_id = 'resumes'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy "resumes: own-update" on storage.objects
  for update
  using (
    bucket_id = 'resumes'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy "resumes: own-delete" on storage.objects
  for delete
  using (
    bucket_id = 'resumes'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

