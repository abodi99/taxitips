-- Bolagskoden slutar dela ut permanenta enhetstokens.
--
-- BAKGRUND. `public.join_device(p_join_code, p_label)` är SECURITY DEFINER,
-- körbar av `anon`, och skapar en rad i `devices` med en färsk token som
-- returneras i klartext. Bolagskoden är sex tecken, står på ett papper i
-- fikarummet och syns i administratörsvyn. Den som läser den får alltså en
-- permanent credential till betald data, och enda sättet att stänga den är att
-- byta kod -- vilket inte låser ut angriparen (token är redan utdelad) men
-- däremot varje förare som ska ansluta därefter.
--
-- EFTER DEN HÄR MIGRATIONEN får bolagskoden göra en enda sak: hitta företaget.
-- Godkännandet av en telefon sker genom Djangos parkopplingsflöde, där en
-- administratör väljer bil och skapar en engångskod med högst fem minuters
-- giltighet (POST /api/fleet/pairing-codes -> POST /api/fleet/pair).
--
-- REDAN PARKOPPLADE TELEFONER PÅVERKAS INTE. Inga rader i `devices` rörs, och
-- ingen token återkallas. Det enda som slutar fungera är att skapa NYA enheter
-- ur bolagskoden -- alltså precis hålet.
--
-- ÄLDRE APPVERSIONER som anropar RPC:n får ett begripligt svenskt felmeddelande
-- i stället för ett tyst misslyckande, så att föraren vet vad hen ska göra.
-- Appens force-upgrade-mekanism (Remote Config, lib/widgets/force_upgrade_overlay.dart)
-- är vägen att styra dem vidare.
--
-- ÅTERSTÄLLNING. Funktionen nedan ersätter en tidigare definition; hela den
-- gamla kroppen finns i 20260829000000_rpc_functions.sql och i
-- taxitips-backend/schema/functions.sql om den någonsin måste tillbaka. Inga
-- data ändras, så en återställning är att köra den gamla definitionen igen.
-- Gör inte det utan att först ha en ersättare för hålet.

create or replace function public.join_device(p_join_code text, p_label text default 'Förare')
returns json
language plpgsql
security definer
set search_path = public
as $function$
declare
  v_company public.companies;
begin
  -- Koden får bekräfta att företaget finns. Inget mer.
  select * into v_company from public.companies where join_code = upper(trim(p_join_code));

  if v_company is null then
    raise exception 'Ogiltig bolagskod'
      using errcode = 'P0002';
  end if;

  raise exception 'Bolagskoden ger inte längre åtkomst. Be din administratör om en anslutningskod i TaxiTips-portalen.'
    using errcode = 'P0001',
          hint = 'POST /api/fleet/join-request skapar en ansökan; administratören godkänner telefonen med en engångskod.';
end;
$function$;

comment on function public.join_device(text, text) is
  'Utfasad. Bolagskoden hittar företaget men delar inte ut credentials. '
  'Parkoppling sker via Djangos /api/fleet/pairing-codes och /api/fleet/pair.';

-- RÄTTIGHETERNA. `revoke ... from anon` ensamt räcker INTE: Postgres ger varje
-- ny funktion EXECUTE till PUBLIC, och `anon` ärver den vägen. Provat mot den
-- lokala instansen 2026-09-20 -- rollen kom igenom trots revoke. Därför tas
-- PUBLIC först, sedan de namngivna rollerna, och först därefter ges
-- rättigheten tillbaka till den enda som ska ha den.
revoke execute on function public.join_device(text, text) from public;
revoke execute on function public.join_device(text, text) from anon;
revoke execute on function public.join_device(text, text) from authenticated;

-- `authenticated` får kalla den, bara för att en inloggad administratör i en
-- äldre appversion ska få det förklarande felmeddelandet i stället för ett
-- rättighetsfel. `anon` -- förarens väg, och den som hålet gick genom -- får
-- det inte: där är en tyst stängd dörr rätt svar, och den nya vägen
-- (/api/fleet/join-request) har ett eget, begripligt meddelande.
grant execute on function public.join_device(text, text) to authenticated;
