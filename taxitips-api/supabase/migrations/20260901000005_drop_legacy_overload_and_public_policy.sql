-- Cleanup after 20260901000003_gate_get_smart_alerts.sql: CREATE OR REPLACE with a different
-- argument list created a second overload instead of replacing the function, leaving the old
-- ungated 2-arg get_smart_alerts(double precision, double precision) still callable by anon.
-- Drop it explicitly.
drop function if exists public.get_smart_alerts(double precision, double precision);

-- Contract step: now that get_smart_alerts is gated by current_entitlement() and is
-- SECURITY DEFINER (so it doesn't need direct table grants), the direct public read policy
-- on alerts is no longer needed and is the original security hole this whole fix closes.
drop policy if exists alerts_select_all on public.alerts;
