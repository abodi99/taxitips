-- alert_feedback had RLS disabled entirely (relrowsecurity=false) -- anon/authenticated could
-- read, update, or delete any row with no restriction. Feedback data isn't sensitive to read,
-- but write access should be limited to insert-only-by-device, not full CRUD.

alter table public.alert_feedback enable row level security;

create policy alert_feedback_insert_any on public.alert_feedback
  for insert
  with check (true);

create policy alert_feedback_select_none on public.alert_feedback
  for select
  using (false);
