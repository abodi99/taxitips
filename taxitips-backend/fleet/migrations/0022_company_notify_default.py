# Expand: företagets standard för notiserna (fleet/notify_settings.py). Bara en
# ny tabell; inget befintligt ändras. Koden som läser den tål att den saknas
# (pairing ska aldrig falla på en standard), men portalens och adminwebbens
# "Standard för nya telefoner" kräver den.

from django.db import migrations, models

# Aldrig via PostgREST (invariant 19, samma skäl som 0003, 0019 och 0021).
REVOKE = """
do $$
declare
  r text;
begin
  foreach r in array array['anon', 'authenticated'] loop
    if not exists (select 1 from pg_roles where rolname = r) then
      continue;
    end if;
    if to_regclass('public.fleet_company_notify_default') is not null then
      execute format('revoke all on table public.fleet_company_notify_default from %I', r);
    end if;
  end loop;
end $$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('fleet', '0021_county_changes'),
    ]

    operations = [
        migrations.CreateModel(
            name='CompanyNotifyDefault',
            fields=[
                ('company_id', models.UUIDField(primary_key=True, serialize=False)),
                ('prefs', models.JSONField(blank=True, default=dict)),
                ('updated_at', models.DateTimeField()),
                ('updated_by', models.UUIDField(blank=True, null=True)),
            ],
            options={
                'db_table': 'fleet_company_notify_default',
            },
        ),
        migrations.RunSQL(sql=REVOKE, reverse_sql=migrations.RunSQL.noop),
    ]
