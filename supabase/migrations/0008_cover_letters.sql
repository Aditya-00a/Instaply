-- ============================================================
-- 0008_cover_letters.sql
-- Private Supabase Storage bucket + mirror table for cover letter
-- uploads. Schema parallels public.resumes so the upload component
-- can share code.
-- ============================================================

create table if not exists public.cover_letters (
  id              uuid primary key default uuid_generate_v4(),
  user_id         uuid not null references public.profiles(id) on delete cascade,
  label           text not null default 'default',
  storage_path    text not null,
  file_name       text not null,
  file_size_bytes integer,
  is_primary      boolean not null default false,
  created_at      timestamptz not null default now()
);

create unique index if not exists cover_letters_one_primary_per_user
  on public.cover_letters (user_id) where is_primary = true;
create index if not exists cover_letters_user_idx on public.cover_letters (user_id);

alter table public.cover_letters enable row level security;

drop policy if exists "cover_letters: own-read"   on public.cover_letters;
drop policy if exists "cover_letters: own-insert" on public.cover_letters;
drop policy if exists "cover_letters: own-update" on public.cover_letters;
drop policy if exists "cover_letters: own-delete" on public.cover_letters;

create policy "cover_letters: own-read"   on public.cover_letters for select using (auth.uid() = user_id);
create policy "cover_letters: own-insert" on public.cover_letters for insert with check (auth.uid() = user_id);
create policy "cover_letters: own-update" on public.cover_letters for update using (auth.uid() = user_id);
create policy "cover_letters: own-delete" on public.cover_letters for delete using (auth.uid() = user_id);

-- Storage bucket
insert into storage.buckets (id, name, public)
values ('cover_letters', 'cover_letters', false)
on conflict (id) do nothing;

drop policy if exists "cover_letters: own-storage-read"   on storage.objects;
drop policy if exists "cover_letters: own-storage-insert" on storage.objects;
drop policy if exists "cover_letters: own-storage-update" on storage.objects;
drop policy if exists "cover_letters: own-storage-delete" on storage.objects;

create policy "cover_letters: own-storage-read" on storage.objects
  for select using (
    bucket_id = 'cover_letters'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy "cover_letters: own-storage-insert" on storage.objects
  for insert with check (
    bucket_id = 'cover_letters'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy "cover_letters: own-storage-update" on storage.objects
  for update using (
    bucket_id = 'cover_letters'
    and (storage.foldername(name))[1] = auth.uid()::text
  );

create policy "cover_letters: own-storage-delete" on storage.objects
  for delete using (
    bucket_id = 'cover_letters'
    and (storage.foldername(name))[1] = auth.uid()::text
  );
