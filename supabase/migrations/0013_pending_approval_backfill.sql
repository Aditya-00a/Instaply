-- 0013_pending_approval_backfill.sql
-- ─────────────────────────────────────────────────────────────────
-- Backfill the pending_approval table that was created out-of-band
-- in production but never captured in a migration. Mirrors the live
-- shape so a fresh `supabase db reset` produces an identical schema.
--
-- Also adds a CHECK constraint on status that the live table is
-- missing — code writes 'pending', 'approved', 'skipped' but nothing
-- prevents a stray value from sneaking in.
-- ─────────────────────────────────────────────────────────────────

create table if not exists public.pending_approval (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references auth.users(id) on delete cascade,
  job_id        uuid not null references public.jobs(id) on delete cascade,
  match_score   integer not null default 0,
  match_reasons jsonb default '{}'::jsonb,
  status        text not null default 'pending',
  found_at      timestamptz not null default now(),
  decided_at    timestamptz,
  expires_at    timestamptz not null default (now() + interval '7 days'),
  unique (user_id, job_id)
);

-- Enforce the only legal status values. Idempotent.
alter table public.pending_approval
  drop constraint if exists pending_approval_status_check;
alter table public.pending_approval
  add constraint pending_approval_status_check
  check (status in ('pending', 'approved', 'skipped', 'expired'));

create index if not exists pending_approval_user_status_idx
  on public.pending_approval (user_id, status, found_at desc);

-- Row-level security: users see + decide on their own rows. Inserts
-- happen only via service_role (the discovery worker), so no INSERT
-- policy is intentionally created.
alter table public.pending_approval enable row level security;

drop policy if exists "Users see their own pending" on public.pending_approval;
create policy "Users see their own pending"
  on public.pending_approval for select
  using (auth.uid() = user_id);

drop policy if exists "Users update their own pending" on public.pending_approval;
create policy "Users update their own pending"
  on public.pending_approval for update
  using (auth.uid() = user_id)
  with check (auth.uid() = user_id);

-- ─────────────────────────────────────────────────────────────────
-- Also backfill preferences.seniority + auto_apply_* columns that
-- got added out-of-band. Migration is idempotent (IF NOT EXISTS).
-- ─────────────────────────────────────────────────────────────────

alter table public.preferences
  add column if not exists seniority text default 'any';

alter table public.preferences
  drop constraint if exists preferences_seniority_check;
alter table public.preferences
  add constraint preferences_seniority_check
  check (seniority in ('entry', 'mid', 'senior', 'staff_plus', 'any'));

alter table public.preferences
  add column if not exists auto_apply_enabled boolean default false,
  add column if not exists auto_apply_min_match integer default 70,
  add column if not exists auto_apply_keywords text[] default '{}',
  add column if not exists auto_apply_quiet_start text default '23:00',
  add column if not exists auto_apply_quiet_end text default '08:00',
  add column if not exists auto_apply_paused_until timestamptz,
  add column if not exists auto_apply_last_run_at timestamptz,
  add column if not exists auto_apply_daily_cap integer default 5;

-- profiles.extracted_skills (resume parser output)
alter table public.profiles
  add column if not exists extracted_skills jsonb default '{}'::jsonb;
