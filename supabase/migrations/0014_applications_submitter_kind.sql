-- 0014_applications_submitter_kind.sql
-- ─────────────────────────────────────────────────────────────────
-- Add `submitter_kind` to `applications` so we can tell which
-- submission path filed each row. Critical telemetry for the
-- hybrid rollout (Instaply-native worker vs. legacy Revize-imported
-- submitter vs. browser extension), and a hard prerequisite for
-- safely deploying the Instaply worker behind a feature flag.
--
-- Defaulting existing rows to 'server_revize' is intentional: every
-- application already in the DB was filed by the legacy submitter at
-- C:/Ravendise/Revize/cloud_submitter.py. New writes will tag
-- 'server_instaply' (or 'extension' when that ships).
--
-- Idempotent: safe to re-run.
-- ─────────────────────────────────────────────────────────────────

alter table public.applications
  add column if not exists submitter_kind text not null default 'server_revize';

-- CHECK constraint enforces a closed allow-list. Adding via DROP+ADD
-- so re-running this migration after editing the allow-list is safe.
alter table public.applications
  drop constraint if exists applications_submitter_kind_check;

alter table public.applications
  add constraint applications_submitter_kind_check
  check (submitter_kind in (
    'server_revize',     -- legacy C:/Ravendise/Revize cloud_submitter.py path
    'server_instaply',   -- new Instaply-native worker (worker/orchestrator.py)
    'extension',         -- future Chrome extension client
    'manual'             -- ops-issued / backfill
  ));

-- Operational index: per-kind throughput and success-rate dashboards
-- will routinely filter by submitter_kind. Keep the existing
-- (status, queued_at) index in 0001_init.sql; this is additive.
create index if not exists applications_submitter_kind_status_idx
  on public.applications (submitter_kind, status);
