-- TechPulse schema. Safe to re-run.
create table if not exists public.videos (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  kind text not null check (kind in ('long', 'short')),
  topic text,
  title text,
  description text,
  tags text[],
  status text not null default 'rendered',         -- rendered | uploaded | published | failed
  youtube_id text,
  privacy text,                                    -- private | public | unlisted
  preview_path text,                               -- storage object in bucket 'videos'
  thumb_path text,
  duration_s numeric,
  publish_requested boolean not null default false,
  published_at timestamptz,
  stats jsonb,                                     -- views/likes/comments from YouTube
  meta jsonb
);
create index if not exists videos_created_at_idx on public.videos (created_at desc);

-- Who may use the phone app (emails of Supabase Auth users).
create table if not exists public.app_admins (email text primary key);

create or replace function public.is_app_admin() returns boolean
language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.app_admins where email = (auth.jwt() ->> 'email'));
$$;

alter table public.videos enable row level security;
alter table public.app_admins enable row level security;

drop policy if exists "admins read videos" on public.videos;
create policy "admins read videos" on public.videos for select to authenticated using (public.is_app_admin());
drop policy if exists "admins request publish" on public.videos;
create policy "admins request publish" on public.videos for update to authenticated
  using (public.is_app_admin()) with check (public.is_app_admin());

-- The app may only flip publish_requested; everything else is written by the pipeline (service key).
revoke update on public.videos from authenticated;
grant update (publish_requested) on public.videos to authenticated;
grant select on public.videos to authenticated;

-- Private storage bucket for previews + thumbnails.
insert into storage.buckets (id, name, public, file_size_limit)
values ('videos', 'videos', false, 52428800)
on conflict (id) do nothing;

drop policy if exists "admins read video files" on storage.objects;
create policy "admins read video files" on storage.objects for select to authenticated
  using (bucket_id = 'videos' and public.is_app_admin());

-- Video language (en | hi)
alter table public.videos add column if not exists lang text not null default 'en';
