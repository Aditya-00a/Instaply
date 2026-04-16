-- ─── Ravendise / Instaply — consume_credit RPC ────────────────────
-- Called by the cloud submitter worker after a successful submission.
-- Atomically deducts 1 credit and marks the application confirmed.
-- Idempotent: if the application is already confirmed, no-ops silently.
--
-- Returns: 'ok' | 'already_confirmed' | 'insufficient_credits'

CREATE OR REPLACE FUNCTION public.consume_credit(
  p_user_id       UUID,
  p_application_id UUID
)
RETURNS TEXT
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_current_status TEXT;
  v_balance        INTEGER;
BEGIN
  -- Lock the application row to prevent races
  SELECT status INTO v_current_status
    FROM public.applications
   WHERE id = p_application_id AND user_id = p_user_id
   FOR UPDATE;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'Application % not found for user %', p_application_id, p_user_id;
  END IF;

  -- Idempotency: already confirmed → skip silently
  IF v_current_status = 'confirmed' THEN
    RETURN 'already_confirmed';
  END IF;

  -- Credit gate
  v_balance := public.get_credit_balance(p_user_id);
  IF v_balance <= 0 THEN
    -- Don't block submission logging, but don't deduct negative credits
    RETURN 'insufficient_credits';
  END IF;

  -- Deduct 1 credit
  INSERT INTO public.credit_ledger (user_id, delta, reason, application_id, note)
  VALUES (p_user_id, -1, 'application_confirmed', p_application_id, 'Application submitted via Instaply');

  -- Mark confirmed
  UPDATE public.applications
     SET status       = 'confirmed',
         confirmed_at = NOW()
   WHERE id = p_application_id;

  RETURN 'ok';
END;
$$;

-- Only the service role (workers) may call this. Never the anon key.
REVOKE ALL ON FUNCTION public.consume_credit(UUID, UUID) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.consume_credit(UUID, UUID) TO service_role;
