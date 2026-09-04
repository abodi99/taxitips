-- Dedup marker for the FCM push-send pipeline: a still-active opportunity is
-- upserted every ~60s poll cycle, but a driver should only ever be notified
-- once for it, not on every cycle it remains live. notified_at records when
-- (if ever) a push was actually sent for this opportunity.
--
-- Verified against production (2026-09-04) that PostgREST's partial-column
-- upsert (worker only sends the columns mapOpportunity() builds) leaves
-- columns absent from the payload untouched rather than nulling them -- so a
-- plain column here, not a separate join table, is a safe dedup mechanism:
-- set once by the send pipeline, survives every subsequent re-upsert of the
-- same external_id for as long as the disruption stays active.
alter table public.opportunities add column if not exists notified_at timestamptz;

create index if not exists idx_opportunities_notified_at
  on public.opportunities (notified_at)
  where notified_at is null;
