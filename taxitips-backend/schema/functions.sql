-- SQL-funktioner som de faktiskt ser ut i databasen just nu.
-- Genererad av `manage.py dump_truth`. Redigera inte för hand.
--
-- Poängen med filen: migrationsmappen innehåller sju versioner av
-- get_smart_alerts. Här finns en -- den som gäller.

-- ─── current_entitlement ─────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.current_entitlement(p_device_token text)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
  select coalesce(
    (
      select c.status in ('trial', 'active') or c.subscription_status = 'active'
      from public.devices d
      join public.companies c on c.id = d.company_id
      where p_device_token is not null and d.token = p_device_token
      limit 1
    ),
    (
      select c.status in ('trial', 'active') or c.subscription_status = 'active'
      from public.company_members m
      join public.companies c on c.id = m.company_id
      where auth.uid() is not null
        and m.user_id = auth.uid()
        and m.status = 'active'
      limit 1
    ),
    false
  );
$function$;

-- ─── device_by_token ─────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.device_by_token(p_token text)
 RETURNS json
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  v_device public.devices;
  v_company public.companies;
begin
  select * into v_device from public.devices where token = p_token;
  if v_device is null then
    raise exception 'Enheten hittades inte';
  end if;

  select * into v_company from public.companies where id = v_device.company_id;

  return json_build_object(
    'device', row_to_json(v_device),
    'company', row_to_json(v_company)
  );
end;
$function$;

-- ─── get_opportunity_detail ──────────────────────────────────────
CREATE OR REPLACE FUNCTION public.get_opportunity_detail(p_opportunity_id uuid, p_device_token text DEFAULT NULL::text)
 RETURNS json
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
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
$function$;

-- ─── get_smart_alerts ────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.get_smart_alerts(p_lat double precision, p_lon double precision, p_device_token text DEFAULT NULL::text)
 RETURNS json
 LANGUAGE plpgsql
 SECURITY DEFINER
AS $function$
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

-- ─── gtfs_promote_feed_version ───────────────────────────────────
CREATE OR REPLACE FUNCTION public.gtfs_promote_feed_version(p_new_id uuid, p_operator text)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  v_previous_id uuid;
begin
  select id into v_previous_id
  from public.gtfs_feed_versions
  where operator = p_operator and is_current
  limit 1;

  update public.gtfs_feed_versions
  set is_current = false
  where operator = p_operator and is_current;

  update public.gtfs_feed_versions
  set is_current = true
  where id = p_new_id;

  -- Keep exactly the new version and the one it replaced (rollback safety
  -- net); delete anything older than that.
  delete from public.gtfs_feed_versions
  where operator = p_operator
    and id <> p_new_id
    and (v_previous_id is null or id <> v_previous_id);
end;
$function$;

-- ─── handle_new_user ─────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.handle_new_user()
 RETURNS trigger
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
begin
  insert into public.profiles (id, name)
  values (new.id, new.raw_user_meta_data ->> 'name')
  on conflict (id) do nothing;
  return new;
end;
$function$;

-- ─── join_device ─────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.join_device(p_join_code text, p_label text DEFAULT 'Förare'::text)
 RETURNS json
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  v_company public.companies;
  v_seat_count int;
  v_token text;
  v_device public.devices;
begin
  select * into v_company from public.companies where join_code = upper(p_join_code);
  if v_company is null then
    raise exception 'Ogiltig bolagskod';
  end if;

  select count(*) into v_seat_count from public.devices where company_id = v_company.id;
  if v_seat_count >= v_company.seats then
    raise exception 'Inga lediga platser';
  end if;

  v_token := gen_random_uuid()::text;

  insert into public.devices (company_id, token, label, kind)
  values (v_company.id, v_token, coalesce(nullif(p_label, ''), 'Förare'), 'driver')
  returning * into v_device;

  return json_build_object('token', v_device.token, 'id', v_device.id, 'label', v_device.label);
end;
$function$;

-- ─── regenerate_join_code ────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.regenerate_join_code(p_company_id uuid)
 RETURNS text
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare
  v_code text;
begin
  if not exists (
    select 1 from public.company_members
    where company_id = p_company_id
      and user_id = auth.uid()
      and status = 'active'
  ) then
    raise exception 'Not a member of this company';
  end if;

  loop
    select string_agg(
             substr('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', (random() * 32)::int + 1, 1),
             ''
           )
      into v_code
      from generate_series(1, 6);
    exit when not exists (select 1 from public.companies where join_code = v_code);
  end loop;

  update public.companies set join_code = v_code where id = p_company_id;
  return v_code;
end;
$function$;
