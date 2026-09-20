# Backup och återställning

**Läge 2026-09-13:** skripten finns och återställningen är provad mot den lokala
utvecklingsdatabasen (se *Senaste prov*). **Ingen backup är schemalagd i
produktion.** Det kräver extern lagring och ett beslut, och ingår inte i P0-arbetet
i utveckling.

## Innehåll

| Fil | Gör |
|---|---|
| `backup.sh` | `pg_dump` i custom-format → `pg_restore --list` som kontroll → extern kopia via `BACKUP_UPLOAD_CMD` → gallrar skriptets **egna** äldre filer (`KEEP`, standard 14) |
| `count_rows.sql` | Radantal per tabell i `public` och `auth`, tabbseparerat |
| `restore_test.sh` | Återställer en dump i en tillfällig container av samma image och jämför radantal mot räkningen vid dumpen |

## Varför inte Coolifys backupfunktion

Coolifys API för databasbackuper når inte en databas inuti en tjänst: för
`supabase-db` i `supabase-taxitips` svarade det "Database not found". Varken
schemalagda uppgifter eller pg_cron-jobb fanns 2026-09-13.

## Produktion (att göra, kräver beslut)

1. **Extern lagring** utanför servern, t.ex. en S3-kompatibel bucket hos en annan
   leverantör. En kopia på samma server skyddar inte mot att servern går förlorad.
2. **Kör där databasen nås internt**, med `pg_dump` 15: som schemalagd uppgift i
   tjänsten `supabase-taxitips` på containern `supabase-db`, eller i en separat
   backup-container i samma nätverk. Aldrig via den publika porten 5432.
3. **Lösenord via miljön** (`PGPASSWORD` eller `DATABASE_URL`), aldrig på
   kommandoraden eller i en logg.
4. **Återställ den första backupen** med `restore_test.sh` på servern innan den
   räknas som verifierad.
5. **Innan gallringen `purge-old` körs mot produktion första gången:** en
   verifierad backup.

## Återställning vid incident

1. Stoppa worker, beat och AIS-lyssnaren så att inget skrivs.
2. Återställ till en **ny** databas, aldrig över den som kör:
   `pg_restore --no-owner -d <ny databas> <fil>`.
3. Jämför radantal med `count_rows.sql` mot den senaste räkningen.
4. Peka om `DATABASE_URL` och starta tjänsterna igen. Behåll den gamla databasen tills
   flödet och notiserna är kontrollerade.

## Lokalt prov

```sh
# 1. Radantal, dump och roller från den lokala Supabase-databasen (samma image som produktion)
docker exec -i supabase_db_taxitips psql -U postgres -At -F $'\t' < ops/backup/count_rows.sql > /tmp/radantal.tsv
docker exec supabase_db_taxitips pg_dump -U postgres --format=custom postgres > /tmp/taxitips.dump
docker exec supabase_db_taxitips pg_dumpall -U postgres --roles-only --no-role-passwords > /tmp/roles.sql

# 2. Återställ i en tillfällig container och jämför
ops/backup/restore_test.sh /tmp/taxitips.dump /tmp/radantal.tsv /tmp/roles.sql
```

Två saker provet lärde oss, båda inbyggda i skripten nu:

- **Återställ som `supabase_admin`, inte `postgres`.** Som `postgres` stoppades
  Supabases egna scheman på "must be owner": 18 auth-tabeller saknades och
  `auth.users` blev tom.
- **Roller följer inte med `pg_dump`.** Utan `pg_dumpall --roles-only` stoppade
  återställningen på "role does not exist" (`django_billing`,
  `supabase_functions_admin`). `backup.sh` sparar därför en rollfil bredvid dumpen.

## Senaste prov

**2026-09-13, lokal utvecklingsdatabas** (`supabase/postgres:15.8.1.085`, samma
version som produktionen): dump 6,1 MB, 14 roller. Återställd i en tom container:
**61 av 61 tabeller, 59 076 rader, alla radantal lika.** En kvarvarande felrad:
`graphql_public.graphql(...)` saknas i den tomma imagen, vilket inte rör TaxiTips data.

Inte provat: backup och återställning mot produktionsdatabasen, och extern lagring.
