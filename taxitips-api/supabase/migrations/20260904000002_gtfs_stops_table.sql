-- stops.txt was only counted during ingestion, never stored -- but real GTFS-RT
-- alert stop_ids ('26515', '82000', Skånetrafiken's own short "hållplats"
-- numbers) don't match static GTFS stop_id format ('9022012093032001',
-- Samtrafiken's national VDV-style stop-point IDs), confirmed against real
-- ingested data (zero matches on 8 real sampled alert stop_ids). GTFS's
-- stop_code field exists specifically for "the identifier riders/other
-- systems use" -- this table stores it so nextDeparture() can join through
-- stop_code as a bridge, if that's what actually resolves the mismatch.
create table public.gtfs_stops (
  id bigint generated always as identity primary key,
  feed_version_id uuid not null references public.gtfs_feed_versions(id) on delete cascade,
  stop_id text not null,
  stop_code text,
  stop_name text,
  parent_station text
);

create index idx_gtfs_stops_stop_id on public.gtfs_stops (feed_version_id, stop_id);
create index idx_gtfs_stops_stop_code on public.gtfs_stops (feed_version_id, stop_code);

alter table public.gtfs_stops enable row level security;
-- No policies -- service-role only, same as the other gtfs_* tables.
