"""
managed=False -- de här tre tabellerna ägs av Supabases egna migrationer
(taxitips-api/supabase/migrations/20260828999999_baseline_actual_schema.sql
och 20260901000001_processed_webhook_events.sql), aldrig av Django. Kör
ALDRIG `makemigrations billing`: managed=False är det som håller gränsen,
och den är hela poängen med uppdelningen -- Django äger pipeline-tabellerna,
Supabase äger domäntabellerna, ingen tabell beskrivs på två ställen.

De ligger numera i SAMMA databas som Djangos egna tabeller (en Postgres,
den `supabase start` kör), så ingen router och inget andra DB-alias behövs.

Fältformerna speglar det verifierade schemat, inte den äldre/planerade
formen i init_saas.sql (ingen trial_ends_at, billing_account_id, m.fl. --
se baseline-migrationens egen kommentar).
"""

from django.db import models


class Company(models.Model):
    id = models.UUIDField(primary_key=True)
    name = models.TextField()
    email = models.TextField(null=True)
    org_number = models.TextField(null=True)
    join_code = models.TextField(unique=True)
    seats = models.IntegerField(default=1)
    status = models.TextField(default="trial")
    # watched_areas (text[]) är inte med -- billing-appen läser/skriver den
    # aldrig, och Djangos JSONField skulle mappa fel mot en riktig text[]-
    # kolumn (jsonb-semantik mot en array-kolumn). Lägg till med
    # ArrayField(TextField()) den dagen den faktiskt behövs här.
    created_at = models.DateTimeField()
    stripe_customer_id = models.TextField(null=True)
    stripe_subscription_id = models.TextField(null=True)
    subscription_status = models.TextField(default="inactive")

    class Meta:
        app_label = "billing"
        managed = False
        db_table = "companies"


class Device(models.Model):
    id = models.UUIDField(primary_key=True)
    company_id = models.UUIDField()
    token = models.TextField(unique=True)
    label = models.TextField()
    kind = models.TextField()
    push_token = models.TextField(null=True)
    notify_prefs = models.JSONField(default=dict)
    created_at = models.DateTimeField(null=True)

    class Meta:
        app_label = "billing"
        managed = False
        db_table = "devices"


class ProcessedWebhookEvent(models.Model):
    stripe_event_id = models.TextField(primary_key=True)
    event_type = models.TextField()
    processed_at = models.DateTimeField()
    status = models.TextField()
    error = models.TextField(null=True)

    class Meta:
        app_label = "billing"
        managed = False
        db_table = "processed_webhook_events"


class CompanyMember(models.Model):
    """
    Ägare/administratör kopplad till ett bolag -- den inloggade vägen, till
    skillnad från Device som är förarens tokenväg.

    Behövs av core/entitlement.py: `current_entitlement` i SQL kollade både
    d.token och auth.uid() mot company_members, och en Django-port som bara
    kollade device-token hade tyst nekat varje inloggad ägare all data --
    exakt buggen som 20260902000005 en gång rättade i SQL-versionen.
    """

    id = models.UUIDField(primary_key=True)
    company_id = models.UUIDField()
    user_id = models.UUIDField()
    role = models.TextField(null=True)
    status = models.TextField(null=True)
    created_at = models.DateTimeField(null=True)

    class Meta:
        app_label = "billing"
        managed = False
        db_table = "company_members"
