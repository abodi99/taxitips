-- get_smart_alerts returned every opportunity with end_time > now(), including
-- severity_tier='ignore' rows (demand_score=0, worth_it_score=0 always) -- e.g.
-- "Stängd hållplats" (closed bus stop) notices, which taxiRelevance.js already
-- correctly classifies as not taxi-relevant, but which still reached the client
-- and could flood the list (90+ observed in one poll) with zero-value noise.
-- Filter them out server-side: a driver never needs to see a signal the backend
-- itself has already decided is worth nothing.

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
            'end_time', a.end_time,
            'demand_score', a.demand_score,
            'reasons', a.reasons,
            'distance_km', a.distance_km,
            'worth_it_score', CASE
                WHEN EXTRACT(EPOCH FROM (a.end_time - NOW())) / 60 < a.distance_km + 10 THEN 0
                ELSE GREATEST(0, a.demand_score - (a.distance_km * 2))
            END
        )
    ) INTO result
    FROM (
        SELECT
            id, title, summary, kind, mode, severity_tier, confidence, rule_id,
            lat, lon, end_time, demand_score, reasons,
            (6371 * acos(cos(radians(p_lat)) * cos(radians(lat)) *
            cos(radians(lon) - radians(p_lon)) +
            sin(radians(p_lat)) * sin(radians(lat)))) AS distance_km
        FROM public.opportunities
        WHERE end_time > NOW()
          AND severity_tier <> 'ignore'
          AND demand_score > 0
    ) a;

    RETURN COALESCE(result, '[]'::json);
end;
$$;
