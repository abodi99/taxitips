# Expand: säljarens uppgifter (CrmTask) och redigeringsspår på anteckningar.
# Additivt — ny tabell och två nya kolumner med databas-default/NULL.

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
    foreach tbl in array array['fleet_crm_task', 'fleet_crm_note'] loop
      if to_regclass('public.' || tbl) is not null then
        execute format('revoke all on table public.%I from %I', tbl, r);
      end if;
    end loop;
  end loop;
end $$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("fleet", "0017_crm_account_city_legal_form"),
    ]

    operations = [
        migrations.AddField(
            model_name="crmnote",
            name="edited_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="crmnote",
            name="edited_by_label",
            field=models.CharField(blank=True, db_default="", default="", max_length=320),
        ),
        migrations.CreateModel(
            name="CrmTask",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False,
                    ),
                ),
                ("title", models.CharField(max_length=200)),
                ("body", models.TextField(blank=True, default="")),
                (
                    "status",
                    models.CharField(
                        choices=[("todo", "Att göra"), ("doing", "Pågår"), ("done", "Klar")],
                        default="todo",
                        max_length=10,
                    ),
                ),
                ("due_date", models.DateField(blank=True, null=True)),
                ("assignee_user_id", models.UUIDField(blank=True, null=True)),
                ("assignee_label", models.CharField(blank=True, default="", max_length=320)),
                ("deal_id", models.UUIDField(blank=True, null=True)),
                ("account_id", models.UUIDField(blank=True, null=True)),
                ("person_id", models.UUIDField(blank=True, null=True)),
                ("company_id", models.UUIDField(blank=True, null=True)),
                ("created_by_user_id", models.UUIDField(blank=True, null=True)),
                ("created_by_label", models.CharField(blank=True, default="", max_length=320)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "fleet_crm_task",
                "indexes": [
                    models.Index(
                        fields=["assignee_user_id", "status", "due_date"],
                        name="fleet_crm_task_assignee_idx",
                    ),
                    models.Index(fields=["status", "due_date"], name="fleet_crm_task_status_idx"),
                    models.Index(fields=["deal_id", "status"], name="fleet_crm_task_deal_idx"),
                    models.Index(fields=["account_id", "status"], name="fleet_crm_task_acc_idx"),
                    models.Index(
                        fields=["company_id", "status"], name="fleet_crm_task_company_idx",
                    ),
                ],
            },
        ),
        migrations.RunSQL(REVOKE, reverse_sql=migrations.RunSQL.noop),
    ]
