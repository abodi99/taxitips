# Separat CRM-modul: account / person / deal; flytta data från fleet_crm_lead.

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
    foreach tbl in array array[
      'fleet_crm_account', 'fleet_crm_person', 'fleet_crm_deal', 'fleet_crm_note'
    ] loop
      if to_regclass('public.' || tbl) is not null then
        execute format('revoke all on table public.%I from %I', tbl, r);
      end if;
    end loop;
  end loop;
end $$;
"""

# Gamla lead-steg → deal-steg (Twenty-liknande).
STAGE_MAP = {
    "lead": "new",
    "qualified": "screening",
    "proposal": "proposal",
    "trial": "proposal",
    "customer": "won",
    "lost": "lost",
    "churned": "churned",
}


def migrate_leads_forward(apps, schema_editor):
    CrmLead = apps.get_model("fleet", "CrmLead")
    CrmAccount = apps.get_model("fleet", "CrmAccount")
    CrmPerson = apps.get_model("fleet", "CrmPerson")
    CrmDeal = apps.get_model("fleet", "CrmDeal")
    CrmNote = apps.get_model("fleet", "CrmNote")

    for lead in CrmLead.objects.all().iterator():
        account = CrmAccount.objects.create(
            id=uuid.uuid4(),
            name=lead.company_name or "",
            org_number=lead.org_number or "",
            county=lead.county or "",
            source=lead.source or "",
            created_at=lead.created_at,
            updated_at=lead.updated_at,
        )
        person = None
        if lead.contact_name or lead.contact_email or lead.contact_phone:
            person = CrmPerson.objects.create(
                id=uuid.uuid4(),
                account_id=account.id,
                name=lead.contact_name or "",
                email=lead.contact_email or "",
                phone=lead.contact_phone or "",
                created_at=lead.created_at,
                updated_at=lead.updated_at,
            )
        stage = STAGE_MAP.get(lead.stage, "new")
        deal_name = lead.company_name or lead.contact_name or "Affär"
        deal = CrmDeal.objects.create(
            id=lead.id,  # behåll lead-id så anteckningar / bokmärken håller
            account_id=account.id,
            person_id=person.id if person else None,
            name=deal_name,
            stage=stage,
            notes_summary=lead.notes_summary or "",
            source=lead.source or "",
            company_id=lead.company_id,
            created_at=lead.created_at,
            updated_at=lead.updated_at,
        )
        CrmNote.objects.filter(lead_id=lead.id).update(deal_id=deal.id)


def migrate_leads_backward(apps, schema_editor):
    # Contract-only forward; reverse recreate is best-effort.
    CrmLead = apps.get_model("fleet", "CrmLead")
    CrmDeal = apps.get_model("fleet", "CrmDeal")
    CrmAccount = apps.get_model("fleet", "CrmAccount")
    CrmPerson = apps.get_model("fleet", "CrmPerson")
    reverse_stage = {
        "new": "lead",
        "screening": "qualified",
        "meeting": "qualified",
        "proposal": "proposal",
        "won": "customer",
        "lost": "lost",
        "churned": "churned",
    }
    for deal in CrmDeal.objects.all().iterator():
        account = CrmAccount.objects.filter(id=deal.account_id).first() if deal.account_id else None
        person = CrmPerson.objects.filter(id=deal.person_id).first() if deal.person_id else None
        CrmLead.objects.create(
            id=deal.id,
            contact_name=(person.name if person else "") or "",
            contact_email=(person.email if person else "") or "",
            contact_phone=(person.phone if person else "") or "",
            company_name=(account.name if account else "") or deal.name or "",
            org_number=(account.org_number if account else "") or "",
            county=(account.county if account else "") or "",
            source=deal.source or "",
            stage=reverse_stage.get(deal.stage, "lead"),
            notes_summary=deal.notes_summary or "",
            company_id=deal.company_id,
            created_at=deal.created_at,
            updated_at=deal.updated_at,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("fleet", "0014_native_crm"),
    ]

    operations = [
        migrations.CreateModel(
            name="CrmAccount",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False,
                    ),
                ),
                ("name", models.TextField(blank=True, default="")),
                ("org_number", models.CharField(blank=True, default="", max_length=32)),
                ("county", models.CharField(blank=True, default="", max_length=32)),
                ("domain", models.CharField(blank=True, default="", max_length=255)),
                ("source", models.CharField(blank=True, default="", max_length=100)),
                ("twenty_id", models.CharField(blank=True, max_length=64, null=True, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "fleet_crm_account",
                "indexes": [
                    models.Index(fields=["-updated_at"], name="fleet_crm_acc_updated_idx"),
                    models.Index(fields=["org_number"], name="fleet_crm_acc_org_idx"),
                ],
            },
        ),
        migrations.CreateModel(
            name="CrmPerson",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False,
                    ),
                ),
                ("name", models.TextField(blank=True, default="")),
                ("email", models.TextField(blank=True, default="")),
                ("phone", models.TextField(blank=True, default="")),
                ("title", models.CharField(blank=True, default="", max_length=200)),
                ("twenty_id", models.CharField(blank=True, max_length=64, null=True, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "account",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="people",
                        to="fleet.crmaccount",
                    ),
                ),
            ],
            options={
                "db_table": "fleet_crm_person",
                "indexes": [
                    models.Index(fields=["email"], name="fleet_crm_person_email_idx"),
                    models.Index(
                        fields=["account", "-updated_at"], name="fleet_crm_person_acc_idx",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="CrmDeal",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False,
                    ),
                ),
                ("name", models.TextField(blank=True, default="")),
                (
                    "stage",
                    models.CharField(
                        choices=[
                            ("new", "Ny"),
                            ("screening", "Kvalificering"),
                            ("meeting", "Möte"),
                            ("proposal", "Offert"),
                            ("won", "Vunnen"),
                            ("lost", "Förlorad"),
                            ("churned", "Churnad"),
                        ],
                        default="new",
                        max_length=20,
                    ),
                ),
                ("amount_ore", models.BigIntegerField(blank=True, null=True)),
                ("notes_summary", models.TextField(blank=True, default="")),
                ("source", models.CharField(blank=True, default="", max_length=100)),
                ("company_id", models.UUIDField(blank=True, null=True)),
                ("twenty_id", models.CharField(blank=True, max_length=64, null=True, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "account",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="deals",
                        to="fleet.crmaccount",
                    ),
                ),
                (
                    "person",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="deals",
                        to="fleet.crmperson",
                    ),
                ),
            ],
            options={
                "db_table": "fleet_crm_deal",
                "indexes": [
                    models.Index(
                        fields=["stage", "-updated_at"], name="fleet_crm_deal_stage_idx",
                    ),
                    models.Index(fields=["company_id"], name="fleet_crm_deal_company_idx"),
                    models.Index(
                        fields=["account", "-updated_at"], name="fleet_crm_deal_acc_idx",
                    ),
                    models.Index(fields=["-updated_at"], name="fleet_crm_deal_updated_idx"),
                ],
            },
        ),
        # Expand note targets
        migrations.AddField(
            model_name="crmnote",
            name="account_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="crmnote",
            name="person_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="crmnote",
            name="deal_id",
            field=models.UUIDField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="crmnote",
            name="twenty_id",
            field=models.CharField(blank=True, max_length=64, null=True, unique=True),
        ),
        migrations.AddIndex(
            model_name="crmnote",
            index=models.Index(
                fields=["deal_id", "-created_at"], name="fleet_crm_note_deal_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="crmnote",
            index=models.Index(
                fields=["account_id", "-created_at"], name="fleet_crm_note_acc_idx",
            ),
        ),
        migrations.AddIndex(
            model_name="crmnote",
            index=models.Index(
                fields=["person_id", "-created_at"], name="fleet_crm_note_person_idx",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="crmnote",
            name="fleet_crm_note_has_target",
        ),
        migrations.AddConstraint(
            model_name="crmnote",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("account_id__isnull", False))
                    | models.Q(("person_id__isnull", False))
                    | models.Q(("deal_id__isnull", False))
                    | models.Q(("company_id__isnull", False))
                    | models.Q(("lead_id__isnull", False))
                ),
                name="fleet_crm_note_has_target",
            ),
        ),
        migrations.RunPython(migrate_leads_forward, migrate_leads_backward),
        # Contract: drop lead column and table
        migrations.RemoveConstraint(
            model_name="crmnote",
            name="fleet_crm_note_has_target",
        ),
        migrations.RemoveIndex(
            model_name="crmnote",
            name="fleet_crm_note_lead_idx",
        ),
        migrations.RemoveField(
            model_name="crmnote",
            name="lead_id",
        ),
        migrations.AddConstraint(
            model_name="crmnote",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(("account_id__isnull", False))
                    | models.Q(("person_id__isnull", False))
                    | models.Q(("deal_id__isnull", False))
                    | models.Q(("company_id__isnull", False))
                ),
                name="fleet_crm_note_has_target",
            ),
        ),
        migrations.DeleteModel(name="CrmLead"),
        migrations.RunSQL(REVOKE_NEW_TABLES, reverse_sql=migrations.RunSQL.noop),
    ]
