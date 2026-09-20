"""
Inga av kundlivscykelns tabeller får nås via PostgREST.

**Varför den här migrationen finns trots 20260913000003.** Den
Supabase-migrationen satte `alter default privileges ... revoke all` för rollen
postgres, vilket gör att nya Django-tabeller INTE automatiskt får rättigheter
för anon och authenticated. Verifierat mot den lokala instansen 2026-09-20:
ingen av de 23 fleet-tabellerna hade någon rättighet för de rollerna.

Men den migrationen är inte nödvändigtvis körd överallt, och ett `alter default
privileges` gäller bara tabeller som skapas EFTER det. En tabell som skapas i
en miljö utan den får Supabases standard: anon och authenticated med full
rättighet. De här tabellerna bär hashade credentials, beställningar och
revisionslogg -- att lita på att en annan migration har körts först är inte en
säkerhetsdesign.

Revoken är idempotent och ofarlig att köra två gånger. Django ansluter som
tabellägaren och påverkas inte.

Ingen RLS-policy behövs: tabellerna är inte avsedda att nås direkt av någon
klient. All läsning går genom Djangos vyer, som kontrollerar behörigheten i
Python (fleet/access.py).
"""

from django.db import migrations

TABLES = [
    "fleet_audit_event", "fleet_change_review", "fleet_company_profile",
    "fleet_device_approval", "fleet_device_credential", "fleet_join_request",
    "fleet_license", "fleet_license_county", "fleet_order", "fleet_outbox_message",
    "fleet_ownership_transfer", "fleet_pairing_code", "fleet_pending_change",
    "fleet_price_version", "fleet_risk_config", "fleet_risk_signal",
    "fleet_sales_invite", "fleet_staff_role", "fleet_subscription", "fleet_trial",
    "fleet_vehicle", "fleet_vehicle_assignment", "fleet_vehicle_session",
]

REVOKE = """
do $$
declare
  t text;
  r text;
begin
  foreach r in array array['anon', 'authenticated'] loop
    -- Rollerna finns i Supabase men inte i en naken Postgres. En saknad roll
    -- är inte ett fel här; då finns det heller ingen rättighet att ta bort.
    if not exists (select 1 from pg_roles where rolname = r) then
      continue;
    end if;
    foreach t in array array[%s] loop
      if to_regclass(format('public.%%I', t)) is not null then
        execute format('revoke all on table public.%%I from %%I', t, r);
      end if;
    end loop;
  end loop;
end $$;
""" % ", ".join(f"'{table}'" for table in TABLES)


class Migration(migrations.Migration):
    dependencies = [("fleet", "0002_seed_price_version")]
    operations = [
        migrations.RunSQL(REVOKE, reverse_sql=migrations.RunSQL.noop),
    ]
