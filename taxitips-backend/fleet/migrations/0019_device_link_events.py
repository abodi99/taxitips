# Expand: telefonbyten per konto (historik + extra tillfällen från admin).
# Additivt — nya tabeller. Inga PostgREST-rättigheter (invariant 19).

import uuid

from django.db import migrations, models


REVOKE = """
do $$
declare
  r text;
  tbl text;
begin
  foreach r in array array['anon', 'authenticated'] loop
    if not exists (select 1 from pg_roles where rolname = r) then
      continue;
    end if;
    foreach tbl in array array['fleet_device_link_event', 'fleet_device_swap_grant'] loop
      if to_regclass('public.' || tbl) is not null then
        execute format('revoke all on table public.%I from %I', tbl, r);
      end if;
    end loop;
  end loop;
end $$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("fleet", "0018_crm_tasks_note_edit"),
    ]

    operations = [
        migrations.CreateModel(
            name="DeviceLinkEvent",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False,
                    ),
                ),
                ("user_id", models.UUIDField()),
                ("device_id", models.UUIDField()),
                ("previous_device_id", models.UUIDField(blank=True, null=True)),
                ("via", models.CharField(blank=True, default="", max_length=40)),
                ("is_swap", models.BooleanField(default=False)),
                ("admin_override", models.BooleanField(default=False)),
                ("actor_user_id", models.UUIDField(blank=True, null=True)),
                ("note", models.CharField(blank=True, default="", max_length=300)),
                ("created_at", models.DateTimeField()),
            ],
            options={
                "db_table": "fleet_device_link_event",
                "indexes": [
                    models.Index(fields=["user_id", "-created_at"], name="fleet_devic_user_id_7e2a1b_idx"),
                    models.Index(
                        fields=["user_id", "is_swap", "-created_at"],
                        name="fleet_devic_user_id_9c4d2e_idx",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="DeviceSwapGrant",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False,
                    ),
                ),
                ("user_id", models.UUIDField()),
                ("month_key", models.CharField(max_length=7)),
                ("granted_by", models.UUIDField(blank=True, null=True)),
                ("note", models.CharField(blank=True, default="", max_length=300)),
                ("created_at", models.DateTimeField()),
            ],
            options={
                "db_table": "fleet_device_swap_grant",
                "indexes": [
                    models.Index(fields=["user_id", "month_key"], name="fleet_devic_user_id_a1b2c3_idx"),
                ],
            },
        ),
        migrations.RunSQL(sql=REVOKE, reverse_sql=migrations.RunSQL.noop),
    ]
