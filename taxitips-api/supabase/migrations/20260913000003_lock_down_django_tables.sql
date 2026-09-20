-- Säkerhet (P0): Djangos tabeller ska inte gå att nå via PostgREST som anon eller authenticated.
--
-- Uppmätt i produktionen 2026-09-13, endast läsande frågor: elva tabeller i public hade
-- RLS avstängt och full rättighet (SELECT, INSERT, UPDATE, DELETE) för anon och
-- authenticated -- bland dem push_delivery (förartokens), scoring_rule, source_status,
-- opportunity_favorite och två säkerhetskopior av opportunities och source_events.
-- Med den publika anon-nyckeln kan de sannolikt läsas och ändras via /rest/v1 (inte
-- provat mot produktionen).
--
-- Orsak: Supabases standardrättigheter. Varje tabell som rollen postgres skapar får
-- automatiskt anon=arwdDxt och authenticated=arwdDxt, och Django skapar sina tabeller
-- som postgres.
--
-- Säkert att köra: ingen klient läser tabellerna via PostgREST (sökt i appen, webben,
-- edge-funktionerna och pipeline-sidan). Django ansluter som tabellägaren postgres och
-- edge-funktionerna som service_role; ingen av dem påverkas. Inga data tas bort.

do $$
declare
  t text;
begin
  foreach t in array array[
    'ais_vessels',
    'django_migrations',
    'events',
    'ferry_arrivals',
    'ferry_calls',
    'ferry_timetable_calls',
    'opportunities',
    'opportunity_combinations',
    'device_presence',
    'opportunity_favorite',
    'opportunity_feedback',
    'push_delivery',
    'rail_assessment',
    'rail_station',
    'region_compensation_rule',
    'scoring_rule',
    'source_events',
    'source_status',
    'stop_area',
    '_backup_opportunities_20260910',
    '_backup_source_events_20260910'
  ]
  loop
    if to_regclass(format('public.%I', t)) is not null then
      execute format('revoke all on table public.%I from anon, authenticated', t);
    end if;
  end loop;
end $$;

-- Nya tabeller som postgres skapar (t.ex. Djangos migrationer) får inte längre
-- rättigheter för anon och authenticated automatiskt. En Supabase-migration som skapar
-- en tabell appen ska läsa via PostgREST ger därför rättigheten uttryckligen, tillsammans
-- med RLS-policyer.
alter default privileges for role postgres in schema public revoke all on tables from anon, authenticated;
alter default privileges for role postgres in schema public revoke all on sequences from anon, authenticated;
