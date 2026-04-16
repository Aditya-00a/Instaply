-- ============================================================
-- 0009_search_quota.sql
-- Track daily job-search usage per user. Free tier = 10 searches / day.
-- Resets every UTC midnight via natural key on date.
-- ============================================================

create table if not exists public.search_usage (
  user_id  uuid not null references public.profiles(id) on delete cascade,
  day      date not null default (now() at time zone 'utc')::date,
  count    integer not null default 0,
  primary key (user_id, day)
);

create index if not exists search_usage_user_day
  on public.search_usage (user_id, day desc);

alter table public.search_usage enable row level security;

drop policy if exists "search_usage: own-read" on public.search_usage;
create policy "search_usage: own-read"
  on public.search_usage for select
  using (auth.uid() = user_id);

-- Increment counter; return new count. Used by the search endpoint.
-- Service-definer so callers don't need direct write permission.
create or replace function public.increment_search_count(p_user_id uuid)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  v_today date := (now() at time zone 'utc')::date;
  v_count integer;
begin
  insert into public.search_usage (user_id, day, count)
  values (p_user_id, v_today, 1)
  on conflict (user_id, day)
  do update set count = public.search_usage.count + 1
  returning count into v_count;
  return v_count;
end;
$$;

-- Today's count (0 if no row yet). Read-only, safe for clients.
create or replace function public.get_search_usage_today(p_user_id uuid)
returns integer
language sql
stable
as $$
  select coalesce(
    (select count from public.search_usage
      where user_id = p_user_id
        and day = (now() at time zone 'utc')::date),
    0
  );
$$;

comment on table public.search_usage is
  'Free tier daily search quota (10 per UTC day). Resets at midnight UTC.';
