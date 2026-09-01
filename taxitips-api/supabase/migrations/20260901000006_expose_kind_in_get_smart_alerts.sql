-- Expose `kind` (e.g. 'traffic' for road-sourced alerts vs the transit-sourced default) in
-- get_smart_alerts so the Flutter client can actually filter road vs. transit disruptions --
-- previously stored on public.alerts but never returned to the client at all.

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
            id, title, summary, kind, lat, lon, end_time, demand_score, reasons,
            (6371 * acos(cos(radians(p_lat)) * cos(radians(lat)) *
            cos(radians(lon) - radians(p_lon)) +
            sin(radians(p_lat)) * sin(radians(lat)))) AS distance_km
        FROM public.alerts
        WHERE end_time > NOW()
    ) a;

    RETURN COALESCE(result, '[]'::json);
end;
$$;
