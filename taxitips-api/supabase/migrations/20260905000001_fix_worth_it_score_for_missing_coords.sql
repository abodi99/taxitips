-- Bug found via user report: a driver toggled notification priority for
-- line_paused (their highest-severity tier) but kept seeing those exact
-- disruptions badged "Osannolikt just nu" (low likelihood) in the list.
--
-- Root cause: when an opportunity has no resolved lat/lon (some Trafiklab
-- alerts only name a station in free text, never geocoded), the Haversine
-- distance_km expression evaluates to NULL. The old CASE then fell through
-- to `GREATEST(0, demand_score - (distance_km * 2))`, and Postgres's
-- GREATEST() silently ignores NULL arguments -- so `demand_score - NULL`
-- becomes NULL, and GREATEST(0, NULL) returns 0. Every opportunity with an
-- unresolved location silently scored worth_it_score=0 regardless of
-- severity, which forces customerLikelihood() (Flutter, severity_labels.dart)
-- to "low" no matter how severe the underlying tier actually is.
--
-- Fix: when location is unknown, don't guess a distance penalty -- use
-- demand_score as-is. We don't know it's far, so we shouldn't score it as if
-- it were.
create or replace function public.get_smart_alerts(p_lat double precision, p_lon double precision, p_device_token text default null)
returns json
language plpgsql
security definer
as $$
declare
    result json;
begin
    if not public.current_entitlement(p_device_token) then
        return '[]'::json;
    end if;

    select json_agg(
        json_build_object(
            'id', a.id,
            'title', a.title,
            'summary', a.summary,
            'kind', a.kind,
            'mode', a.mode,
            'severity_tier', a.severity_tier,
            'confidence', a.confidence,
            'rule_id', a.rule_id,
            'lat', a.lat,
            'lon', a.lon,
            'start_time', a.start_time,
            'end_time', a.end_time,
            'demand_score', a.demand_score,
            'reasons', a.reasons,
            'distance_km', a.distance_km,
            'is_active', a.end_time > now(),
            'worth_it_score', CASE
                WHEN a.end_time <= now() THEN 0
                WHEN a.distance_km IS NULL THEN a.demand_score
                WHEN EXTRACT(EPOCH FROM (a.end_time - NOW())) / 60 < a.distance_km + 10 THEN 0
                ELSE GREATEST(0, a.demand_score - (a.distance_km * 2))
            END
        )
    ) INTO result
    FROM (
        SELECT
            id, title, summary, kind, mode, severity_tier, confidence, rule_id,
            lat, lon, start_time, end_time, demand_score, reasons,
            CASE WHEN lat IS NULL OR lon IS NULL THEN NULL ELSE
                (6371 * acos(cos(radians(p_lat)) * cos(radians(lat)) *
                cos(radians(lon) - radians(p_lon)) +
                sin(radians(p_lat)) * sin(radians(lat))))
            END AS distance_km
        FROM public.opportunities
        WHERE end_time > now() - interval '24 hours'
          AND severity_tier <> 'ignore'
          AND demand_score > 0
    ) a;

    RETURN COALESCE(result, '[]'::json);
end;
$$;
