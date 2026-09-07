-- current_entitlement() only ever checked the device-token path, so an owner/
-- manager logged in via email+password (no paired device -- e.g. the company
-- owner viewing the driver screen directly from _AppShell in the Flutter app)
-- always got p_device_token = null and was silently denied all data, even for
-- an active/trialing company. This looked identical to "no disruptions right
-- now" (get_smart_alerts returning '[]') with no error, so it went unnoticed.
--
-- Widen the check: entitled if EITHER the device token resolves to an
-- active/trialing company (existing driver-app path, unchanged) OR the
-- caller is authenticated and has an active company_members row for an
-- active/trialing company (the owner/manager path, new).
create or replace function public.current_entitlement(p_device_token text)
returns boolean
language sql
stable
security definer
set search_path = public
as $$
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
$$;

grant execute on function public.current_entitlement(text) to anon, authenticated;
