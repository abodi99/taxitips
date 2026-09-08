-- Django tar över ägandet av source_events och opportunities.
--
-- Bakgrund: pipelinen (hämtning, klassificering, poängsättning) har flyttat till
-- taxitips-backend/. Fram tills nu skrev den till en EGEN Postgres, medan appen
-- läste Supabases opportunities som Node-workern fyllde -- två databaser, två
-- skrivare, och allt Django räknade ut nådde aldrig en förare.
--
-- Härifrån äger Django dessa två tabellers schema via sina egna migrationer
-- (core/migrations/). Den här filen är sista gången SQL-migrationerna rör dem.
-- Övriga tabeller (companies, devices, profiles, ...) ägs fortfarande här.
--
-- Varför DROP och inte ALTER: de två tabellernas innehåll är regenererbart --
-- pipelinen skriver om dem var 90:e sekund och purge_old slänger dem efter sju
-- dagar ändå. Att förena schemana hade krävt en tio kolumner lång ALTER-serie
-- (text[] -> jsonb för reasons, uuid[] -> jsonb för source_event_ids, två
-- saknade compensation-kolumner, tio nullability-skillnader, och samtliga av
-- Djangos index). En pollcykels data är ett billigare pris än den serien.
--
-- Kör INTE mot produktion utan en pg_dump i samma session (CLAUDE.md).

-- TimescaleDB följde tidigare med Djangos egna container. Den finns redan
-- tillgänglig i Supabases Postgres-image (2.16.1), så tillägget flyttar hit
-- i stället för att gå förlorat. Ingen hypertable skapas -- det finns inget
-- tidsseriedata-schema än, det här gör bara tillägget tillgängligt.
create extension if not exists timescaledb;

drop table if exists public.source_events cascade;
drop table if exists public.opportunities cascade;

-- get_opportunity_detail joinar via source_event_ids, som blir jsonb i Djangos
-- modell i stället för uuid[]. jsonb-operatorn `?` ersätter `= any(...)` -- det
-- är samma operator core/repository.py:s purge_old redan använder, så båda
-- sidor talar samma språk efter det här.
--
-- get_smart_alerts behöver INGEN ändring: den läser `reasons` rakt in i
-- json_build_object, och en jsonb-array ger exakt samma utdata som en text[]
-- gjorde. coalesce(region,'skane') lämnas orörd -- Django skriver NULL, inte
-- tom sträng, just för att den fallbacken ska fortsätta fungera.
create or replace function public.get_opportunity_detail(p_opportunity_id uuid, p_device_token text default null)
returns json
language plpgsql
security definer
as $$
declare
    result json;
begin
    if not public.current_entitlement(p_device_token) then
        return null;
    end if;

    select json_build_object(
        'opportunity', json_build_object(
            'id', o.id,
            'title', o.title,
            'summary', o.summary,
            'mode', o.mode,
            'severity_tier', o.severity_tier,
            'level', o.level,
            'confidence', o.confidence,
            'rule_id', o.rule_id,
            'reasons', o.reasons,
            'demand_score', o.demand_score,
            'start_time', o.start_time,
            'end_time', o.end_time,
            'computed_at', o.computed_at,
            'expired_reason', o.expired_reason
        ),
        'source_events', (
            select coalesce(json_agg(json_build_object(
                'source', se.source,
                'external_id', se.external_id,
                'fetched_at', se.fetched_at,
                'active_from', se.active_from,
                'active_to', se.active_to,
                'raw', se.raw
            )), '[]'::json)
            from public.source_events se
            where o.source_event_ids ? se.id::text
        )
    ) into result
    from public.opportunities o
    where o.id = p_opportunity_id;

    return result;
end;
$$;
