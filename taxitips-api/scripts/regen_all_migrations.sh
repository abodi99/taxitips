#!/usr/bin/env bash
# Regenerates supabase/ALL_MIGRATIONS.sql from supabase/migrations/*.sql in filename order.
# Run this after adding a new migration file, and commit the updated ALL_MIGRATIONS.sql
# alongside it. This file is the documented path for applying schema via Supabase Studio's
# SQL Editor in environments where the Supabase CLI isn't used.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MIGDIR="$SCRIPT_DIR/../supabase/migrations"
OUT="$SCRIPT_DIR/../supabase/ALL_MIGRATIONS.sql"

{
  echo "-- GENERATED FILE — do not edit directly."
  echo "-- Regenerate with taxitips-api/scripts/regen_all_migrations.sh after adding a migration."
  echo "-- Concatenation of taxitips-api/supabase/migrations/*.sql in filename order."
  echo "--"
  echo "-- NOTE: the original 20260823000001_init_saas.sql and 20260823000002_rls.sql described a"
  echo "-- schema design that was never actually applied to production as written (confirmed schema"
  echo "-- drift, see TAXITIPS_STATUS.md). They were moved to supabase/migrations_historical/ and"
  echo "-- are not part of this file. 20260828999999_baseline_actual_schema.sql documents the real"
  echo "-- production shape and is the source of truth for standing up a fresh (e.g. local dev) DB."
  echo ""
  for f in "$MIGDIR"/*.sql; do
    echo "-- ===== $(basename "$f") ====="
    cat "$f"
    echo ""
  done
} > "$OUT"

echo "Regenerated $OUT ($(wc -l < "$OUT") lines)"
