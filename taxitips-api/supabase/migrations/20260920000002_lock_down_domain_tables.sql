-- Domäntabellerna slutar vara öppna för anon.
--
-- UPPMÄTT 2026-09-20 mot den lokala instansen (samma form som produktionen,
-- se baseline-migrationen):
--
--   tabell                 rls   rättigheter
--   companies              av    anon: SELECT INSERT UPDATE DELETE TRUNCATE ...
--   company_members        av    anon: SELECT INSERT UPDATE DELETE TRUNCATE ...
--   devices                av    anon: SELECT INSERT UPDATE DELETE TRUNCATE ...
--   device_transfer_codes  av    anon: SELECT INSERT UPDATE DELETE TRUNCATE ...
--
-- Med den publika anon-nyckeln går det alltså att läsa `devices.token` för
-- samtliga förare. Den token ÄR förarens credential i den gamla modellen --
-- hela entitlement-grinden faller på det. Det går också att skriva egna rader
-- i alla fyra tabellerna.
--
-- 20260913000003 stängde Djangos tabeller. Den här stänger Supabases egna,
-- som den inte omfattade.
--
-- VAD SOM FORTSÄTTER FUNGERA. Portalen och appens adminläge läser `companies`,
-- `company_members` och `devices` som inloggad medlem via PostgREST. Det
-- behålls, avgränsat till det egna bolaget. Django ansluter som tabellägaren
-- och edge-funktionerna som service_role; ingen av dem påverkas av RLS.
--
-- VAD SOM SLUTAR FUNGERA, MED AVSIKT:
--   * anon får ingenting. Förarens väg går genom Djangos /api/fleet/*.
--   * ingen klient får skriva i `devices`. Push-token och etikett sätts av
--     /api/device/session och /api/fleet/pair, som kontrollerar behörigheten.
--   * `device_transfer_codes` stängs helt. Byteskoden gav en ny enhetstoken
--     utan att någon godkände telefonen för en bil, och ersätts av
--     parkopplingskoden (/api/fleet/pairing-codes).
--
-- ÅTERSTÄLLNING: `alter table ... disable row level security` på respektive
-- tabell återställer läget. Gör inte det utan att först ha stängt hålet på
-- annat sätt.

-- --- companies -----------------------------------------------------------
alter table public.companies enable row level security;

drop policy if exists companies_select_own on public.companies;
create policy companies_select_own on public.companies
  for select to authenticated
  using (
    exists (
      select 1 from public.company_members m
      where m.company_id = companies.id
        and m.user_id = auth.uid()
        and m.status = 'active'
    )
  );

drop policy if exists companies_update_own on public.companies;
create policy companies_update_own on public.companies
  for update to authenticated
  using (
    exists (
      select 1 from public.company_members m
      where m.company_id = companies.id
        and m.user_id = auth.uid()
        and m.status = 'active'
        and m.role in ('company_owner', 'fleet_admin')
    )
  );

-- Registrering: den inloggade användaren skapar sitt bolag och blir medlem i
-- nästa anrop. Utan den här raden går självregistreringen inte att slutföra.
drop policy if exists companies_insert_authenticated on public.companies;
create policy companies_insert_authenticated on public.companies
  for insert to authenticated
  with check (true);

revoke all on table public.companies from anon;
revoke truncate, delete, references, trigger on table public.companies from authenticated;

-- --- company_members -----------------------------------------------------
alter table public.company_members enable row level security;

drop policy if exists company_members_select_own on public.company_members;
create policy company_members_select_own on public.company_members
  for select to authenticated
  using (
    user_id = auth.uid()
    or exists (
      select 1 from public.company_members mine
      where mine.company_id = company_members.company_id
        and mine.user_id = auth.uid()
        and mine.status = 'active'
    )
  );

-- Bara sitt EGET medlemskap, och bara vid registrering. Att bjuda in andra
-- går genom Djangos behörighetskontroll, inte genom en insert från klienten.
drop policy if exists company_members_insert_self on public.company_members;
create policy company_members_insert_self on public.company_members
  for insert to authenticated
  with check (user_id = auth.uid());

revoke all on table public.company_members from anon;
revoke update, delete, truncate, references, trigger
  on table public.company_members from authenticated;

-- --- devices -------------------------------------------------------------
-- Ingen klient skriver här. Raden bär förarens credential i den gamla
-- modellen, och en läsbar token är samma sak som en utdelad token.
alter table public.devices enable row level security;

drop policy if exists devices_select_own_company on public.devices;
create policy devices_select_own_company on public.devices
  for select to authenticated
  using (
    exists (
      select 1 from public.company_members m
      where m.company_id = devices.company_id
        and m.user_id = auth.uid()
        and m.status = 'active'
    )
  );

revoke all on table public.devices from anon;
revoke insert, update, delete, truncate, references, trigger
  on table public.devices from authenticated;

-- --- device_transfer_codes ----------------------------------------------
-- Stängd helt. Ersatt av parkopplingskoden, som binder telefonen till en
-- BIL och godkänns av en behörig administratör.
alter table public.device_transfer_codes enable row level security;
revoke all on table public.device_transfer_codes from anon, authenticated;

comment on table public.device_transfer_codes is
  'Utfasad. Byteskoden gav en ny enhetstoken utan att någon godkände telefonen '
  'för en bil. Ersatt av fleet_pairing_code och /api/fleet/pairing-codes.';
