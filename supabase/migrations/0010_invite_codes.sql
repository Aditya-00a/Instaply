-- ============================================================
-- 0010_invite_codes.sql
-- Closed-beta access control + tester credit grants.
-- Each invite code grants the redeemer N credits on success
-- (default 1000 for the closed beta).
-- ============================================================

create table if not exists public.invite_codes (
  code           text primary key,
  label          text,                       -- e.g. "beta-batch-1", or a tester's name
  max_uses       integer not null default 1,
  uses           integer not null default 0,
  grant_credits  integer not null default 1000,  -- credits granted on redeem
  expires_at     timestamptz,                -- null = no expiry
  created_at     timestamptz not null default now(),
  created_by     uuid references auth.users(id) on delete set null,
  notes          text
);

create index if not exists invite_codes_expires_idx
  on public.invite_codes (expires_at) where expires_at is not null;

-- Track which user redeemed which code (for audit + revoke).
create table if not exists public.invite_redemptions (
  code        text not null references public.invite_codes(code) on delete cascade,
  user_id     uuid not null references auth.users(id) on delete cascade,
  redeemed_at timestamptz not null default now(),
  primary key (code, user_id)
);

create index if not exists invite_redemptions_user_idx
  on public.invite_redemptions (user_id);

-- Atomic redeem RPC: validates + increments + grants credits + records,
-- all in one transaction. Returns true on success, false otherwise.
create or replace function public.redeem_invite_code(p_code text, p_user_id uuid)
returns boolean
language plpgsql
security definer
set search_path = public
as $$
declare
  v_row public.invite_codes;
begin
  -- Lock the row to prevent races
  select * into v_row
    from public.invite_codes
   where code = p_code
   for update;

  if not found then
    return false;
  end if;

  if v_row.expires_at is not null and v_row.expires_at < now() then
    return false;
  end if;

  if v_row.uses >= v_row.max_uses then
    return false;
  end if;

  -- Idempotent: a user can't redeem the same code twice.
  if exists (
    select 1 from public.invite_redemptions
    where code = p_code and user_id = p_user_id
  ) then
    return false;
  end if;

  update public.invite_codes
     set uses = uses + 1
   where code = p_code;

  insert into public.invite_redemptions (code, user_id)
  values (p_code, p_user_id);

  -- Grant credits on the ledger if the code carries a positive grant.
  if v_row.grant_credits > 0 then
    insert into public.credit_ledger (user_id, delta, reason, note)
    values (
      p_user_id,
      v_row.grant_credits,
      'invite_code',
      coalesce('Invite code: ' || v_row.label, 'Invite code redeemed')
    );
  end if;

  return true;
end;
$$;

-- Helper: validate without redeeming (for client-side pre-check)
create or replace function public.invite_code_is_valid(p_code text)
returns boolean
language sql
stable
as $$
  select case
    when not exists (select 1 from public.invite_codes where code = p_code) then false
    when exists (
      select 1 from public.invite_codes
      where code = p_code
        and expires_at is not null and expires_at < now()
    ) then false
    when exists (
      select 1 from public.invite_codes
      where code = p_code and uses >= max_uses
    ) then false
    else true
  end;
$$;

grant execute on function public.redeem_invite_code(text, uuid) to authenticated;
grant execute on function public.invite_code_is_valid(text) to anon, authenticated;

-- RLS: invite_codes are admin-managed, redemptions are user-readable
alter table public.invite_codes enable row level security;
alter table public.invite_redemptions enable row level security;

drop policy if exists "invite_codes: own-redemptions-read" on public.invite_redemptions;
create policy "invite_codes: own-redemptions-read" on public.invite_redemptions
  for select using (auth.uid() = user_id);

-- ============================================================
-- HELPER: generate N random codes. Run from SQL Editor when you need
-- a batch of codes to send to testers.
--
-- select * from public.mint_invite_codes(
--   p_count       => 20,
--   p_label       => 'beta-batch-1',
--   p_max_uses    => 1,
--   p_grant_credits => 1000,
--   p_expires_at  => null
-- );
--
-- Returns the generated codes — copy them and share with testers.
-- ============================================================
create or replace function public.mint_invite_codes(
  p_count int,
  p_label text default null,
  p_max_uses int default 1,
  p_grant_credits int default 1000,
  p_expires_at timestamptz default null
)
returns setof text
language plpgsql
security definer
set search_path = public
as $$
declare
  v_code text;
  v_chars text := 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  i int;
  j int;
begin
  for i in 1..p_count loop
    v_code := '';
    for j in 1..8 loop
      v_code := v_code || substr(v_chars, 1 + floor(random() * length(v_chars))::int, 1);
    end loop;

    insert into public.invite_codes
      (code, label, max_uses, grant_credits, expires_at)
    values
      (v_code, p_label, p_max_uses, p_grant_credits, p_expires_at)
    on conflict (code) do nothing;

    return next v_code;
  end loop;
end;
$$;

comment on table public.invite_codes is
  'Closed-beta access codes. Set NEXT_PUBLIC_INVITE_REQUIRED=true on the web to enforce on signup.';
