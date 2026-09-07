-- Körs EN GÅNG, manuellt, mot supabase starts lokala Postgres-instans --
-- INNAN SUPABASE_DATABASE_URL tas i bruk (annars ett rent autentiserings-
-- fel). Skapar en skopad roll med GRANT på exakt de tre tabeller
-- billing-appen rör, i stället för att återanvända SUPABASE_SERVICE_ROLE_KEY
-- (full RLS-bypass) för ännu en skrivväg -- det uppfyller direkt CLAUDE.md:s
-- redan uttalade krav på en lägst-privilegie-roll för worker-/apptrafik.
--
-- ALDRIG mot produktion utan en pg_dump-backup i samma session först
-- (CLAUDE.md:s MCP-regel) -- gäller inte här, det här är lokalt.

CREATE ROLE django_billing LOGIN PASSWORD 'django_billing';

GRANT SELECT, INSERT, UPDATE ON public.companies TO django_billing;
GRANT SELECT, INSERT, UPDATE ON public.devices TO django_billing;
GRANT SELECT, INSERT, UPDATE ON public.processed_webhook_events TO django_billing;

-- Krävs specifikt eftersom processed_webhook_events har RLS aktiverat med
-- noll policies (20260901000001_processed_webhook_events.sql) -- en bar
-- GRANT räcker inte, allt returnerar tyst 0 rader / misslyckas annars.
-- (companies/devices saknar RLS idag, så ingen motsvarande policy behövs
-- där än -- om RLS någonsin aktiveras på dem senare behöver den här rollen
-- matchande policies då.)
CREATE POLICY django_billing_full_access ON public.processed_webhook_events
  FOR ALL TO django_billing USING (true) WITH CHECK (true);
