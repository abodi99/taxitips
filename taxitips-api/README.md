# TaxiTips API (Supabase + worker)

Coolify service: **supabase-taxitips** (`kjrcb9ghbpegwyyxb05vjo66`) in project **taxitips** / env **production**, on server `abbe-worker` (192.168.0.7).

## Local dev

Requires Docker (Colima works: `brew install colima docker docker-compose && colima start`) and the Supabase CLI (`brew install supabase/tap/supabase`).

```bash
cd taxitips-api
supabase start   # applies every migration in supabase/migrations/ to a fresh local Postgres
supabase status  # prints local API_URL, ANON_KEY, SERVICE_ROLE_KEY, STUDIO_URL
```

Worker against local Supabase:

```bash
cd taxitips-api/worker
npm install
cp .env.local.example .env.local   # fill SUPABASE_SERVICE_ROLE_KEY from `supabase status`
set -a && source .env.local && set +a
node src/index.js
```

Flutter app against local Supabase:

```bash
cd taxitips-app
flutter run --dart-define=SUPABASE_URL=http://127.0.0.1:54321 --dart-define=SUPABASE_ANON_KEY=<local ANON_KEY from `supabase status`>
```

`supabase/migrations_historical/` holds two early migration files that described a schema
design that was never actually applied to production as written (confirmed schema drift —
see `TAXITIPS_STATUS.md`). `20260828999999_baseline_actual_schema.sql` is the real source of
truth for the schema shape and is what `supabase start` actually builds from.

`supabase stop` to tear the local stack down; `supabase stop --no-backup` to also wipe local data.

## Kong URL (default after create)

```
http://supabasekong-kjrcb9ghbpegwyyxb05vjo66.192.168.0.7.sslip.io:8000
```

Set a public HTTPS domain on the `supabase-kong` container in Coolify when ready (e.g. `https://sb.taxitips.se`).

## Client env

```bash
SUPABASE_URL=https://YOUR_KONG_HOST
SUPABASE_ANON_KEY=...   # from Coolify service env SERVICE_SUPABASEANON_KEY / ANON_KEY
```

Worker needs:

```bash
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
TRAFIKLAB_API_KEY=...
TRAFIKVERKET_API_KEY=...
STRIPE_SECRET_KEY=...
STRIPE_WEBHOOK_SECRET=...
POLL_INTERVAL_MS=60000
```

## Apply migrations

1. Open Studio: http://studio-taxitips.192.168.0.7.sslip.io (login = Coolify `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD`)
2. SQL Editor → paste [`supabase/ALL_MIGRATIONS.sql`](supabase/ALL_MIGRATIONS.sql) → Run
3. Or: `DATABASE_URL=... ./scripts/apply_migrations.sh`

## Client env

```bash
cd taxitips-api/worker
npm install
npm run start
```

Deploy worker as a Coolify **Application** (Dockerfile included) with the env above.
