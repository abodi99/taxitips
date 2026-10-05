# Kopplingar – lokalt och i produktion

För kodagenter som ska arbeta i projektet. Inga hemligheter står här, bara var de
finns och hur man når saker. Kontrollerat 2026-10-04.

## Lokalt (utveckling på Macen)

**Docker**: Colima (`colima start`). Utan Colima finns ingen lokal databas, och
testerna faller med `connection refused` på 54322.

**Supabase lokalt** (`taxitips-api/`, `supabase start`, project_id `taxitips`):

| Tjänst | Adress |
|---|---|
| API (Kong: auth, rest) | http://127.0.0.1:54321 |
| Postgres | 127.0.0.1:54322, användare `postgres` (Djangos `DATABASE_URL`) |
| Studio | http://127.0.0.1:54323 |

**Django-backend** (`taxitips-backend/`): `.env` (gitignorerad) pekar på den lokala
Supabase: `DATABASE_URL=postgresql://postgres:…@127.0.0.1:54322/postgres` och
`SUPABASE_URL=http://127.0.0.1:54321`. Där finns också API-nycklarna för källorna
(Trafiklab, Trafikverket, Västtrafik, Swedavia, Resrobot, AISstream,
Ticketmaster, PredictHQ, API-Sports, Bolagsverket), Gemini, Stripe (test), Firebase
och `CELERY_TASK_ALWAYS_EAGER=1`. Kör med `./.venv/bin/python manage.py …`.

- **Tester**: `CELERY_TASK_ALWAYS_EAGER=1 ./.venv/bin/python manage.py test`. Hela
  sviten var grön 2026-10-04 (1338 tester).
- **Testdatabasen**: Djangos testrunner skapar `test_postgres` i samma Postgres.

**Webben** (`taxitips-web/`): kör med `npm run dev` (Vite, `http://127.0.0.1:5173`).

- **Mot produktion (vanligast för portal/admin-UI):** `.env.local` med
  `VITE_SUPABASE_URL=https://api.taxitips.se`, produktionens anon-nyckel och
  `VITE_API_BASE_URL=https://backend.taxitips.se`. Backendens
  `APP_API_ALLOWED_ORIGINS` måste innehålla `http://127.0.0.1:5173` och
  `http://localhost:5173`.
- **Full lokal stack:** `.env` med `VITE_SUPABASE_URL=http://127.0.0.1:54321`
  och `VITE_API_BASE_URL=http://127.0.0.1:8000`, plus `supabase start` och
  Django på :8000. Ta bort `.env.local` så den inte vinner över `.env`.
  Standardvärdet i `src/config.js` (när variablerna saknas) är
  `https://api.taxitips.se` + `https://backend.taxitips.se`.

**Appen** (`taxitips-app/`): `dart_defines.local.json` (gitignorerad) har
`API_BASE_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `CARTO_KEY` och
`GOOGLE_MAPS`. Den pekar idag på **produktionen** (`https://backend.taxitips.se`
och `https://api.taxitips.se`). Bygg med
`flutter build apk --debug --dart-define-from-file=dart_defines.local.json`.
Testtelefonen är en Samsung SM-S906B på trådlös adb. Paketet heter `se.taxitips.app`.
Ett debugbygge går att installera ovanpå appen som redan finns på telefonen; ett
releasebygge har annan signatur och gör det inte.

## Produktion

| Del | Var |
|---|---|
| Server | Hostinger VPS `srv2013632` (179.198.213.14), Coolify på https://coolify.taxitips.se |
| Django-backend | https://backend.taxitips.se (Coolify-app `taxitips-backend`) |
| Celery | `taxitips-celery-worker` (insamling, push, utkorg) och `taxitips-celery-beat` |
| Webb | `taxitips-web`: taxitips.se, admin.taxitips.se, portal.taxitips.se |
| Supabase (Auth, Postgres, Kong) | https://api.taxitips.se (Coolify-tjänst `supabase-taxitips`) |
| Mejl | smtp.hostinger.com, avsändare hej@taxitips.se (Django-utkorgen och Supabase Auth) |
| Push | Firebase-projektet `taxitips-se` (FCM). iOS behöver en APNs-nyckel i Firebase. |
| Betalning | Stripe live, webhook till backend.taxitips.se/billing/stripe/webhook |

**Produktionens detaljer** finns i en privat fil på ägarens Mac, **utanför repot**:
`~/.taxitips/prod.md` (chmod 600). Den innehåller Coolify-apparnas uuid:er, containrarna,
alla variabelnamn per app och var varje hemlighet ligger, plus ägarens egna anteckningar.
Läs den när du behöver den. Kopiera aldrig innehållet in i repot, en chatt eller ett ärende.
Hemligheternas källa är Coolify, och värden ändras av ägaren i gränssnittet.

Kortversionen av driften:

- **SSH**: `ssh -i ~/.ssh/taxitips_deploy -o IdentitiesOnly=yes root@179.198.213.14`.
  Nyckeln är kopplad till VPS:en i hPanel.
- **Push driftsätter inte** (webhooken är trasig).
- **Deploy**:
  - Läs först läget ur `ApplicationDeploymentQueue`.
  - Köa sedan med `docker exec coolify php artisan tinker` och
    `queue_application_deployment(..., commit: '<sha>')`.
  - En app i taget: backend → worker → beat → webb.
- **Migreringar körs inte vid deploy**:
  1. Ta en säkerhetskopia (`pg_dump` i `supabase-db-…` till `/root/backups/`).
  2. Kör `sqlmigrate`-SQL:en via den hostade Supabase-kopplingen.
  3. Lägg in raden i `django_migrations`.
  4. Kontrollera att antalet migreringar i repot och i `django_migrations` stämmer.
- **Supabase startas om bara från Coolify-gränssnittet.** En omstart via API har
  stoppat allt, databasen inräknad.
- **Lagrade hemligheter i Coolify** ändras av ägaren i gränssnittet. "Deployment
  failed: The payload is invalid" betyder att en variabel sparats okrypterat.

## Verktyg (MCP) som är kopplade till projektet

- `taxitips-selfhosted`: Supabase-MCP mot produktionen (https://api.taxitips.se/mcp).
  Samma databas nås också via claude.ai-kopplingen "taxitips mcp" (`execute_sql` m.fl.).
- `coolify`: **pekar fortfarande på labbet** (192.168.0.7), inte på produktionen.
  Använd SSH för produktionen.
- `hostinger`: VPS:en (snapshots, nycklar). Snapshot har bara en plats, och en ny
  skriver över den förra.
- `stripe-remote`: Stripe. Riktiga belopp kräver ägarens uttryckliga ja i chatten.
- `firebase`: Firebase-projektet `taxitips-se`.
- `twenty-taxitips`: Twenty-CRM (säljlistan).
- `github`: repot `abodi99/taxitips`, gren `fas2-django-pipeline`.
- Övriga för ägarens andra projekt: `n8n-mcp`, `postiz`, `openclaw`, `hermes`,
  `metamcp`, Canva.

## Att känna till

- **Flera sessioner** arbetar ibland samtidigt i huvudcheckouten. Arbeta i en egen
  worktree (`.claude/worktrees/…`, gitignorerad), inte i `/private/tmp`, som töms
  vid omstart. Pusha direkt efter varje commit. Använd aldrig `git stash` utan namn.
- **Disken** på Macen är nästan full. Gradle-cachen (`~/.gradle/caches`) och
  `taxitips-app/build` kan tas bort; de återskapas.
- **Butiksrelease**: se `docs/release-checklist.md`.
- **Mejlmallar och Supabase Auth**: se `docs/auth-mejl.md`.
