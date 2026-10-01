# Expand: ort och bolagsform på CRM-konton för filter i pipelinen.
# Additivt med databas-default — kod utan kännedom om kolumnerna fungerar
# fortfarande. Fylls via `manage.py import_sales_list` (idempotent).

from django.db import migrations, models


# Tabellen är redan stängd för PostgREST (0015); körs igen så att även de
# nya kolumnerna garanterat saknar grants för anon/authenticated.
REVOKE = """
do $$
declare
  r text;
begin
  foreach r in array array['anon', 'authenticated'] loop
    if not exists (select 1 from pg_roles where rolname = r) then
      continue;
    end if;
    if to_regclass('public.fleet_crm_account') is not null then
      execute format('revoke all on table public.fleet_crm_account from %I', r);
    end if;
  end loop;
end $$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("fleet", "0016_crm_tags"),
    ]

    operations = [
        migrations.AddField(
            model_name="crmaccount",
            name="city",
            field=models.CharField(blank=True, db_default="", default="", max_length=100),
        ),
        migrations.AddField(
            model_name="crmaccount",
            name="legal_form",
            field=models.CharField(blank=True, db_default="", default="", max_length=64),
        ),
        migrations.RunSQL(REVOKE, reverse_sql=migrations.RunSQL.noop),
    ]
