-- source_events / opportunities model split (see architecture plan in project notes).
-- Pure "expand" step: introduces both tables, touches nothing existing. public.alerts
-- stays authoritative for reads until a later migration cuts get_smart_alerts over.

-- source_events: latest-known-state per raw fact from an upstream API (upsert on
-- external_id, not append-only -- keeps this simple, avoids an unbounded-growth
-- cleanup job. Explainability is still satisfied because opportunities point at the
-- fact as last observed, which is enough to answer "which source event, which rule").
create table public.source_events (
  id uuid primary key default gen_random_uuid(),
  source text not null,              -- 'trafiklab' | 'trafikverket' | 'smhi' (later)
  external_id text not null unique,  -- e.g. "skane:1234", "tv:mock-e22:0"
  mode text,                         -- 'train' | 'bus' | 'road' | 'weather' | null (unknown)
  fetched_at timestamptz not null default now(),
  active_from timestamptz,
  active_to timestamptz,
  raw jsonb not null,                -- full untouched source payload
  lat double precision,
  lon double precision,
  created_at timestamptz not null default now()
);

create index idx_source_events_external_id on public.source_events (external_id);
create index idx_source_events_active_to on public.source_events (active_to);

alter table public.source_events enable row level security;
-- Service-role only; no anon/authenticated access -- raw source payloads are not
-- meant for direct client consumption (that's what get_opportunity_detail is for).

-- opportunities: one row per derived, scored thing shown to a driver. Superset of
-- today's alerts shape, plus explicit provenance (source_event_ids, rule_id,
-- confidence) that alerts never had.
create table public.opportunities (
  id uuid primary key default gen_random_uuid(),
  external_id text not null unique,
  kind text not null,                -- 'road' | 'transit' (back-compat with existing client filter)
  mode text,                         -- 'train' | 'bus' | 'road' -- new first-class severity axis
  severity_tier text not null default 'unclassified',
  level text not null,               -- 'high'|'medium'|'low'|'ignore'
  title text,
  summary text,
  lat double precision,
  lon double precision,
  h3_index text,
  places jsonb,
  start_time timestamptz,
  end_time timestamptz,
  demand_score integer check (demand_score >= 0 and demand_score <= 100),
  confidence text not null default 'medium', -- 'low'|'medium'|'high' -- explicit, never fabricated
  reasons text[],
  rule_id text,                      -- which function/branch produced this
  source_event_ids uuid[] not null default '{}',
  computed_at timestamptz not null default now(), -- when scoring last ran
  updated_at timestamptz not null default now(),
  expired_reason text
);

create index idx_opportunities_end_time on public.opportunities (end_time);
create index idx_opportunities_h3_index on public.opportunities (h3_index);
create index idx_opportunities_lat_lon on public.opportunities (lat, lon);

alter table public.opportunities enable row level security;
-- No direct table access for anon/authenticated -- reads go through get_smart_alerts /
-- get_opportunity_detail (SECURITY DEFINER, entitlement-gated), same pattern as alerts.
