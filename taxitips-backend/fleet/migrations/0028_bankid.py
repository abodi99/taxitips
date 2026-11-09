from django.db import migrations, models

# Invariant 19: Djangos tabeller nås aldrig via PostgREST. BankID-identiteten
# bär en nyckel till personnumret och får inte vara läsbar för anon/authenticated.
REVOKE_NEW_TABLES = """
do $$
declare
  t text;
  r text;
begin
  foreach r in array array['anon', 'authenticated'] loop
    if not exists (select 1 from pg_roles where rolname = r) then
      continue;
    end if;
    foreach t in array array['fleet_bankid_identity', 'fleet_bankid_order'] loop
      if to_regclass(format('public.%I', t)) is not null then
        execute format('revoke all on table public.%I from %I', t, r);
      end if;
    end loop;
  end loop;
end $$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("fleet", "0027_account_block_pause_kinds"),
    ]

    operations = [
        migrations.CreateModel(
            name="BankIdIdentity",
            fields=[
                ("user_id", models.UUIDField(primary_key=True, serialize=False)),
                ("pnr_key", models.CharField(max_length=32, unique=True)),
                ("full_name", models.TextField()),
                ("verified_at", models.DateTimeField()),
                ("last_used_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "fleet_bankid_identity"},
        ),
        migrations.CreateModel(
            name="BankIdOrder",
            fields=[
                ("order_ref", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("purpose", models.CharField(max_length=16)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("collected_at", models.DateTimeField(blank=True, null=True)),
                ("consumed_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={
                "db_table": "fleet_bankid_order",
                "indexes": [models.Index(fields=["created_at"], name="fleet_banki_created_c5d576_idx")],
            },
        ),
        migrations.RunSQL(REVOKE_NEW_TABLES, reverse_sql=migrations.RunSQL.noop),
    ]
