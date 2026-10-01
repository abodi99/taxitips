# Inbyggd CRM i adminwebben (leads, anteckningar, pipeline).

from django.db import migrations, models
import django.db.models.deletion
import uuid


REVOKE_NEW_TABLES = """
do $$
declare
  r text;
  tbl text;
begin
  foreach r in array array['anon', 'authenticated'] loop
    if not exists (select 1 from pg_roles where rolname = r) then
      continue;
    end if;
    foreach tbl in array array['fleet_crm_lead', 'fleet_crm_note'] loop
      if to_regclass('public.' || tbl) is not null then
        execute format('revoke all on table public.%I from %I', tbl, r);
      end if;
    end loop;
  end loop;
end $$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("fleet", "0013_sales_followup_churn"),
    ]

    operations = [
        migrations.CreateModel(
            name="CrmLead",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False,
                    ),
                ),
                ("contact_name", models.TextField(blank=True, default="")),
                ("contact_email", models.TextField(blank=True, default="")),
                ("contact_phone", models.TextField(blank=True, default="")),
                ("company_name", models.TextField(blank=True, default="")),
                ("org_number", models.CharField(blank=True, default="", max_length=32)),
                ("county", models.CharField(blank=True, default="", max_length=32)),
                ("source", models.CharField(blank=True, default="", max_length=100)),
                (
                    "stage",
                    models.CharField(
                        choices=[
                            ("lead", "Lead"),
                            ("qualified", "Kvalificerad"),
                            ("proposal", "Offert / prov"),
                            ("trial", "Prov"),
                            ("customer", "Kund"),
                            ("lost", "Förlorad"),
                            ("churned", "Churnad"),
                        ],
                        default="lead",
                        max_length=20,
                    ),
                ),
                ("notes_summary", models.TextField(blank=True, default="")),
                ("company_id", models.UUIDField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "fleet_crm_lead",
                "indexes": [
                    models.Index(fields=["stage", "-created_at"], name="fleet_crm_lead_stage_idx"),
                    models.Index(fields=["company_id"], name="fleet_crm_lead_company_idx"),
                    models.Index(fields=["-created_at"], name="fleet_crm_lead_created_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="CrmNote",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False,
                    ),
                ),
                ("lead_id", models.UUIDField(blank=True, null=True)),
                ("company_id", models.UUIDField(blank=True, null=True)),
                ("author_user_id", models.UUIDField(blank=True, null=True)),
                ("author_label", models.TextField(blank=True, default="")),
                ("title", models.CharField(blank=True, default="", max_length=200)),
                ("body", models.TextField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "db_table": "fleet_crm_note",
                "indexes": [
                    models.Index(
                        fields=["company_id", "-created_at"], name="fleet_crm_note_company_idx",
                    ),
                    models.Index(fields=["lead_id", "-created_at"], name="fleet_crm_note_lead_idx"),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("lead_id__isnull", False))
                        | models.Q(("company_id__isnull", False)),
                        name="fleet_crm_note_has_target",
                    ),
                ],
            },
        ),
        migrations.RunSQL(REVOKE_NEW_TABLES, reverse_sql=migrations.RunSQL.noop),
    ]
