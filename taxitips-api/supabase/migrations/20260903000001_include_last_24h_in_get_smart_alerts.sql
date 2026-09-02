-- Driver asked to always see yesterday's disruptions too, not just currently
-- active ones, so they can sanity-check "was there really a big backup on E22
-- last night" after the fact. Widen the window from "active now" to "active
-- any time in the last 24h" -- a rolling window, not a calendar-day cutoff, so
-- there's no midnight cliff where "yesterday" briefly means two days.
--
-- start_time is included in the output so the client can show real date/time
-- (not just "ends in X min") and tell active vs. already-ended apart.
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
                WHEN EXTRACT(EPOCH FROM (a.end_time - NOW())) / 60 < a.distance_km + 10 THEN 0
                ELSE GREATEST(0, a.demand_score - (a.distance_km * 2))
            END
        )
    ) INTO result
    FROM (
        SELECT
            id, title, summary, kind, mode, severity_tier, confidence, rule_id,
            lat, lon, start_time, end_time, demand_score, reasons,
            (6371 * acos(cos(radians(p_lat)) * cos(radians(lat)) *
            cos(radians(lon) - radians(p_lon)) +
            sin(radians(p_lat)) * sin(radians(lat)))) AS distance_km
        FROM public.opportunities
        WHERE end_time > now() - interval '24 hours'
          AND severity_tier <> 'ignore'
          AND demand_score > 0
    ) a;

    RETURN COALESCE(result, '[]'::json);
end;
$$;
