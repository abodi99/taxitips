-- SL (Stockholm) site register: stop_area id -> coordinates.
--
-- SL's deviations reference stop_areas, but /v1/sites is keyed by SITE id --
-- a different id space (measured: only 14 of 104 referenced stop_area ids
-- even collide with a site id, and those collisions are coincidental). The
-- ?expand=true response carries each site's stop_areas[], which bridges the
-- two spaces for 104/104 of the referenced ids. This table stores that
-- bridge, one row per stop_area, so a deviation can be placed on the map
-- without an API call per alert.
--
-- Sites with several stop areas (a station plus its bus terminal) yield
-- several rows sharing one coordinate. That is correct: they are the same
-- place to a driver.
--
-- Refreshed on the existing daily GTFS loop, not a timer of its own. The
-- endpoint needs no API key and has no quota tier.
create table public.sl_sites (
  stop_area_id text primary key,
  site_id text not null,
  name text,
  lat double precision not null,
  lon double precision not null,
  fetched_at timestamptz not null default now()
);

create index idx_sl_sites_site_id on public.sl_sites (site_id);

alter table public.sl_sites enable row level security;
-- No policies -- service-role only, same as the gtfs_* tables. This is
-- ingestion infrastructure, never read directly by a client.
