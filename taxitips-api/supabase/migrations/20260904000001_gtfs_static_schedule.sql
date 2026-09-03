-- GTFS-static schedule storage: closes the gap scoring.js's own header comment
-- names outright -- "Without GTFS static timetable data (next scheduled
-- departure), this is the best available signal from the realtime feed's own
-- text." This migration only adds capability; nothing reads or writes these
-- tables yet, so it's a pure expand step.
--
-- Design: denormalized/query-shaped (one row per stop+trip+departure,
-- pre-joined with route_id/route_type) rather than a 1:1 mirror of raw GTFS
-- files, since the only query this needs to serve well is "next departure at
-- stop X after time T." departure_seconds intentionally preserves GTFS's
-- >24:00:00 convention for after-midnight trips (not wrapped to 0-86399) --
-- wrapping it would break same-service-day ordering across midnight.
--
-- Static GTFS churns daily (Trafiklab refreshes ~03:00-06:00). Storage uses a
-- versioned replace-not-append strategy: each ingest gets its own
-- feed_version_id, gtfs_promote_feed_version() atomically flips which version
-- is "current" and prunes anything older than the previous version, so a
-- worker crash mid-ingest can never leave zero current rows, and a bad new
-- feed doesn't destroy the last-known-good one until the next successful
-- ingest replaces it.

create table public.gtfs_feed_versions (
  id uuid primary key default gen_random_uuid(),
  operator text not null,
  fetched_at timestamptz not null default now(),
  is_current boolean not null default false,
  stop_count integer,
  trip_count integer,
  stop_time_count integer,
  created_at timestamptz not null default now()
);

create unique index idx_gtfs_feed_versions_current
  on public.gtfs_feed_versions (operator)
  where is_current;

create table public.gtfs_stop_departures (
  id bigint generated always as identity primary key,
  feed_version_id uuid not null references public.gtfs_feed_versions(id) on delete cascade,
  operator text not null,
  stop_id text not null,
  trip_id text not null,
  route_id text,
  route_type integer,
  service_id text not null,
  departure_seconds integer not null,
  stop_sequence integer,
  days_of_week smallint not null default 0,
  start_date date,
  end_date date
);

create index idx_gtfs_departures_lookup
  on public.gtfs_stop_departures (feed_version_id, stop_id, departure_seconds);
create index idx_gtfs_departures_route
  on public.gtfs_stop_departures (feed_version_id, route_id, departure_seconds);

create table public.gtfs_service_exceptions (
  id bigint generated always as identity primary key,
  feed_version_id uuid not null references public.gtfs_feed_versions(id) on delete cascade,
  service_id text not null,
  exception_date date not null,
  exception_type smallint not null
);

create index idx_gtfs_exceptions_lookup
  on public.gtfs_service_exceptions (feed_version_id, service_id, exception_date);

alter table public.gtfs_feed_versions enable row level security;
alter table public.gtfs_stop_departures enable row level security;
alter table public.gtfs_service_exceptions enable row level security;
-- No policies added -- service-role only (bypasses RLS), same pattern as
-- source_events/opportunities. No anon/authenticated grants at all.

-- Atomically promote a newly-ingested feed version to "current" and prune
-- anything older than the previous current version. SECURITY DEFINER so the
-- worker's service-role connection can call it as one round-trip instead of
-- 3 (unset old, set new, delete stale), which matters because a crash between
-- separate client-side steps could otherwise leave zero current rows.
create or replace function public.gtfs_promote_feed_version(p_new_id uuid, p_operator text)
returns void
language plpgsql
security definer
set search_path = public
as $$
declare
  v_previous_id uuid;
begin
  select id into v_previous_id
  from public.gtfs_feed_versions
  where operator = p_operator and is_current
  limit 1;

  update public.gtfs_feed_versions
  set is_current = false
  where operator = p_operator and is_current;

  update public.gtfs_feed_versions
  set is_current = true
  where id = p_new_id;

  -- Keep exactly the new version and the one it replaced (rollback safety
  -- net); delete anything older than that.
  delete from public.gtfs_feed_versions
  where operator = p_operator
    and id <> p_new_id
    and (v_previous_id is null or id <> v_previous_id);
end;
$$;
