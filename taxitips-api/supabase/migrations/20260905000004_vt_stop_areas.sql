-- Västtrafik (Göteborg) stop-area register: gid -> WGS84 coordinates.
--
-- Situations reference stopAreaGid (measured: 268/268 of referenced gids
-- resolve against this register). The API publishes coordinates in
-- SWEREF99TM (EPSG:3006) -- metres, not degrees -- so vasttrafik.js projects
-- them to WGS84 before insert; unprojected, a Göteborg tip lands in the Gulf
-- of Guinea.
create table if not exists public.vt_stop_areas (
  gid text primary key,
  name text,
  lat double precision not null,
  lon double precision not null,
  fetched_at timestamptz not null default now()
);

alter table public.vt_stop_areas enable row level security;
-- No policies -- service-role only, same as sl_sites and the gtfs_* tables.
