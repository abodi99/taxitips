-- RPC for getting smart alerts with "Worth It Score"

CREATE OR REPLACE FUNCTION public.get_smart_alerts(p_lat double precision, p_lon double precision)
RETURNS json
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    result json;
BEGIN
    SELECT json_agg(
        json_build_object(
            'id', a.id,
            'title', a.title,
            'summary', a.summary,
            'lat', a.lat,
            'lon', a.lon,
            'end_time', a.end_time,
            'demand_score', a.demand_score,
            'reasons', a.reasons,
            'distance_km', a.distance_km,
            'worth_it_score', CASE 
                -- Assume speed is ~60 km/h (1 min / km). If minutes left < distance + 10, it's not worth it.
                WHEN EXTRACT(EPOCH FROM (a.end_time - NOW())) / 60 < a.distance_km + 10 THEN 0
                ELSE GREATEST(0, a.demand_score - (a.distance_km * 2))
            END
        )
    ) INTO result
    FROM (
        SELECT 
            id, title, summary, lat, lon, end_time, demand_score, reasons,
            -- Haversine formula for distance in km
            (6371 * acos(cos(radians(p_lat)) * cos(radians(lat)) * 
            cos(radians(lon) - radians(p_lon)) + 
            sin(radians(p_lat)) * sin(radians(lat)))) AS distance_km
        FROM public.alerts
        WHERE end_time > NOW()
    ) a;

    RETURN COALESCE(result, '[]'::json);
END;
$$;
