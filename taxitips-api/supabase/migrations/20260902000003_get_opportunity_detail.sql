-- Explainability RPC: "why was this suggested" -- returns the full opportunity
-- (including severity_tier/mode/rule_id/confidence) plus its source_events'
-- raw payloads, gated by the same entitlement check as get_smart_alerts.

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
            where se.id = any(o.source_event_ids)
        )
    ) into result
    from public.opportunities o
    where o.id = p_opportunity_id;

    return result;
end;
$$;
