#!/bin/sh
# TaxiTips: komprimerad pg_dump av hela databasen, kontrollerad innan den räknas
# som klar. Se ops/backup/README.md.
#
#   BACKUP_DIR=/backups KEEP=14 ./backup.sh
#   BACKUP_UPLOAD_CMD='rclone copy' BACKUP_UPLOAD_TARGET='remote:taxitips' ./backup.sh
#
# Anslutningen läses ur PG*-variablerna (PGHOST, PGUSER, PGPASSWORD, PGDATABASE)
# eller DATABASE_URL och skrivs aldrig ut.
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
KEEP="${KEEP:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
FILE="$BACKUP_DIR/taxitips-$STAMP.dump"
ROLES="$BACKUP_DIR/taxitips-$STAMP.roles.sql"

mkdir -p "$BACKUP_DIR"

# Custom-format: komprimerat, och pg_restore kan läsa innehållsförteckningen
# utan att återställa. Filen får sitt slutliga namn först när den gått igenom
# den kontrollen, så en avbruten dump aldrig ser ut som en backup.
if [ -n "${DATABASE_URL:-}" ]; then
  pg_dump --format=custom --file="$FILE.partial" "$DATABASE_URL"
else
  pg_dump --format=custom --file="$FILE.partial"
fi
pg_restore --list "$FILE.partial" > /dev/null
mv "$FILE.partial" "$FILE"

# Roller ligger utanför databasen och följer inte med pg_dump. Utan dem
# stoppar en återställning på "role does not exist" (mätt 2026-09-13:
# django_billing). Lösenord tas inte med; de sätts om vid återställning.
if [ -n "${DATABASE_URL:-}" ]; then
  pg_dumpall --roles-only --no-role-passwords --dbname="$DATABASE_URL" > "$ROLES"
else
  pg_dumpall --roles-only --no-role-passwords > "$ROLES"
fi
echo "backup klar: $(basename "$FILE") ($(du -h "$FILE" | cut -f1))"

# En backup på samma server som databasen skyddar inte mot att servern går
# förlorad. Utan uppladdning är den bara ett första steg.
if [ -n "${BACKUP_UPLOAD_CMD:-}" ]; then
  $BACKUP_UPLOAD_CMD "$FILE" "${BACKUP_UPLOAD_TARGET:?BACKUP_UPLOAD_TARGET saknas}"
  $BACKUP_UPLOAD_CMD "$ROLES" "$BACKUP_UPLOAD_TARGET"
  echo "uppladdad: $(basename "$FILE")"
else
  echo "VARNING: ingen extern kopia (BACKUP_UPLOAD_CMD saknas)" >&2
fi

# Gallra bara filer som det här skriptet skapat, äldst först.
ls -1t "$BACKUP_DIR"/taxitips-*.dump 2>/dev/null | tail -n +"$((KEEP + 1))" | while read -r old; do
  rm -f -- "$old" "${old%.dump}.roles.sql"
  echo "gallrad lokalt: $(basename "$old")"
done
