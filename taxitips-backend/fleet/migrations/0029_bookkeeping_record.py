from django.db import migrations, models
import uuid

# Invariant 19: Djangos tabeller nås aldrig via PostgREST. Bokföringsraden
# bär organisationsnummer och Stripe-referenser.
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
    foreach t in array array['fleet_bookkeeping_record'] loop
      if to_regclass(format('public.%I', t)) is not null then
        execute format('revoke all on table public.%I from %I', t, r);
      end if;
    end loop;
  end loop;
end $$;
"""


class Migration(migrations.Migration):

    dependencies = [
        ("fleet", "0028_bankid"),
    ]

    operations = [
        migrations.CreateModel(
            name="BookkeepingRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("retained_at", models.DateTimeField()),
                ("retained_by", models.UUIDField(blank=True, null=True)),
                ("former_company_id", models.UUIDField()),
                ("country", models.CharField(default="SE", max_length=2)),
                ("org_number", models.CharField(blank=True, default="", max_length=32)),
                ("legal_name", models.TextField(blank=True, default="")),
                ("order_id", models.UUIDField(blank=True, null=True)),
                ("kind", models.CharField(blank=True, default="", max_length=24)),
                ("status", models.CharField(blank=True, default="", max_length=20)),
                ("amount_ore", models.IntegerField(default=0)),
                ("vat_ore", models.IntegerField(default=0)),
                ("total_ore", models.IntegerField(default=0)),
                ("currency", models.CharField(default="SEK", max_length=3)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("stripe_invoice_id", models.TextField(blank=True, default="")),
                ("stripe_payment_intent_id", models.TextField(blank=True, default="")),
                ("stripe_checkout_session_id", models.TextField(blank=True, default="")),
                ("stripe_customer_id", models.TextField(blank=True, default="")),
                ("stripe_subscription_id", models.TextField(blank=True, default="")),
            ],
            options={
                "db_table": "fleet_bookkeeping_record",
                "indexes": [
                    models.Index(fields=["former_company_id", "-retained_at"], name="fleet_bookk_former__ca3700_idx"),
                    models.Index(fields=["org_number"], name="fleet_bookk_org_num_cbdcb7_idx"),
                ],
            },
        ),
        migrations.RunSQL(REVOKE_NEW_TABLES, reverse_sql=migrations.RunSQL.noop),
    ]
