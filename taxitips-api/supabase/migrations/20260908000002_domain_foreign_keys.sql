-- De främmande nycklar domäntabellerna aldrig fick.
--
-- Upptäckt när ett riktigt konto skulle logga in i appen: `me()` hämtar
-- bolaget genom PostgREST-inbäddning,
--
--     company_members?select=role,status,company:companies(id,name,...)
--
-- och PostgREST vägrar bädda in utan en deklarerad relation. Svaret blev
-- PGRST200 "Searched for a foreign key relationship ... in the schema
-- cache", appen föll tillbaka på sin degraderade väg, och en inloggad
-- ägare såg "Inget bolag" trots ett giltigt medlemskap.
--
-- Utan nycklarna kan dessutom ett medlemskap eller en enhet peka på ett
-- bolag som inte finns. Verifierat innan migrationen: noll föräldralösa
-- rader i båda tabellerna, så ingen städning behövs först.
--
-- Rent additivt (expand-steget). Kör ändå INTE mot produktion utan en
-- pg_dump i samma session -- en ALTER TABLE tar ett kort lås, och
-- constraint-valideringen läser hela tabellen.

alter table public.company_members
  add constraint company_members_company_id_fkey
  foreign key (company_id) references public.companies (id) on delete cascade;

alter table public.company_members
  add constraint company_members_user_id_fkey
  foreign key (user_id) references auth.users (id) on delete cascade;

-- Enheterna: en förartelefon utan bolag kan inte bedömas av
-- current_entitlement() -- den joinar devices -> companies och får noll
-- rader, vilket ser ut som "obetald" i stället för "trasig data".
alter table public.devices
  add constraint devices_company_id_fkey
  foreign key (company_id) references public.companies (id) on delete cascade;

-- PostgREST cachar schemat och upptäcker inte nya relationer av sig själv.
notify pgrst, 'reload schema';
