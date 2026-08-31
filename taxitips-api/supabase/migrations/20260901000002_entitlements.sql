-- Entitlement primitive: is this device's company currently allowed to see scored opportunity data?
-- Based on the ACTUAL live schema (verified via psql introspection 2026-08-31), not the git migration
-- files, which have diverged from production (see TAXITIPS_STATUS.md addendum).
--
-- companies.status: 'trial' | 'active' | (others e.g. 'canceled') -- default 'trial'
-- companies.subscription_status: 'inactive' | (presumably 'active'/other stripe-driven values) -- default 'inactive'
-- devices.token: the driver app's bearer identifier (not a FK to auth.users)

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
      where d.token = p_device_token
      limit 1
    ),
    false
  );
$$;

grant execute on function public.current_entitlement(text) to anon, authenticated;
