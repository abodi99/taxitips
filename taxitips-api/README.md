# TaxiTips API (Supabase + worker)

Coolify service: **supabase-taxitips** (`kjrcb9ghbpegwyyxb05vjo66`) in project **labb** / env **production**.

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
