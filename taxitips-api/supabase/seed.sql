-- Local dev seed. Runs automatically on `supabase db reset`.
--
-- Without it the local database has no company and no device, so
-- current_entitlement() returns false for every token and get_smart_alerts
-- returns "[]" -- which looks exactly like "the pipeline produced nothing"
-- rather than "you are not signed in". That ambiguity cost real debugging
-- time, hence a fixed, known-good driver token to test against.
insert into public.companies (id, name, email, join_code, seats, status)
values (
  '00000000-0000-4000-8000-000000000001',
  'Taxi Tips Demo AB',
  'demo@taxitips.se',
  'DEMO01',
  10,
  'trial'
)
on conflict (id) do nothing;

insert into public.devices (company_id, token, label, kind)
values
  ('00000000-0000-4000-8000-000000000001',
   '9a9bf67c6e8885f44c831232afd314788d86067b7ddfcced', 'Förare – Anna', 'driver'),
  ('00000000-0000-4000-8000-000000000001',
   '6c485ae7c5d16fe553a0ed5758f08cde1d1f69b3bc2efb29', 'Förare – Kalle', 'driver')
on conflict (token) do nothing;
