-- Två hål som låg kvar efter 20260920000002, hittade vid granskning mot
-- produktionen 2026-09-21. Den här filen speglar exakt det som applicerades
-- för hand i produktionen samma natt -- den finns för att läget ska gå att
-- återskapa, inte för att köras en gång till (allt är idempotent ändå).
--
-- 1. ÖVERTAGANDE AV VILKET BOLAG SOM HELST.
--    Policyn `company_members_insert_own` (äldre, inte från någon migration i
--    repot) tillät `INSERT ... WITH CHECK (user_id = auth.uid())` -- alltså att
--    lägga in SIG SJÄLV som medlem i ett godtyckligt bolag. RLS-policyer
--    OR:as, så den upphävde den striktare `cm_ins`. Registrering är öppen,
--    så "inloggad användare" betyder "vem som helst": lägg in dig som
--    company_owner i ett främmande bolag och läs dess förartokens,
--    parkoppla telefoner och säg upp abonnemanget.
--
-- 2. GRATIS BETALD ÅTKOMST.
--    `companies_insert_authenticated` (with check true) och
--    `companies_update_own`/`_member` lät klienten sätta
--    `subscription_status='active'` på sitt eget bolag. Den gamla
--    åtkomstregeln läser just det fältet. En trigger tvingar nu
--    betalfälten till serverns värden för klientroller.
--
-- Rekursion: en policy på company_members som frågar company_members ger
-- "infinite recursion detected in policy". `my_company_ids()` är SECURITY
-- DEFINER och läser därför förbi RLS -- det är hela skälet till att den finns.

create or replace function public.my_company_ids()
returns setof uuid
language sql stable security definer
set search_path = public
as $$
  select company_id from company_members
  where user_id = auth.uid() and status = 'active'
$$;

-- Medlemmar ser medlemmarna i sina egna bolag.
drop policy if exists cm_sel on public.company_members;
create policy cm_sel on public.company_members
  for select to authenticated
  using (company_id in (select public.my_company_ids()));

-- Hålet (1): bort med den tillåtande insert-policyn.
drop policy if exists company_members_insert_own on public.company_members;

-- Kvar: man får bara lägga in sig själv i ett bolag som ännu saknar
-- medlemmar -- det man just skapat vid registrering. Rätt fix på sikt är att
-- flytta registreringen till Django, där behörigheten kontrolleras i Python.
drop policy if exists cm_ins on public.company_members;
create policy cm_ins on public.company_members
  for insert to authenticated
  with check (
    user_id = auth.uid()
    and company_id not in (select company_id from public.company_members)
  );

drop policy if exists dev_sel on public.devices;
create policy dev_sel on public.devices
  for select to authenticated
  using (company_id in (select public.my_company_ids()));

-- Hålet (2): klienten sätter aldrig betalstatus.
create or replace function public.companies_protect_billing()
returns trigger
language plpgsql
as $fn$
begin
  -- Stripe-webhooken och Django skriver som service_role/postgres och
  -- påverkas inte. Bara PostgREST-klienterna (anon/authenticated) låses.
  if current_user in ('authenticated', 'anon') then
    if tg_op = 'INSERT' then
      new.status := 'trial';
      new.subscription_status := 'inactive';
      new.stripe_customer_id := null;
      new.stripe_subscription_id := null;
    else
      new.status := old.status;
      new.subscription_status := old.subscription_status;
      new.stripe_customer_id := old.stripe_customer_id;
      new.stripe_subscription_id := old.stripe_subscription_id;
      new.seats := old.seats;
    end if;
  end if;
  return new;
end
$fn$;

drop trigger if exists companies_protect_billing on public.companies;
create trigger companies_protect_billing
  before insert or update on public.companies
  for each row execute function public.companies_protect_billing();

-- Återställning: `drop trigger companies_protect_billing on public.companies`
-- och återskapa `company_members_insert_own`. Gör inte det senare -- det är
-- övertagandehålet.
