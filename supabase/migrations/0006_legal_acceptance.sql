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
