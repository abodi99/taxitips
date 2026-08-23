-- TaxiTips SaaS schema (Postgres / Supabase)
-- Migrated from skane-storingar SQLite SaaS + devices JSON

create extension if not exists "pgcrypto";

-- Profiles extend auth.users
create table if not exists public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  email text not null,
  name text not null default '',
  status text not null default 'active',
  is_platform_owner boolean not null default false,
  created_at timestamptz not null default now(),
  deleted_at timestamptz
);

create table if not exists public.billing_accounts (
  id uuid primary key default gen_random_uuid(),
  owner_type text not null check (owner_type in ('user', 'company')),
  owner_id uuid not null,
  billing_provider text not null default 'stripe',
  stripe_customer_id text,
  legal_name text,
  vat_id text,
  billing_email text,
  billing_address_json jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create unique index if not exists idx_billing_owner
  on public.billing_accounts (owner_type, owner_id);
create index if not exists idx_billing_stripe
  on public.billing_accounts (stripe_customer_id);

create table if not exists public.companies (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  email text not null,
  org_number text,
  company_info_json jsonb not null default '{}'::jsonb,
  seats integer not null default 1,
  status text not null default 'trial',
  trial_ends_at timestamptz,
  stripe_customer_id text,
  stripe_subscription_id text,
  watched_areas jsonb not null default '[]'::jsonb,
  join_code text,
  join_code_updated_at timestamptz,
  billing_account_id uuid references public.billing_accounts (id),
  admin_notes text,
  created_at timestamptz not null default now()
);

create unique index if not exists idx_companies_email on public.companies (lower(email));
create unique index if not exists idx_companies_join_code on public.companies (join_code);
create index if not exists idx_companies_stripe_customer on public.companies (stripe_customer_id);

create table if not exists public.company_members (
  company_id uuid not null references public.companies (id) on delete cascade,
  user_id uuid not null references public.profiles (id) on delete cascade,
  role text not null check (role in ('company_owner', 'company_admin', 'driver')),
  status text not null default 'active',
  joined_at timestamptz not null default now(),
  primary key (company_id, user_id)
);

create index if not exists idx_members_user on public.company_members (user_id);

create table if not exists public.subscriptions (
  id uuid primary key default gen_random_uuid(),
  billing_account_id uuid not null references public.billing_accounts (id) on delete cascade,
  stripe_subscription_id text,
  stripe_price_id text,
  plan text,
  status text not null default 'none',
  quantity integer not null default 1,
  trial_ends_at timestamptz,
  current_period_end timestamptz,
  cancel_at_period_end boolean not null default false,
  grace_until timestamptz,
  raw_stripe_json jsonb,
  updated_at timestamptz not null default now()
);

create unique index if not exists idx_subs_stripe on public.subscriptions (stripe_subscription_id);

create table if not exists public.devices (
  id uuid primary key default gen_random_uuid(),
  company_id uuid not null references public.companies (id) on delete cascade,
  token text not null unique,
  label text not null default 'Förare',
  push_token text,
  notify_prefs jsonb not null default '{}'::jsonb,
  last_seen_at timestamptz,
  created_at timestamptz not null default now()
);

create index if not exists idx_devices_company on public.devices (company_id);

create table if not exists public.device_transfer_codes (
  code text primary key,
  device_id uuid not null references public.devices (id) on delete cascade,
  expires_at timestamptz not null,
  created_at timestamptz not null default now()
);

create table if not exists public.processed_webhook_events (
  stripe_event_id text primary key,
  event_type text not null,
  processed_at timestamptz not null default now(),
  status text not null,
  error text
);

create table if not exists public.app_config (
  key text primary key,
  value text not null,
  updated_at timestamptz not null default now()
);

-- Tips / disturbances written by worker
create table if not exists public.alerts (
  id text primary key,
  kind text not null default 'traffic',
  level text not null default 'medium',
  title text not null,
  summary text,
  lat double precision,
  lon double precision,
  places jsonb not null default '[]'::jsonb,
  payload jsonb not null default '{}'::jsonb,
  starts_at timestamptz,
  ends_at timestamptz,
  updated_at timestamptz not null default now(),
  created_at timestamptz not null default now()
);

create index if not exists idx_alerts_updated on public.alerts (updated_at desc);
create index if not exists idx_alerts_kind on public.alerts (kind);

create table if not exists public.tickets (
  id uuid primary key default gen_random_uuid(),
  company_id uuid references public.companies (id) on delete set null,
  subject text not null,
  body text not null default '',
  status text not null default 'open',
  created_by uuid references public.profiles (id),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

-- Auto-create profile on signup
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, email, name)
  values (
    new.id,
    coalesce(new.email, ''),
    coalesce(new.raw_user_meta_data->>'name', '')
  )
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- Helpers
create or replace function public.is_platform_owner()
returns boolean
language sql
stable
security definer
set search_path = public
as $$
  select coalesce(
    (select is_platform_owner from public.profiles where id = auth.uid()),
    false
  );
$$;

create or replace function public.member_company_ids()
returns setof uuid
language sql
stable
security definer
set search_path = public
as $$
  select company_id
  from public.company_members
  where user_id = auth.uid() and status = 'active';
$$;

create or replace function public.admin_company_ids()
returns setof uuid
language sql
stable
security definer
set search_path = public
as $$
  select company_id
  from public.company_members
  where user_id = auth.uid()
    and status = 'active'
    and role in ('company_owner', 'company_admin');
$$;
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
