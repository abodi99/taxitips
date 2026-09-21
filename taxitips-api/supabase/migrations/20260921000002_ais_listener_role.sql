-- En egen databasroll för AISStream-lyssnaren (taxitips-backend, APP_ROLE=ais).
--
-- Lyssnaren är den första processen som INTE ansluter som tabellägaren postgres
-- (CLAUDE.md, regel 4: minsta möjliga rättighet). Den får skriva fartyg, färjeanlöp,
-- sina egna tips och sin källstatus -- inget annat. Bolag, enheter, abonnemang,
-- licenser och notiser når den inte.
--
-- Rollen skapas här UTAN inloggning och utan lösenord: lösenordet hör inte hemma i
-- versionshanteringen. I en miljö där lyssnaren ska köra sätts det för hand:
--
--   alter role taxitips_ais login password '<slumpat>';
--
-- och samma lösenord läggs i lyssnarappens DATABASE_URL i Coolify.
--
-- Tabellerna skapas av Djangos migrationer, som kan köra efter den här filen i en
-- tom databas. Därför hoppas de tabeller som ännu inte finns över; kör filen igen
-- efter `manage.py migrate` i en sådan miljö. Allt i filen tål att köras flera gånger.

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'taxitips_ais') then
    create role taxitips_ais nologin;
  end if;
end $$;

grant usage on schema public to taxitips_ais;

do $$
declare
  t text;
begin
  -- Läser och skriver.
  foreach t in array array[
    'ais_vessels', 'ferry_arrivals', 'ferry_calls', 'source_events', 'opportunities', 'source_status'
  ]
  loop
    if to_regclass(format('public.%I', t)) is not null then
      execute format('grant select, insert, update on table public.%I to taxitips_ais', t);
    end if;
  end loop;

  -- Läser bara: färjornas tidtabell.
  if to_regclass('public.ferry_timetable_calls') is not null then
    grant select on table public.ferry_timetable_calls to taxitips_ais;
  end if;

  -- Djangos BigAutoField-id:n i maritime-tabellerna.
  foreach t in array array['ais_vessels', 'ferry_arrivals', 'ferry_calls', 'source_status']
  loop
    if exists (select 1 from information_schema.columns
               where table_schema = 'public' and table_name = t and column_name = 'id')
       and pg_get_serial_sequence(format('public.%I', t), 'id') is not null then
      execute format('grant usage, select on sequence %s to taxitips_ais',
                     pg_get_serial_sequence(format('public.%I', t), 'id'));
    end if;
  end loop;

  -- source_events och opportunities har RLS på. Rollen är varken ägare eller
  -- bypassrls, så den behöver egna policyer -- avgränsade till just den här rollen.
  foreach t in array array['source_events', 'opportunities']
  loop
    if to_regclass(format('public.%I', t)) is not null then
      execute format('drop policy if exists ais_listener_rw on public.%I', t);
      execute format(
        'create policy ais_listener_rw on public.%I for all to taxitips_ais using (true) with check (true)', t
      );
    end if;
  end loop;
end $$;
