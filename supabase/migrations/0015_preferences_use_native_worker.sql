-- 0015_preferences_use_native_worker.sql
-- ─────────────────────────────────────────────────────────────────
-- Per-user feature flag that gates which submitter claims a user's
-- queued applications:
--   FALSE → legacy Revize-imported submitter (`instaply-submitter` Fly app,
--           runs `C:/Ravendise/Revize/cloud_submitter.py`)
--   TRUE  → new Instaply-native worker (`instaply-worker` Fly app,
--           runs `C:/Ravendise/Instaply/worker/orchestrator.py`)
--
-- The Instaply worker reads this flag every cycle and claims only
-- applications belonging to opted-in users (see `_claim_one` in
-- worker/orchestrator.py). The legacy Revize submitter does NOT read
-- this flag — it claims any `status='queued'` row, which is acceptable
-- during canary because:
--
--   1. The native worker uses a single-statement UPDATE filter
--      (status='queued' AND user_id IN opted_in) so its claim is
--      atomic against any other contender.
--   2. If both submitters race for the same canary row, whichever
--      issues its PATCH first wins; the other's filter no longer matches.
--   3. The recommended canary procedure is to briefly suspend the
--      legacy submitter (`flyctl scale count 0 -a instaply-submitter`)
--      while verifying the first opted-in user, then resume.
--
-- Idempotent. NOT NULL with default so the worker never has to handle
-- a null flag value.
-- ─────────────────────────────────────────────────────────────────

alter table public.preferences
  add column if not exists use_native_worker boolean not null default false;

-- Partial index only on the TRUE side keeps the index small (most users
-- will be FALSE). The worker queries this every cache refresh
-- (60s default), so a tiny index is preferable to a full one.
create index if not exists preferences_use_native_worker_true_idx
  on public.preferences (user_id) where use_native_worker = true;
