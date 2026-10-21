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

-- Long-term performance memory (kept ~6 months, no files) used to steer topic choice.
create table if not exists public.insights (
  youtube_id text primary key,
  lang text not null default 'en',
  kind text,
  topic text,
  title text,
  created_at timestamptz not null default now(),
  views integer not null default 0,
  likes integer not null default 0,
  comments integer not null default 0,
  updated_at timestamptz
);
alter table public.insights enable row level security;
drop policy if exists "admins read insights" on public.insights;
create policy "admins read insights" on public.insights for select to authenticated using (public.is_app_admin());
grant select on public.insights to authenticated;

-- Channel safety: set when YouTube rejects/removes a video
alter table public.insights add column if not exists health text;

-- Daily channel totals (for the app's growth chart)
create table if not exists public.channel_stats (
  day date primary key,
  subscribers integer not null default 0,
  views bigint not null default 0,
  videos integer not null default 0,
  updated_at timestamptz not null default now()
);
-- One row per automated run (app: latest runs)
create table if not exists public.runs (
  id bigserial primary key,
  started_at timestamptz not null default now(),
  finished_at timestamptz,
  lang text, made integer default 0, published integer default 0, held integer default 0, failed integer default 0,
  note text
);
-- App-controlled switches: paused (bool), autopublish (bool)
create table if not exists public.settings (key text primary key, value jsonb not null, updated_at timestamptz default now());
insert into public.settings (key, value) values ('paused', 'false'), ('autopublish', 'true') on conflict (key) do nothing;
-- "Run now" requests from the app; the cloud picks them up and starts a run
create table if not exists public.run_requests (
  id bigserial primary key,
  created_at timestamptz not null default now(),
  lang text not null default 'en' check (lang in ('en', 'hi')),
  long integer not null default 0 check (long between 0 and 1),
  shorts integer not null default 1 check (shorts between 0 and 4),
  status text not null default 'pending'
);

alter table public.channel_stats enable row level security;
alter table public.runs enable row level security;
alter table public.settings enable row level security;
alter table public.run_requests enable row level security;
drop policy if exists "admins read channel_stats" on public.channel_stats;
create policy "admins read channel_stats" on public.channel_stats for select to authenticated using (public.is_app_admin());
drop policy if exists "admins read runs" on public.runs;
create policy "admins read runs" on public.runs for select to authenticated using (public.is_app_admin());
drop policy if exists "admins read settings" on public.settings;
create policy "admins read settings" on public.settings for select to authenticated using (public.is_app_admin());
drop policy if exists "admins change settings" on public.settings;
create policy "admins change settings" on public.settings for update to authenticated
  using (public.is_app_admin()) with check (public.is_app_admin() and key in ('paused', 'autopublish'));
drop policy if exists "admins read run_requests" on public.run_requests;
create policy "admins read run_requests" on public.run_requests for select to authenticated using (public.is_app_admin());
drop policy if exists "admins request runs" on public.run_requests;
create policy "admins request runs" on public.run_requests for insert to authenticated
  with check (public.is_app_admin() and status = 'pending');
grant select on public.channel_stats, public.runs, public.settings, public.run_requests to authenticated;
grant update (value, updated_at) on public.settings to authenticated;
grant insert (lang, long, shorts) on public.run_requests to authenticated;
grant usage on sequence public.run_requests_id_seq to authenticated;
