#!/usr/bin/env bash
# Apply TaxiTips SQL migrations to Coolify Supabase Postgres.
# Usage:
#   export DATABASE_URL='postgresql://postgres:PASSWORD@HOST:5432/postgres'
#   ./scripts/apply_migrations.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${DATABASE_URL:?Set DATABASE_URL to the Coolify supabase-db connection string}"

for f in "$ROOT"/supabase/migrations/*.sql; do
  echo "==> $f"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"
done
echo "Done."
