-- 0016_profiles_pronouns.sql
-- ─────────────────────────────────────────────────────────────────
-- Add a dedicated `pronouns` field to profiles.
--
-- Why: ATSes (especially Lever) render pronouns as a multi-checkbox
-- block. Without an explicit profile field the worker's LLM stage
-- hallucinates answers like "Sowmya Deshpande" for "Ze/hir". The
-- correct behaviour is to auto-fill ONLY when the user has explicitly
-- chosen pronouns; otherwise escalate to needs_review.
--
-- IMPORTANT: pronouns must NOT be inferred from gender. Different
-- fields, different semantics. A "she" gender does not imply "she/her"
-- pronouns; users may use any combination.
--
-- Nullable so existing users aren't forced to re-onboard. Free-form
-- text so users can type custom pronouns ("ze/zir", "fae/faer", etc.).
-- A "Prefer not to say" UX choice maps to NULL — same as not setting
-- the field at all, which preserves the auto-escalate-to-review
-- behaviour the worker depends on.
--
-- Idempotent.
-- ─────────────────────────────────────────────────────────────────

alter table public.profiles
  add column if not exists pronouns text;

-- No index — this column is read once per application run inside
-- _load_profile (already a single-row lookup by primary key id).
