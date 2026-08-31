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
