-- 0012_credit_ledger_invite_code_reason.sql
-- ─────────────────────────────────────────────────────────────────
-- Fix: 0010_invite_codes.sql introduced reason='invite_code' but the
-- credit_ledger.reason CHECK in 0001 doesn't allow it, so every beta
-- code redemption silently fails (CHECK violation rolls back the entire
-- redeem_invite_code tx → user redeems code, gets zero credits).
--
-- Adding 'invite_code' to the allow-list. Idempotent.
-- ─────────────────────────────────────────────────────────────────

alter table public.credit_ledger
  drop constraint if exists credit_ledger_reason_check;

alter table public.credit_ledger
  add constraint credit_ledger_reason_check
  check (reason in (
    'signup_bonus',
    'paid_topup',
    'plan_upgrade',
    'application_confirmed',
    'refund',
    'manual_adjustment',
    'beta_grant',
    'invite_code'
  ));

-- ── Confused-deputy fix on redeem_invite_code ──────────────────────
-- redeem_invite_code is SECURITY DEFINER + GRANTed to authenticated.
-- It accepts p_user_id but never verified it matches auth.uid(),
-- meaning a malicious authenticated user could redeem a code on
-- behalf of any other user (gifting them credits). Adding the guard.

drop function if exists public.redeem_invite_code(text, uuid);

create function public.redeem_invite_code(p_code text, p_user_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_row   public.invite_codes%rowtype;
  v_count integer;
begin
  -- Confused-deputy guard: a caller can only redeem for themselves.
  if p_user_id is null or p_user_id <> auth.uid() then
    raise exception 'unauthorized: p_user_id must equal auth.uid()';
  end if;

  select * into v_row from public.invite_codes
  where code = upper(trim(p_code))
  for update;

  if not found then
    return jsonb_build_object('ok', false, 'reason', 'unknown_code');
  end if;
  if v_row.expires_at is not null and v_row.expires_at < now() then
    return jsonb_build_object('ok', false, 'reason', 'expired');
  end if;
  if v_row.max_uses is not null and v_row.times_used >= v_row.max_uses then
    return jsonb_build_object('ok', false, 'reason', 'exhausted');
  end if;

  -- Has this user already redeemed this code?
  select count(*) into v_count from public.invite_redemptions
  where code = v_row.code and user_id = p_user_id;
  if v_count > 0 then
    return jsonb_build_object('ok', false, 'reason', 'already_redeemed');
  end if;

  insert into public.invite_redemptions (code, user_id) values (v_row.code, p_user_id);
  update public.invite_codes set times_used = times_used + 1 where code = v_row.code;

  if v_row.grant_credits > 0 then
    insert into public.credit_ledger (user_id, delta, reason, note)
    values (
      p_user_id,
      v_row.grant_credits,
      'invite_code',
      coalesce('Invite code: ' || v_row.label, 'Invite code redeemed')
    );
  end if;

  return jsonb_build_object('ok', true, 'credits', v_row.grant_credits);
end
$$;

revoke all on function public.redeem_invite_code(text, uuid) from public;
grant execute on function public.redeem_invite_code(text, uuid) to authenticated;
