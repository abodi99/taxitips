-- processed_webhook_events does not exist in production despite being referenced by
-- taxitips-api/worker/src/index.js for Stripe webhook idempotency. Must exist before the
-- worker is deployed, or the first webhook event will crash the handler on insert.

create table if not exists public.processed_webhook_events (
  stripe_event_id text primary key,
  event_type text not null,
  processed_at timestamptz not null default now(),
  status text not null,
  error text
);

alter table public.processed_webhook_events enable row level security;
-- Service-role only; no anon/authenticated access needed -- the worker uses the service key.
