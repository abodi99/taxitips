-- RLS policies for TaxiTips

alter table public.profiles enable row level security;
alter table public.billing_accounts enable row level security;
alter table public.companies enable row level security;
alter table public.company_members enable row level security;
alter table public.subscriptions enable row level security;
alter table public.devices enable row level security;
alter table public.device_transfer_codes enable row level security;
alter table public.processed_webhook_events enable row level security;
alter table public.app_config enable row level security;
alter table public.alerts enable row level security;
alter table public.tickets enable row level security;

-- Profiles
create policy profiles_select_self on public.profiles
  for select using (id = auth.uid() or public.is_platform_owner());
create policy profiles_update_self on public.profiles
  for update using (id = auth.uid() or public.is_platform_owner());

-- Companies
create policy companies_select_member on public.companies
  for select using (
    public.is_platform_owner()
    or id in (select public.member_company_ids())
  );
create policy companies_update_admin on public.companies
  for update using (
    public.is_platform_owner()
    or id in (select public.admin_company_ids())
  );
create policy companies_insert_authenticated on public.companies
  for insert with check (auth.uid() is not null);

-- Members
create policy members_select on public.company_members
  for select using (
    public.is_platform_owner()
    or company_id in (select public.member_company_ids())
    or user_id = auth.uid()
  );
create policy members_admin_write on public.company_members
  for all using (
    public.is_platform_owner()
    or company_id in (select public.admin_company_ids())
  )
  with check (
    public.is_platform_owner()
    or company_id in (select public.admin_company_ids())
  );

-- Devices: company admins + service role; anon join via RPC
create policy devices_select_admin on public.devices
  for select using (
    public.is_platform_owner()
    or company_id in (select public.admin_company_ids())
  );
create policy devices_admin_write on public.devices
  for all using (
    public.is_platform_owner()
    or company_id in (select public.admin_company_ids())
  )
  with check (
    public.is_platform_owner()
    or company_id in (select public.admin_company_ids())
  );

-- Alerts: readable by any authenticated user or anon with device header via RPC;
-- for MVP allow authenticated read; public read for driver apps using anon + RPC.
create policy alerts_select_authenticated on public.alerts
  for select using (true);

-- Billing / subscriptions: admins of company
create policy billing_select_admin on public.billing_accounts
  for select using (
    public.is_platform_owner()
    or (
      owner_type = 'company'
      and owner_id in (select public.admin_company_ids())
    )
  );

create policy subscriptions_select_admin on public.subscriptions
  for select using (
    public.is_platform_owner()
    or billing_account_id in (
      select id from public.billing_accounts
      where owner_type = 'company'
        and owner_id in (select public.admin_company_ids())
    )
  );

-- Tickets
create policy tickets_select on public.tickets
  for select using (
    public.is_platform_owner()
    or company_id in (select public.member_company_ids())
  );
create policy tickets_insert on public.tickets
  for insert with check (
    public.is_platform_owner()
    or company_id in (select public.admin_company_ids())
  );

-- App config public read
create policy app_config_select on public.app_config
  for select using (true);

-- Join device by company join_code (security definer)
create or replace function public.join_device(p_join_code text, p_label text default 'Förare')
returns public.devices
language plpgsql
security definer
set search_path = public
as $$
declare
  c public.companies;
  d public.devices;
begin
  select * into c
  from public.companies
  where upper(join_code) = upper(trim(p_join_code))
  limit 1;

  if c.id is null then
    raise exception 'INVALID_JOIN_CODE';
  end if;

  insert into public.devices (company_id, token, label)
  values (c.id, encode(gen_random_bytes(24), 'hex'), coalesce(nullif(trim(p_label), ''), 'Förare'))
  returning * into d;

  return d;
end;
$$;

grant execute on function public.join_device(text, text) to anon, authenticated;

-- Device by token
create or replace function public.device_by_token(p_token text)
returns public.devices
language plpgsql
security definer
set search_path = public
as $$
declare
  d public.devices;
begin
  select * into d from public.devices where token = p_token limit 1;
  if d.id is null then
    raise exception 'DEVICE_NOT_FOUND';
  end if;
  update public.devices set last_seen_at = now() where id = d.id;
  return d;
end;
$$;

grant execute on function public.device_by_token(text) to anon, authenticated;

-- Regenerate join code
create or replace function public.regenerate_join_code(p_company_id uuid)
returns text
language plpgsql
security definer
set search_path = public
as $$
declare
  code text;
begin
  if not public.is_platform_owner()
     and p_company_id not in (select public.admin_company_ids()) then
    raise exception 'FORBIDDEN';
  end if;
  code := upper(substr(encode(gen_random_bytes(6), 'hex'), 1, 6));
  update public.companies
    set join_code = code, join_code_updated_at = now()
  where id = p_company_id;
  return code;
end;
$$;

grant execute on function public.regenerate_join_code(uuid) to authenticated;
