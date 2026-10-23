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

-- YouTube Analytics (watch time + retention), filled once the yt-analytics scope is granted
alter table public.insights add column if not exists watch_minutes numeric;
alter table public.insights add column if not exists avg_view_pct numeric;
alter table public.insights add column if not exists avg_view_s numeric;
alter table public.insights add column if not exists variant text;
alter table public.channel_stats add column if not exists watch_hours numeric;
-- Goals the automation works toward (editable in the app) + its daily status / strategy and retention lessons
insert into public.settings (key, value) values
  ('goals', '{"subscribers": 10000, "watch_hours": 2000, "deadline": "2026-11-21"}'),
  ('goal_status', '{}'), ('retention_notes', '""')
on conflict (key) do nothing;
drop policy if exists "admins change settings" on public.settings;
create policy "admins change settings" on public.settings for update to authenticated
  using (public.is_app_admin()) with check (public.is_app_admin() and key in ('paused', 'autopublish', 'goals'));

-- Title optimisation: original title kept when the automation re-titles a weak video
alter table public.insights add column if not exists retitled text;

-- Amazon Associates tracking IDs, entered in the app (More > Amazon affiliate)
insert into public.settings (key, value) values ('affiliate', '{"us": "", "in": ""}') on conflict (key) do nothing;
drop policy if exists "admins change settings" on public.settings;
create policy "admins change settings" on public.settings for update to authenticated
  using (public.is_app_admin()) with check (public.is_app_admin() and key in ('paused', 'autopublish', 'goals', 'affiliate'));

-- Daily lessons the automation writes for itself (shown in the app's Insights tab)
insert into public.settings (key, value) values ('learned_rules', '{}') on conflict (key) do nothing;

-- When YouTube rejected/removed a video (set once; drives the 14-day safety pause)
alter table public.insights add column if not exists health_at timestamptz;
update public.insights set health_at = updated_at where health is not null and health_at is null;

-- Automatic part-2 Shorts for breakout Shorts (set only by the automation)
alter table public.run_requests add column if not exists followup text;
insert into public.settings (key, value) values ('followups', '{}') on conflict (key) do nothing;

-- Short format (hot_take, versus_test, budget_list...) for learning which formats win
alter table public.insights add column if not exists format text;

-- Part-2 Shorts point at the breakout Short they follow (no part 2 of a part 2)
alter table public.insights add column if not exists followup_of text;

-- YouTube logins made from the phone app's "Log in" button: Google sends a one-time code back to the app, the clock
-- job trades it for a lasting login. Tokens live in yt_logins: RLS on with no policies = service key only.
create table if not exists public.yt_logins (
  project int primary key,
  token jsonb not null,
  updated_at timestamptz not null default now()
);
alter table public.yt_logins enable row level security;

create table if not exists public.yt_login_requests (
  id bigint generated always as identity primary key,
  project int not null check (project in (1, 2)),
  code text not null,
  redirect_uri text not null,
  status text not null default 'pending',
  error text,
  created_at timestamptz not null default now()
);
alter table public.yt_login_requests enable row level security;
drop policy if exists "admins add login" on public.yt_login_requests;
create policy "admins add login" on public.yt_login_requests for insert to authenticated with check (public.is_app_admin());
drop policy if exists "admins read login status" on public.yt_login_requests;
create policy "admins read login status" on public.yt_login_requests for select to authenticated using (public.is_app_admin());
