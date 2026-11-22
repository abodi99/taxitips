import uuid

import django.db.models.deletion
from django.db import migrations, models


# Samma skäl som 0003-0006 (invariant 19): tabellerna innehåller e-postadresser
# och får inte nås via PostgREST. All läsning går genom fleet/admin_crm.py.
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
    foreach t in array array[
      'fleet_crm_email_suppression', 'fleet_crm_campaign',
      'fleet_crm_campaign_recipient', 'fleet_crm_mailbox_state'
    ] loop
      if to_regclass(format('public.%I', t)) is not null then
        execute format('revoke all on table public.%I from %I', t, r);
      end if;
    end loop;
  end loop;
end $$;
"""


class Migration(migrations.Migration):
    """
    Säljutskick ur CRM (fleet/outreach.py): kampanj, mottagare, spärrlista och
    inkorgens läsmärke. Bara nya tabeller -- ingenting befintligt ändras, så en
    äldre container kör vidare under utrullningen. (Indexnamnen som
    makemigrations också vill byta hör inte hit, se 0030.)
    """

    dependencies = [
        ("fleet", "0030_company_profile_customer_kind"),
    ]

    operations = [
        migrations.CreateModel(
            name="CrmEmailSuppression",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("email", models.CharField(max_length=254, unique=True)),
                ("reason", models.CharField(
                    choices=[
                        ("unsubscribed", "Avregistrerad"), ("bounced", "Studs"),
                        ("complaint", "Klagomål"), ("blocklist", "Reklamspärr eller ring ej"),
                        ("manual", "Manuell"),
                    ],
                    max_length=16,
                )),
                ("detail", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"db_table": "fleet_crm_email_suppression"},
        ),
        migrations.CreateModel(
            name="CrmCampaign",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("slug", models.CharField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=200)),
                ("status", models.CharField(
                    choices=[("draft", "Utkast"), ("active", "Aktiv"), ("paused", "Pausad"), ("done", "Klar")],
                    default="draft", max_length=10,
                )),
                ("daily_cap", models.PositiveSmallIntegerField(default=80)),
                ("paused_reason", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "fleet_crm_campaign"},
        ),
        migrations.CreateModel(
            name="CrmMailboxState",
            fields=[
                ("mailbox", models.CharField(max_length=254, primary_key=True, serialize=False)),
                ("uid_validity", models.BigIntegerField(default=0)),
                ("last_uid", models.BigIntegerField(default=0)),
                ("checked_at", models.DateTimeField(blank=True, null=True)),
            ],
            options={"db_table": "fleet_crm_mailbox_state"},
        ),
        migrations.CreateModel(
            name="CrmCampaignRecipient",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("deal_id", models.UUIDField(blank=True, null=True)),
                ("email", models.CharField(max_length=254)),
                ("state", models.CharField(
                    choices=[
                        ("queued", "Väntar"), ("active", "Pågår"), ("finished", "Klar"),
                        ("replied", "Svarat"), ("unsubscribed", "Avregistrerad"),
                        ("bounced", "Studs"), ("converted", "Startat prov"), ("stopped", "Stoppad"),
                    ],
                    default="queued", max_length=14,
                )),
                ("step", models.PositiveSmallIntegerField(default=0)),
                ("priority", models.IntegerField(default=0)),
                ("next_send_at", models.DateTimeField(blank=True, null=True)),
                ("last_sent_at", models.DateTimeField(blank=True, null=True)),
                ("thread_message_id", models.CharField(blank=True, default="", max_length=255)),
                ("stopped_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("account", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to="fleet.crmaccount",
                )),
                ("campaign", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="recipients", to="fleet.crmcampaign",
                )),
                ("person", models.ForeignKey(
                    blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                    related_name="+", to="fleet.crmperson",
                )),
            ],
            options={"db_table": "fleet_crm_campaign_recipient"},
        ),
        migrations.AddIndex(
            model_name="crmcampaignrecipient",
            index=models.Index(fields=["campaign", "state", "next_send_at"], name="fleet_crm_camp_rcpt_due_idx"),
        ),
        migrations.AddIndex(
            model_name="crmcampaignrecipient",
            index=models.Index(fields=["email"], name="fleet_crm_camp_rcpt_email_idx"),
        ),
        migrations.AddIndex(
            model_name="crmcampaignrecipient",
            index=models.Index(fields=["deal_id"], name="fleet_crm_camp_rcpt_deal_idx"),
        ),
        migrations.AddConstraint(
            model_name="crmcampaignrecipient",
            constraint=models.UniqueConstraint(
                fields=("campaign", "email"), name="fleet_crm_campaign_recipient_unique",
            ),
        ),
        migrations.RunSQL(REVOKE_NEW_TABLES, reverse_sql=migrations.RunSQL.noop),
    ]
