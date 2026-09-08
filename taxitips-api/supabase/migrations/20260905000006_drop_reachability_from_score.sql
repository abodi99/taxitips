-- Reachability leaves the score; the driver decides whether to drive.
--
-- worth_it_score used to compute `demand_score - distance_km * 2` and zero
-- out anything judged unreachable before the disruption ended. That encoded
-- assumptions about driving speed and willingness we have no basis for, and
-- it hid genuinely strong opportunities: a cancelled line 90 km away scored
-- the same 0 as a trivial one. Distance is now shown on the card and left to
-- the driver, who knows their own shift and traffic.
--
-- Two things had been conflated, and are now separate:
--   * scoring      -- how strong is this signal (no distance term at all)
--   * market scope -- whose business is this tip in the first place
--
-- The second still needs a rule, and removing the distance term exposed why:
-- without it, 65 strong tips more than 150 km away surfaced at the top for a
-- Stockholm driver, including Göteborg trains 400 km off. Hence a hard market
-- radius -- a horizon, not a score adjustment.
create or replace function public.get_smart_alerts(
  p_lat double precision,
  p_lon double precision,
  p_device_token text default null
)
returns json
language plpgsql
security definer
as $function$
declare
    result json;
    v_region text;
    v_market_radius_km constant numeric := 150;
begin
    if not public.current_entitlement(p_device_token) then
        return '[]'::json;
    end if;

    -- Coarse market boxes, used only to place opportunities that have no
    -- coordinate of their own. Anything located is fenced by distance below.
    v_region := case
        when p_lat between 55.0 and 56.6 and p_lon between 12.4 and 14.6 then 'skane'
        when p_lat between 58.7 and 60.4 and p_lon between 17.0 and 19.2 then 'sl'
        when p_lat between 57.0 and 58.7 and p_lon between 11.0 and 13.0 then 'vt'
        else null
    end;

    select json_agg(
        json_build_object(
            'id', a.id, 'title', a.title, 'summary', a.summary, 'kind', a.kind,
            'mode', a.mode, 'severity_tier', a.severity_tier, 'confidence', a.confidence,
            'rule_id', a.rule_id, 'lat', a.lat, 'lon', a.lon,
            'start_time', a.start_time, 'end_time', a.end_time,
            'demand_score', a.demand_score, 'reasons', a.reasons,
            -- Shown, never scored.
            'distance_km', a.distance_km,
            'is_active', a.end_time > now(),
            -- Kept as a field (app, map and sorting all read it) but it now
            -- answers only "how strong is this signal".
            'worth_it_score', case
                when a.end_time <= now() then 0
                else a.demand_score
            end
        )
    ) into result
    from (
        select
            id, title, summary, kind, mode, severity_tier, confidence, rule_id,
            lat, lon, start_time, end_time, demand_score, reasons,
            coalesce(region, 'skane') as region_key,
            case when lat is null or lon is null then null else
                -- LEAST/GREATEST guard acos against floating-point drift
                -- pushing the argument just outside [-1, 1] at distance ~0.
                (6371 * acos(least(1, greatest(-1,
                 cos(radians(p_lat)) * cos(radians(lat)) *
                 cos(radians(lon) - radians(p_lon)) +
                 sin(radians(p_lat)) * sin(radians(lat))))))
            end as distance_km
        from public.opportunities
        where end_time > now() - interval '24 hours'
          and severity_tier <> 'ignore'
          and demand_score > 0
    ) a
    where
        (a.distance_km is not null and a.distance_km <= v_market_radius_km)
        or (a.distance_km is null and v_region is not null
            and a.region_key = v_region);

    return coalesce(result, '[]'::json);
end;
$function$;
