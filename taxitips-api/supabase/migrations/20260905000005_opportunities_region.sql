-- Which market an opportunity belongs to (skane, sl, vt, ...).
--
-- Needed because ~76% of opportunities carry no coordinate: the alert text
-- names a line or a local stop we cannot geocode. Distance filtering cannot
-- fence those, so without a region they leaked across the country -- a
-- Stockholm tram tip surfaced for a Malmö driver 500 km away at full score,
-- because "distance unknown" was being scored as "distance zero".
alter table public.opportunities add column if not exists region text;

comment on column public.opportunities.region is
  'Market region (skane, sl, vt, trafikverket, ...). Used as a coarse geofence
   for opportunities with no coordinate, so a placeless tip is only offered to
   drivers in the market it belongs to.';

-- Backfill from the id prefix convention each source already follows.
update public.opportunities
set region = case
  when external_id like 'sl:%' then 'sl'
  when external_id like 'vt:%' then 'vt'
  when external_id like 'tv:%' then 'trafikverket'
  when external_id ~ '^[a-z]+:' then split_part(external_id, ':', 1)
  else 'skane'
end
where region is null;
