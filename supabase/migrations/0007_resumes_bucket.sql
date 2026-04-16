-- ============================================================
-- 0007_resumes_bucket.sql
-- Private Supabase Storage bucket for user resume uploads, plus
-- storage-level RLS so every user sees only their own files.
--
-- The path convention is `<user_id>/<timestamp>-<filename>` — policies
-- enforce that the first path segment matches auth.uid().
-- ============================================================

-- Create the bucket if it doesn't exist. Private by default.
insert into storage.buckets (id, name, public)
values ('resumes', 'resumes', false)
on conflict (id) do nothing;

-- Drop prior versions (idempotent redeploy)
drop policy if exists "resumes: own-read"     on storage.objects;
drop policy if exists "resumes: own-insert"   on storage.objects;
drop policy if exists "resumes: own-update"   on storage.objects;
drop policy if exists "resumes: own-delete"   on storage.objects;

-- Each user can only read/write files under a folder named by their uid.
create policy "resumes: own-read" on storage.objects
  for select
  using (
    bucket_id = 'resumes'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy "resumes: own-insert" on storage.objects
  for insert
  with check (
    bucket_id = 'resumes'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy "resumes: own-update" on storage.objects
  for update
  using (
    bucket_id = 'resumes'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy "resumes: own-delete" on storage.objects
  for delete
  using (
    bucket_id = 'resumes'
    and (storage.foldername(name))[1] = auth.uid()::text
  );
