-- Expand: koppla enhet till inloggat konto + last_seen för push/session.
-- user_id är nullable så befintliga förartokens utan konto fortsätter fungera.
-- last_seen_at sätts av Django /api/device/session vid inloggning och
-- push-registrering — inte av poll-cykeln.

alter table public.devices
  add column if not exists user_id uuid;

alter table public.devices
  add column if not exists last_seen_at timestamptz;

create index if not exists idx_devices_user_id on public.devices (user_id);
