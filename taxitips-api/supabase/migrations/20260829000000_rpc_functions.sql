-- RPC functions used by taxitips-app/lib/api_client.dart, verified against production's real
-- function bodies via direct psql introspection (2026-09-01) and cross-checked against
-- taxitips-app/supabase/001_schema.sql, the untracked bootstrap script that appears to have
-- actually been run against production (its header comment states the exact PGRST205 symptom
-- this repo's own migrations would otherwise have left unfixed). These were previously not
-- present in any tracked migration file, so `supabase start` never created them locally even
-- though the Flutter app depends on all of them (join_screen.dart, driver_screen.dart, signup).

create or replace function public.regenerate_join_code(p_company_id uuid)
returns text
language plpgsql
security definer
set search_path = public
as $$
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
$$;

create or replace function public.join_device(p_join_code text, p_label text default 'Förare')
returns json
language plpgsql
security definer
set search_path = public
as $$
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
$$;

create or replace function public.device_by_token(p_token text)
returns json
language plpgsql
security definer
set search_path = public
as $$
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
$$;

grant execute on function public.regenerate_join_code(uuid) to authenticated;
grant execute on function public.join_device(text, text) to anon, authenticated;
grant execute on function public.device_by_token(text) to anon, authenticated;

-- Auto-create a profile row whenever a new auth user is created.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, name)
  values (new.id, new.raw_user_meta_data ->> 'name')
  on conflict (id) do nothing;
  return new;
end;
$$;

drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();
