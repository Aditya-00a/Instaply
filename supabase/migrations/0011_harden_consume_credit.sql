-- ─── Harden consume_credit: only deduct on email confirmation ──────
--
-- The submitter marks status='submitted'. Credits are ONLY deducted
-- when the email verifier confirms the employer acknowledgement email
-- arrived. This function now REJECTS calls unless the application is
-- in 'submitted' status — preventing double-deduction and premature
-- charging.
--
-- This is the financial integrity gate for "$1 per confirmed application."

CREATE OR REPLACE FUNCTION public.consume_credit(
  p_user_id        UUID,
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

  -- GUARD: Only allow credit consumption from 'submitted' status.
  -- This prevents premature deduction from 'queued', 'in_progress',
  -- 'failed', or 'needs_review' states.
  IF v_current_status <> 'submitted' THEN
    RETURN 'not_submitted';
  END IF;

  -- Credit gate
  v_balance := public.get_credit_balance(p_user_id);
  IF v_balance <= 0 THEN
    RETURN 'insufficient_credits';
  END IF;

  -- Deduct 1 credit
  INSERT INTO public.credit_ledger (user_id, delta, reason, application_id, note)
  VALUES (p_user_id, -1, 'application_confirmed', p_application_id, 'Application confirmed via email');

  -- Mark confirmed with timestamp
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
