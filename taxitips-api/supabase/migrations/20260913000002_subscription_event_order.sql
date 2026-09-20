-- P0-C3: Stripe levererar inte webhook-händelser i ordning. Tidpunkten för den
-- senast tillämpade prenumerationshändelsen gör att en äldre (t.ex. past_due) inte
-- skriver över en nyare (active). Se functions/stripe-webhook/index.ts.
--
-- Expand: ny nullbar kolumn. Funktionen läser den, så migrationen körs först.

alter table public.companies add column if not exists last_subscription_event_at timestamptz;
