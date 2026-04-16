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
