-- Store the ETag/Last-Modified of each ingested GTFS static feed so the daily
-- refresh can make a conditional GET and skip the multi-MB download when the
-- feed hasn't changed.
--
-- This matters because the static quota is tiny (Trafiklab Bronze: 50 calls
-- per MONTH), and Trafiklab supports conditional requests on every endpoint
-- specifically for this case. Without it, every refresh spends a full call
-- regardless of whether anything changed.
--
-- Nullable: the server may not send either header, and older rows predate
-- this column. Callers must treat null as "unknown, fetch anyway" rather
-- than as "unchanged".
alter table public.gtfs_feed_versions
  add column if not exists source_etag text,
  add column if not exists source_last_modified text;
