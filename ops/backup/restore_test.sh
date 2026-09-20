#!/usr/bin/env bash
# Återställer en dump till en tillfällig Postgres av samma image som databasen
# och jämför radantal per tabell mot räkningen som togs vid dumpen.
#
#   ./restore_test.sh taxitips-20260913T120000Z.dump radantal-vid-dump.tsv [taxitips-20260913T120000Z.roles.sql]
#
# Radantalen tas fram med count_rows.sql. Tabeller som skrivs medan dumpen
# pågår (source_status, ais_vessels) kan skilja några rader; allt annat ska
# vara lika. Se ops/backup/README.md.
set -euo pipefail

DUMP="$1"
EXPECTED="$2"
ROLES="${3:-}"
IMAGE="${RESTORE_IMAGE:-public.ecr.aws/supabase/postgres:15.8.1.085}"
NAME="taxitips-restore-test-$$"
HERE="$(cd "$(dirname "$0")" && pwd)"
# supabase_admin äger Supabases egna scheman (auth, storage). Som postgres
# stoppas återställningen av dem på "must be owner" -- mätt 2026-09-13.
RESTORE_USER="${RESTORE_USER:-supabase_admin}"
PASSWORD="restore-test-$$"

cleanup() { docker rm -f "$NAME" > /dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$NAME" -e POSTGRES_PASSWORD="$PASSWORD" "$IMAGE" > /dev/null
for _ in $(seq 1 90); do
  if docker exec "$NAME" pg_isready -U postgres -h 127.0.0.1 > /dev/null 2>&1; then break; fi
  sleep 2
done
# Imagens egna init-skript kör efter att servern svarat första gången.
sleep 10

docker cp "$DUMP" "$NAME:/tmp/restore.dump"
# Rollerna först: pg_dump tar inte med dem, och utan dem stoppar ägarskap och
# rättigheter på "role does not exist". Roller som imagen redan har ger
# "already exists", vilket är väntat.
if [ -n "$ROLES" ]; then
  docker cp "$ROLES" "$NAME:/tmp/roles.sql"
  docker exec -e PGPASSWORD="$PASSWORD" "$NAME" psql -U "$RESTORE_USER" -h 127.0.0.1 -d postgres -f /tmp/roles.sql > /dev/null 2> "$NAME.roles.log" || true
fi
# --clean --if-exists: imagen har redan Supabases egna scheman och roller.
# Fel om objekt som redan finns är väntade och räknas, men stoppar inte testet.
set +e
docker exec -e PGPASSWORD="$PASSWORD" "$NAME" pg_restore -U "$RESTORE_USER" -h 127.0.0.1 -d postgres --no-owner --clean --if-exists /tmp/restore.dump \
  > /dev/null 2> "$NAME.errors.log"
set -e
echo "pg_restore: $(grep -c 'error:' "$NAME.errors.log" || true) felrader (se $NAME.errors.log)"

docker exec -i -e PGPASSWORD="$PASSWORD" "$NAME" psql -U "$RESTORE_USER" -h 127.0.0.1 -d postgres -At -F $'\t' < "$HERE/count_rows.sql" > "$NAME.restored.tsv"

python3 - "$EXPECTED" "$NAME.restored.tsv" <<'PY'
import sys

def load(path):
    rows = {}
    for line in open(path):
        if "\t" in line:
            table, n = line.rstrip("\n").split("\t")
            rows[table] = int(n)
    return rows

expected, restored = load(sys.argv[1]), load(sys.argv[2])
volatile = {"public.source_status", "public.ais_vessels", "public.ferry_arrivals"}
missing = sorted(t for t in expected if t not in restored)
differ = sorted((t, expected[t], restored[t]) for t in expected if t in restored and expected[t] != restored[t])
total = sum(expected.values())
print(f"tabeller: {len(expected)} vid dump, {len(restored)} återställda; rader vid dump: {total}")
for table in missing:
    print(f"  SAKNAS  {table}")
for table, a, b in differ:
    print(f"  {'skiljer (skrivs löpande)' if table in volatile else 'SKILJER'}  {table}: {a} -> {b}")
bad = missing or [t for t, _, _ in differ if t not in volatile]
print("ÅTERSTÄLLNING GODKÄND" if not bad else "ÅTERSTÄLLNING UNDERKÄND")
sys.exit(1 if bad else 0)
PY
