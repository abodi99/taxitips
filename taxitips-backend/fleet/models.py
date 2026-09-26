"""
Kundlivscykeln: företag, roller, bilar, billicenser, län, godkända telefoner,
aktiva bilsessioner, prov, beställningar och revision.

**Varför en egen app och inte fler kolumner i `companies`/`devices`.**
De tre tabellerna ägs av Supabases migrationer (`billing/models.py`,
managed=False) och nås av appen via PostgREST. Att lägga licenser, priser och
sessioner där hade betytt att varje ny rättighetstabell blir läsbar för
`authenticated` om någon glömmer en RLS-policy -- exakt det felet som
20260913003_lock_down_django_tables.sql städade upp efter. Djangos tabeller
får sedan den migrationen inga rättigheter för anon/authenticated automatiskt,
och den här appen läses uteslutande genom Djangos egna vyer som kontrollerar
behörigheten i Python. Ingen tabell här är avsedd att nås direkt av klienten.

**Vad som återanvänds i stället för att skrivas om.** `companies` är fortsatt
avtalsparten, `company_members` fortsatt roll-/medlemskapstabellen och
`devices` fortsatt telefonraden med sin push-token. Den här appen hänger
rättigheterna PÅ dem (`company_id`, `device_id` som UUID-referenser utan FK,
eftersom måltabellen ligger utanför Djangos migrationskedja).

**Pengar är heltal i ören.** 799 kr = 79900. Ingen float rör ett belopp.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models import Q


# ---------------------------------------------------------------------------
# Företag, roller och verifiering
# ---------------------------------------------------------------------------


class VerificationStatus(models.TextChoices):
    UNVERIFIED = "unverified", "Inte verifierad"
    PENDING_REVIEW = "pending_review", "Under granskning"
    VERIFIED = "verified", "Verifierad"
    REJECTED = "rejected", "Avvisad"


class CompanyProfile(models.Model):
    """
    Avtalsuppgifterna om företaget, vid sidan av Supabases `companies`.

    Avtalsparten identifieras av land + normaliserat organisationsnummer.
    Unikheten gäller BARA verifierade profiler: två obekräftade registreringar
    av samma organisationsnummer måste kunna finnas samtidigt, annars kan den
    som råkar registrera sig först med ett offentligt organisationsnummer låsa
    ute det riktiga företaget (§7). Den riktiga innehavaren tar över genom
    granskningsflödet, inte genom att vinna ett kapplöpningsvillkor.
    """

    company_id = models.UUIDField(primary_key=True)
    country = models.CharField(max_length=2, default="SE")
    # Normaliserat: bara siffror. Se fleet.orgnr.normalize().
    org_number = models.CharField(max_length=32, blank=True, default="")
    legal_name = models.TextField(blank=True, default="")

    contact_name = models.TextField(blank=True, default="")
    contact_role = models.TextField(blank=True, default="")
    contact_email = models.TextField(blank=True, default="")
    contact_phone = models.TextField(blank=True, default="")
    email_verified_at = models.DateTimeField(null=True, blank=True)
    phone_verified_at = models.DateTimeField(null=True, blank=True)
    payment_method_verified_at = models.DateTimeField(null=True, blank=True)

    verification_status = models.CharField(
        max_length=20, choices=VerificationStatus.choices,
        default=VerificationStatus.UNVERIFIED,
    )
    verification_note = models.TextField(blank=True, default="")

    billing_email = models.TextField(blank=True, default="")
    billing_reference = models.TextField(blank=True, default="")
    billing_address = models.JSONField(default=dict, blank=True)

    terms_version = models.CharField(max_length=32, blank=True, default="")
    terms_accepted_at = models.DateTimeField(null=True, blank=True)
    terms_accepted_by = models.UUIDField(null=True, blank=True)

    # Migreringsvägen för äldre konton (§ "Bevara befintliga kunders giltiga
    # åtkomst"). Ett företag som fanns före licensmodellen får köra vidare på
    # sina gamla enheter till och med det här datumet, även utan billicens.
    # NULL = ingen övergångsrätt. Sätts av `migrate_legacy_fleet`, stängs av
    # samma kommando med --close.
    legacy_access_until = models.DateTimeField(null=True, blank=True)
    # Länen ett äldre bolag hade när övergången inleddes -- annars hade
    # övergångsåtkomsten antingen varit hela landet eller ingenting.
    legacy_counties = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "fleet_company_profile"
        constraints = [
            models.UniqueConstraint(
                fields=["country", "org_number"],
                condition=Q(verification_status="verified") & ~Q(org_number=""),
                name="fleet_one_verified_company_per_orgnr",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.legal_name or self.company_id} ({self.country}{self.org_number})"


class StaffRole(models.Model):
    """
    Plattformens egna roller (säljare, support) -- inte kundens.

    Egen tabell och inte ett värde i `company_members.role`, eftersom en
    säljare inte är medlem i kundens företag och aldrig får ärva kundens
    behörigheter. Säljare kan bjuda in till kortfritt prov; ingen av dem kan
    återställa provhistorik (§7).
    """

    class Role(models.TextChoices):
        SALES = "sales", "Säljare"
        SUPPORT = "support", "Support"
        PLATFORM_ADMIN = "platform_admin", "Plattformsadministratör"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user_id = models.UUIDField(unique=True)
    role = models.CharField(max_length=20, choices=Role.choices)
    is_active = models.BooleanField(default=True)
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fleet_staff_role"


# ---------------------------------------------------------------------------
# Pris och abonnemang
# ---------------------------------------------------------------------------


class PriceVersion(models.Model):
    """
    En versionerad prisplan. Befintliga avtal pekar på sin version och ändras
    aldrig av att en ny läggs till -- det är hela poängen med versioneringen.

    Introduktionskampanjen är AV tills någon sätter `launch_date` och
    `intro_enabled`. Ett gissat lanseringsdatum hade börjat ge rabatt till fel
    företag, och den sortens fel syns först på fakturan (§6).
    """

    id = models.CharField(max_length=40, primary_key=True)
    label = models.TextField()
    currency = models.CharField(max_length=3, default="SEK")
    # Moms i punkter av en procent: 2500 = 25,00 %. Heltal, som alla belopp.
    vat_rate_bp = models.IntegerField(default=2500)

    base_price_ore = models.IntegerField()
    volume_price_ore = models.IntegerField()
    volume_threshold = models.IntegerField(default=10)
    extra_county_price_ore = models.IntegerField()

    intro_price_ore = models.IntegerField()
    intro_months = models.IntegerField(default=3)
    intro_enabled = models.BooleanField(default=False)
    launch_date = models.DateField(null=True, blank=True)
    intro_signup_window_days = models.IntegerField(default=60)

    terms_version = models.CharField(max_length=32, default="")

    is_default = models.BooleanField(default=False)
    active_from = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fleet_price_version"
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"], condition=Q(is_default=True),
                name="fleet_one_default_price_version",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.id} ({self.label})"


class SubscriptionStatus(models.TextChoices):
    NONE = "none", "Ingen"
    TRIALING = "trialing", "Prov"
    ACTIVE = "active", "Aktiv"
    PAST_DUE = "past_due", "Förfallen"
    CANCELED = "canceled", "Avslutad"


class Subscription(models.Model):
    """
    Företagets samlade abonnemang -- en per bolag, med versionerad prisplan.

    `last_stripe_event_at` finns av samma skäl som `companies.
    last_subscription_event_at` i edge-funktionen: Stripe lovar ingen ordning,
    och en äldre händelse som kommer efter en nyare får inte skriva över den.

    `had_successful_payment` styr betalningsfristen. Första misslyckade
    betalningen efter ett gratisprov ger ingen frist (§8) -- utan fältet hade
    ett prov som aldrig betalats gett sju extra gratisdagar.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_id = models.UUIDField(unique=True)
    price_version = models.ForeignKey(PriceVersion, on_delete=models.PROTECT)

    status = models.CharField(
        max_length=20, choices=SubscriptionStatus.choices,
        default=SubscriptionStatus.NONE,
    )
    stripe_customer_id = models.TextField(blank=True, default="")
    stripe_subscription_id = models.TextField(blank=True, default="")

    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)

    cancel_at_period_end = models.BooleanField(default=False)
    canceled_at = models.DateTimeField(null=True, blank=True)
    # Sista dagen med åtkomst. Betald period löper ut, ingen extra frist (§8).
    access_until = models.DateTimeField(null=True, blank=True)

    # Betalningsfrist vid misslyckad förnyelse. Räknas från URSPRUNGLIG
    # förfallotid; ett återförsök flyttar den aldrig framåt (§8).
    grace_until = models.DateTimeField(null=True, blank=True)
    grace_origin = models.DateTimeField(null=True, blank=True)
    had_successful_payment = models.BooleanField(default=False)
    renewal_stopped_at = models.DateTimeField(null=True, blank=True)

    # Introduktionen ägs av FÖRETAGET, inte av bilen: en bil som läggs till
    # senare får bara den tid som är kvar (§6).
    intro_started_at = models.DateTimeField(null=True, blank=True)
    intro_ends_at = models.DateTimeField(null=True, blank=True)
    intro_months_used = models.IntegerField(default=0)

    last_stripe_event_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "fleet_subscription"


# ---------------------------------------------------------------------------
# Prov
# ---------------------------------------------------------------------------


class SalesInvite(models.Model):
    """
    Personlig engångsinbjudan till kortfritt prov, giltig sju dagar.

    `verification_note` är obligatoriskt innehåll, inte dekoration: säljaren
    måste dokumentera den verifierade företagskontakten innan inbjudan skickas
    (§7). Koden lagras hashad -- en läckt databas ska inte ge giltiga
    inbjudningar.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Skickad"
        CONSUMED = "consumed", "Använd"
        REVOKED = "revoked", "Återkallad"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code_hash = models.CharField(max_length=64, unique=True)
    created_by = models.UUIDField()
    country = models.CharField(max_length=2, default="SE")
    org_number = models.CharField(max_length=32)
    company_name = models.TextField()
    contact_name = models.TextField()
    contact_email = models.TextField()
    contact_phone = models.TextField(blank=True, default="")
    verification_note = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    consumed_by_company = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fleet_sales_invite"


class Trial(models.Model):
    """
    Provperioden. 14 dagar, högst tre provbilar, högst en per företag per 24
    månader.

    `org_key` är land+organisationsnummer och är det som spärren räknar på.
    Nyckeln sitter avsiktligt INTE på company_id: ett nytt bolagskonto med
    samma organisationsnummer ska inte ge ett nytt gratisprov (§7). Raden
    behålls efter provets slut -- den ÄR provhistoriken.

    `started_at`/`ends_at` skrivs atomiskt en gång (se fleet.trials.start_trial)
    och alla provbilar delar slutdatum.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Väntar på aktivering"
        ACTIVE = "active", "Pågår"
        ENDED = "ended", "Avslutat"
        CONVERTED = "converted", "Övergick till betalning"
        CANCELED = "canceled", "Avbrutet"

    class Source(models.TextChoices):
        SELF_SIGNUP = "self_signup", "Självregistrering"
        SALES_INVITE = "sales_invite", "Säljarinbjudan"
        # Upplagt av en säljare i adminwebben under ett samtal (fleet/sales.py).
        SALES = "sales", "Säljare"
        # Tillfällig åtkomst från en kupong. Samma rad som ett prov, för att
        # samma regler ska gälla: provbilar debiteras aldrig av sig själva och
        # avslutas utan kostnad om ingen beställer (fleet/sales.py).
        COUPON = "coupon", "Kupong"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_id = models.UUIDField()
    org_key = models.CharField(max_length=40)
    source = models.CharField(max_length=20, choices=Source.choices)
    invite = models.ForeignKey(SalesInvite, null=True, blank=True, on_delete=models.SET_NULL)
    requires_payment_method = models.BooleanField(default=True)

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    vehicle_limit = models.IntegerField(default=3)
    started_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    ended_reason = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fleet_trial"
        indexes = [
            models.Index(fields=["org_key", "-created_at"]),
            models.Index(fields=["company_id", "-created_at"]),
        ]
        constraints = [
            # Ett pågående/väntande prov per bolag. Två samtidiga registreringar
            # får inte ge två prov.
            models.UniqueConstraint(
                fields=["company_id"],
                condition=Q(status__in=["pending", "active"]),
                name="fleet_one_open_trial_per_company",
            ),
        ]


class Coupon(models.Model):
    """
    Kupong: ett antal gratisdagar som plattformsadministratören skapar och
    säljaren löser in åt ett företag.

    Vad dagarna BLIR beror på företagets läge när kupongen löses in, och
    avgörs på servern (fleet/sales.py), inte av säljaren:

    * utan betalande abonnemang -- tillfällig åtkomst i `days` dagar för högst
      `vehicle_limit` bilar, som slutar utan debitering;
    * med abonnemang i Stripe -- nästa debitering flyttas `days` dagar;
    * med ett abonnemang som betalas utanför Stripe -- perioden förlängs.

    **Koden sparas i klartext**, till skillnad från parkopplings- och
    inbjudningskoderna. Den är en kampanjkod som ska kunna läsas upp i
    telefon och delas ut igen, inte en inloggning: den ger ingen åtkomst till
    något konto, bara gratisdagar åt det företag säljaren löser in den för,
    och den begränsas av `max_redemptions`, `valid_until` och en inlösen per
    företag.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=32, unique=True)
    description = models.TextField(blank=True, default="")
    days = models.IntegerField()
    vehicle_limit = models.IntegerField(default=3)
    # NULL = obegränsat antal inlösen.
    max_redemptions = models.IntegerField(null=True, blank=True)
    redemption_count = models.IntegerField(default=0)
    valid_until = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    deactivated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "fleet_coupon"


class CouponRedemption(models.Model):
    """En inlöst kupong: vilket företag, vad den blev och vem som löste in den."""

    class Effect(models.TextChoices):
        TEMPORARY_ACCESS = "temporary_access", "Tillfällig åtkomst"
        BILLING_DEFERRED = "billing_deferred", "Nästa debitering flyttad"
        PERIOD_EXTENDED = "period_extended", "Perioden förlängd"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    coupon = models.ForeignKey(Coupon, on_delete=models.PROTECT, related_name="redemptions")
    company_id = models.UUIDField()
    effect = models.CharField(max_length=20, choices=Effect.choices)
    days = models.IntegerField()
    trial = models.ForeignKey(Trial, null=True, blank=True, on_delete=models.SET_NULL)
    detail = models.JSONField(default=dict, blank=True)
    redeemed_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fleet_coupon_redemption"
        constraints = [
            # En kupong ger ett företag dagarna en gång. Två säljare som löser
            # in samma kod samtidigt ger en inlösen, inte två.
            models.UniqueConstraint(
                fields=["coupon", "company_id"], name="fleet_coupon_once_per_company"
            ),
        ]


class OwnerInvite(models.Model):
    """
    Inbjudan till kundens egen administratör, skapad av säljaren.

    Ingen kod och ingen länk med hemlighet: inbjudan knyts till en e-postadress,
    och den löses in när någon loggar in i kundportalen med just den adressen
    (fleet/api.py:claim_invite). Supabase Auth har då redan verifierat att
    personen kommer åt adressen -- det är det enda beviset som behövs, och det
    kan inte vidarebefordras som en kod kan.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Väntar"
        CONSUMED = "consumed", "Använd"
        REVOKED = "revoked", "Återkallad"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_id = models.UUIDField()
    email = models.TextField()
    role = models.CharField(max_length=32, default="company_owner")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    consumed_by_user = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "fleet_owner_invite"
        indexes = [models.Index(fields=["email", "status"])]
        constraints = [
            models.UniqueConstraint(
                fields=["company_id", "email"],
                condition=Q(status="pending"),
                name="fleet_one_pending_owner_invite",
            ),
        ]


# ---------------------------------------------------------------------------
# Bilar och licenser
# ---------------------------------------------------------------------------


class Vehicle(models.Model):
    """En registrerad bil. Registreringsnumret normaliseras (versaler, inga mellanslag)."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Aktiv"
        ARCHIVED = "archived", "Borttagen"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_id = models.UUIDField()
    plate = models.CharField(max_length=16)
    label = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "fleet_vehicle"
        indexes = [models.Index(fields=["company_id", "status"])]
        constraints = [
            models.UniqueConstraint(
                fields=["company_id", "plate"], condition=Q(status="active"),
                name="fleet_one_active_vehicle_per_plate",
            ),
        ]

    def __str__(self) -> str:
        return self.plate


class License(models.Model):
    """
    En billicens: det som faktiskt köps.

    Licensen hör till EN registrerad bil med ett baslän. Den är inte en fritt
    roterande plats mellan bilar -- vilken bil den betjänar just nu avgörs av
    den aktiva raden i `VehicleAssignment`, aldrig av ett fält som två flöden
    kan skriva samtidigt.

    Licensen bär sin egen livslängd (`ends_at`) men INTE sin betalperiod:
    perioden är företagets (`Subscription.current_period_*`), eftersom hela
    modellen är ett samlat abonnemang.
    """

    class Status(models.TextChoices):
        TRIAL = "trial", "Provbil"
        ACTIVE = "active", "Aktiv"
        PENDING_CANCEL = "pending_cancel", "Avslutas vid nästa förnyelse"
        CANCELED = "canceled", "Avslutad"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_id = models.UUIDField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ACTIVE)
    # Baslänet (SCB:s länskod). Ett byte träder i kraft vid nästa förnyelse och
    # ligger då i `scheduled_base_county` tills dess (§5).
    base_county = models.CharField(max_length=4)
    scheduled_base_county = models.CharField(max_length=4, blank=True, default="")

    trial = models.ForeignKey(Trial, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "fleet_license"
        indexes = [models.Index(fields=["company_id", "status"])]


class LicenseCounty(models.Model):
    """
    Länsrättigheterna hör till LICENSEN, inte till företaget: företagets
    samlade län får inte automatiskt tillfalla alla bilar (§5).

    Baslänet finns också som en rad här, så att åtkomstkontrollen har en enda
    lista att läsa i stället för att slå ihop ett fält och en tabell.
    """

    class Kind(models.TextChoices):
        BASE = "base", "Baslän"
        EXTRA = "extra", "Extra län"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    license = models.ForeignKey(License, on_delete=models.CASCADE, related_name="counties")
    county_code = models.CharField(max_length=4)
    kind = models.CharField(max_length=8, choices=Kind.choices)
    active_from = models.DateTimeField()
    # NULL = löper vidare. Satt = upphör då (minskning vid nästa förnyelse).
    active_to = models.DateTimeField(null=True, blank=True)
    order = models.ForeignKey("Order", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fleet_license_county"
        indexes = [models.Index(fields=["license", "county_code"])]
        constraints = [
            models.UniqueConstraint(
                fields=["license", "county_code"], condition=Q(active_to__isnull=True),
                name="fleet_one_open_county_row_per_license",
            ),
        ]


class VehicleAssignment(models.Model):
    """
    Vilken bil licensen betjänar, över tid.

    Exakt en öppen rad per licens (partiellt unikt index). Det är den
    invarianten som gör att ordinarie bil och ersättningsbil aldrig kan använda
    samma licens parallellt (§4) -- inte en kontroll i Python som en andra
    kodväg kan glömma.

    `case_ref` binder ihop en tillfällig ersättning med sin återgång. Återgång
    i samma ärende räknas inte som ett nytt byte i 30-dagarsräkningen (§4).
    """

    class Kind(models.TextChoices):
        INITIAL = "initial", "Första bilen"
        PERMANENT = "permanent", "Permanent bilbyte"
        TEMPORARY = "temporary", "Tillfällig ersättningsbil"
        RETURN = "return", "Återgång till ordinarie bil"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    license = models.ForeignKey(License, on_delete=models.CASCADE, related_name="assignments")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    case_ref = models.UUIDField(default=uuid.uuid4)
    started_at = models.DateTimeField()
    # Planerat slut för en tillfällig ersättning. Informativt: återgången görs
    # av ett uttryckligt anrop, inte av att klockan passerar ett fält.
    planned_end = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_reason = models.TextField(blank=True, default="")
    created_by = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "fleet_vehicle_assignment"
        indexes = [models.Index(fields=["license", "-started_at"])]
        constraints = [
            models.UniqueConstraint(
                fields=["license"], condition=Q(ended_at__isnull=True),
                name="fleet_one_open_assignment_per_license",
            ),
        ]


# ---------------------------------------------------------------------------
# Telefoner: godkännande, credentials, parkoppling
# ---------------------------------------------------------------------------


class DeviceApproval(models.Model):
    """
    En telefon som är godkänd för en bil. Kopplar `devices.id` (Supabase) till
    licens och bil.

    Spärr (borttappad telefon) sker här, av företagets administratör, utan
    tillgång till den gamla telefonen -- och gäller omedelbart även om enhetens
    token fortfarande är giltig. Det är därför åtkomstkontrollen alltid läser
    godkännandet och aldrig nöjer sig med att token finns.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Godkänd"
        BLOCKED = "blocked", "Spärrad"
        REPLACED = "replaced", "Ersatt"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_id = models.UUIDField()
    device_id = models.UUIDField()
    license = models.ForeignKey(License, on_delete=models.CASCADE, related_name="approvals")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    # Fri etikett som administratören satt ("Förare 2", "Nattbil"). Inget
    # personnummer, ingen IMEI -- se §10.
    label = models.TextField(blank=True, default="")
    approved_at = models.DateTimeField()
    approved_by = models.UUIDField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.UUIDField(null=True, blank=True)
    revoke_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "fleet_device_approval"
        indexes = [
            models.Index(fields=["device_id", "status"]),
            models.Index(fields=["license", "status"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["device_id", "license"], condition=Q(status="active"),
                name="fleet_one_active_approval_per_device_license",
            ),
        ]


class DeviceCredential(models.Model):
    """
    Enhetens hemlighet, hashad.

    Den gamla vägen (`devices.token` i klartext, utdelad av `join_device` ur en
    statisk bolagskod) finns kvar för redan parkopplade telefoner -- att dra
    den ur väggen hade låst ute varje befintlig förare, vilket §2 uttryckligen
    förbjuder. Nya parkopplingar får i stället en 256-bitars hemlighet som
    bara lagras som SHA-256 här; servern slår upp på hashen.

    `prefix` är de första tecknen i klartext och är INTE en hemlighet: den
    finns för att en supportfråga ska gå att besvara utan att någon läser upp
    hela token.
    """

    class Scheme(models.TextChoices):
        LEGACY_PLAINTEXT = "legacy_plaintext", "Äldre klartexttoken i devices.token"
        HASHED_V1 = "hashed_v1", "SHA-256-hashad hemlighet"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    device_id = models.UUIDField()
    company_id = models.UUIDField()
    token_hash = models.CharField(max_length=64, unique=True)
    prefix = models.CharField(max_length=12, blank=True, default="")
    scheme = models.CharField(max_length=20, choices=Scheme.choices, default=Scheme.HASHED_V1)
    approval = models.ForeignKey(
        DeviceApproval, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="credentials",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "fleet_device_credential"
        indexes = [models.Index(fields=["device_id", "revoked_at"])]


class PairingCode(models.Model):
    """
    Engångskoden/QR-koden som godkänner en telefon för en bil. Högst fem
    minuter.

    Koden lagras hashad och konsumeras atomiskt (ett villkorat UPDATE, se
    fleet.pairing). `attempts` räknas på KODEN; anropsfrekvensen begränsas
    dessutom per bolag i fleet.ratelimit, så att en angripare varken kan
    gissa en kod eller mala igenom många.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Väntar"
        CONSUMED = "consumed", "Använd"
        REVOKED = "revoked", "Återkallad"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_id = models.UUIDField()
    license = models.ForeignKey(License, on_delete=models.CASCADE)
    vehicle = models.ForeignKey(Vehicle, on_delete=models.CASCADE)
    code_hash = models.CharField(max_length=64, unique=True)
    label = models.TextField(blank=True, default="")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    attempts = models.IntegerField(default=0)
    max_attempts = models.IntegerField(default=5)
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    consumed_by_device = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "fleet_pairing_code"
        indexes = [models.Index(fields=["company_id", "-created_at"])]


class JoinRequest(models.Model):
    """
    Vad en statisk bolagskod får åstadkomma: en ANSÖKAN, inget mer.

    Den gamla `join_device()`-RPC:n delade ut en permanent enhetstoken direkt
    ur bolagskoden. Koden står på ett papper i fikarummet, och den som läste
    den fick betald data tills någon bytte kod. Här hittar koden bara företaget
    och lägger en rad som en administratör måste godkänna -- godkännandet sker
    genom det vanliga parkopplingsflödet med engångskod.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Väntar på godkännande"
        APPROVED = "approved", "Godkänd"
        REJECTED = "rejected", "Avvisad"
        EXPIRED = "expired", "Förfallen"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_id = models.UUIDField()
    label = models.TextField(blank=True, default="")
    installation_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "fleet_join_request"
        indexes = [models.Index(fields=["company_id", "status", "-created_at"])]


# ---------------------------------------------------------------------------
# Skiftbyte: aktiv bilsession
# ---------------------------------------------------------------------------


class VehicleSession(models.Model):
    """
    Den aktiva bilsessionen. Exakt en telefon per billicens, exakt en bil per
    telefon.

    Båda reglerna är partiella unika index, inte Python-kontroller: två
    samtidiga övertaganden går in i samma millisekund och en kontroll i
    applikationen hade släppt igenom båda. Databasen avgör vem som vann; den
    som förlorar läser om och får `takeover_conflict`.

    En avslutad session återupplivas aldrig. Den gamla telefonen kan förnya
    sin token, komma tillbaka ur bakgrunden eller återansluta hur den vill --
    utan en öppen rad här har den ingen åtkomst (§3).
    """

    class EndReason(models.TextChoices):
        TAKEOVER = "takeover", "Övertagen av annan telefon"
        DRIVER_END = "driver_end", "Föraren lämnade bilen"
        DEVICE_MOVED = "device_moved", "Telefonen tog en annan bil"
        BLOCKED = "blocked", "Spärrad av administratör"
        LICENSE_CHANGE = "license_change", "Licensen ändrades"
        EXPIRED = "expired", "Tidsgräns"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_id = models.UUIDField()
    license = models.ForeignKey(License, on_delete=models.CASCADE, related_name="sessions")
    vehicle = models.ForeignKey(Vehicle, on_delete=models.PROTECT)
    device_id = models.UUIDField()
    approval = models.ForeignKey(DeviceApproval, on_delete=models.CASCADE)
    started_at = models.DateTimeField()
    last_seen_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_reason = models.CharField(max_length=20, choices=EndReason.choices, blank=True, default="")
    ended_by_device = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "fleet_vehicle_session"
        indexes = [
            models.Index(fields=["device_id", "ended_at"]),
            models.Index(fields=["license", "-started_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["license"], condition=Q(ended_at__isnull=True),
                name="fleet_one_active_session_per_license",
            ),
            models.UniqueConstraint(
                fields=["device_id"], condition=Q(ended_at__isnull=True),
                name="fleet_one_active_session_per_device",
            ),
        ]


# ---------------------------------------------------------------------------
# Beställningar och väntande ändringar
# ---------------------------------------------------------------------------


class Order(models.Model):
    """
    En beställning. Beloppen räknas ut på servern och sparas här -- klienten
    visar det servern räknat, aldrig tvärtom.

    `lines` bär den uträkning kunden såg: post för post, med antal, styckpris
    och proportionering. En faktura som inte går att förklara i efterhand är
    en supportfråga som inte går att avsluta.
    """

    class Kind(models.TextChoices):
        INITIAL = "initial", "Första beställningen"
        ADD_LICENSE = "add_license", "Fler billicenser"
        ADD_COUNTY = "add_county", "Extra län"
        REDUCE = "reduce", "Minskning vid nästa förnyelse"
        CHANGE_BASE_COUNTY = "change_base_county", "Byte av baslän"
        RENEWAL = "renewal", "Förnyelse"

    class Status(models.TextChoices):
        DRAFT = "draft", "Utkast"
        PENDING_PAYMENT = "pending_payment", "Väntar på betalning"
        PAID = "paid", "Betald"
        FAILED = "failed", "Misslyckad"
        CANCELED = "canceled", "Avbruten"
        SCHEDULED = "scheduled", "Schemalagd till nästa förnyelse"
        APPLIED = "applied", "Verkställd"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_id = models.UUIDField()
    kind = models.CharField(max_length=24, choices=Kind.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    price_version = models.ForeignKey(PriceVersion, on_delete=models.PROTECT)

    quantity_before = models.IntegerField(default=0)
    quantity_after = models.IntegerField(default=0)

    # Allt i ören, exklusive moms där inget annat sägs.
    amount_now_ore = models.IntegerField(default=0)
    vat_now_ore = models.IntegerField(default=0)
    total_now_ore = models.IntegerField(default=0)
    next_period_amount_ore = models.IntegerField(default=0)
    next_period_vat_ore = models.IntegerField(default=0)
    next_period_total_ore = models.IntegerField(default=0)
    currency = models.CharField(max_length=3, default="SEK")

    effective_at = models.DateTimeField(null=True, blank=True)
    lines = models.JSONField(default=list, blank=True)
    request = models.JSONField(default=dict, blank=True)

    terms_version = models.CharField(max_length=32, blank=True, default="")
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    idempotency_key = models.CharField(max_length=64, unique=True, null=True, blank=True)
    stripe_invoice_id = models.TextField(blank=True, default="")
    # Stripes betalsida för fakturan (`hosted_invoice_url`). Ingen hemlighet --
    # den visar fakturan och tar emot betalningen -- men den visas bara för
    # kundens egna administratörer och plattformens personal.
    stripe_payment_url = models.TextField(blank=True, default="")
    stripe_payment_intent_id = models.TextField(blank=True, default="")
    stripe_checkout_session_id = models.TextField(blank=True, default="")
    paid_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    failure_reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "fleet_order"
        indexes = [models.Index(fields=["company_id", "-created_at"])]


class PendingChange(models.Model):
    """
    En ändring som träder i kraft vid nästa förnyelse.

    Samlade, så att en uppsägning kan stänga av allt annat schemalagt i samma
    steg (§9): annars hade en minskning kunnat ligga kvar och förnya ett
    abonnemang kunden sagt upp.
    """

    class Kind(models.TextChoices):
        REDUCE_LICENSES = "reduce_licenses", "Avsluta billicenser"
        REMOVE_COUNTY = "remove_county", "Ta bort extra län"
        CHANGE_BASE_COUNTY = "change_base_county", "Byt baslän"
        CANCEL_SUBSCRIPTION = "cancel_subscription", "Säg upp abonnemanget"

    class Status(models.TextChoices):
        PENDING = "pending", "Väntar"
        APPLIED = "applied", "Verkställd"
        CANCELED = "canceled", "Ångrad"
        SUPERSEDED = "superseded", "Ersatt"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_id = models.UUIDField()
    kind = models.CharField(max_length=24, choices=Kind.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    payload = models.JSONField(default=dict, blank=True)
    order = models.ForeignKey(Order, null=True, blank=True, on_delete=models.SET_NULL)
    effective_at = models.DateTimeField()
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "fleet_pending_change"
        indexes = [models.Index(fields=["company_id", "status", "effective_at"])]


# ---------------------------------------------------------------------------
# Risk, granskning och revision
# ---------------------------------------------------------------------------


class RiskConfig(models.Model):
    """
    Riskgränserna, konfigurerbara (§4). En rad, id=1.

    Startvärdena står i defaults och är precis det: startvärden. De stänger
    aldrig av ett betalande företag -- de kräver extra verifiering för NÄSTA
    ändring, och senast giltig åtkomst ligger kvar under tiden.
    """

    id = models.IntegerField(primary_key=True, default=1)
    new_pairings_per_vehicle_24h = models.IntegerField(default=3)
    takeovers_per_hour = models.IntegerField(default=6)
    vehicle_changes_per_30d = models.IntegerField(default=2)
    pairing_code_ttl_seconds = models.IntegerField(default=300)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "fleet_risk_config"

    @classmethod
    def current(cls) -> "RiskConfig":
        obj, _ = cls.objects.get_or_create(id=1)
        return obj


class RiskSignal(models.Model):
    """Den räknebara historiken bakom riskgränserna. En rad per händelse."""

    class Kind(models.TextChoices):
        PAIRING = "pairing", "Ny telefonanslutning"
        TAKEOVER = "takeover", "Övertagande"
        VEHICLE_CHANGE = "vehicle_change", "Byte av fysisk bil"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_id = models.UUIDField()
    kind = models.CharField(max_length=20, choices=Kind.choices)
    license = models.ForeignKey(License, null=True, blank=True, on_delete=models.CASCADE)
    vehicle = models.ForeignKey(Vehicle, null=True, blank=True, on_delete=models.CASCADE)
    device_id = models.UUIDField(null=True, blank=True)
    case_ref = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField()

    class Meta:
        db_table = "fleet_risk_signal"
        indexes = [
            models.Index(fields=["company_id", "kind", "-created_at"]),
            models.Index(fields=["vehicle", "kind", "-created_at"]),
            models.Index(fields=["license", "kind", "-created_at"]),
        ]


class ChangeReview(models.Model):
    """
    Granskningsärendet kunden kan se status på.

    Den ÖPPNAR aldrig ett ärende genom att stänga av företaget: åtkomsten som
    redan gäller ligger kvar, och det är nästa självbetjäningsändring som
    kräver ett godkännande (§4).
    """

    class Status(models.TextChoices):
        OPEN = "open", "Under granskning"
        APPROVED = "approved", "Godkänd"
        REJECTED = "rejected", "Avslagen"

    class Kind(models.TextChoices):
        PAIRING_RATE = "pairing_rate", "Många nya telefonanslutningar"
        TAKEOVER_RATE = "takeover_rate", "Många övertaganden"
        VEHICLE_CHANGE_RATE = "vehicle_change_rate", "Många bilbyten"
        COMPANY_VERIFICATION = "company_verification", "Företagsuppgifter"
        OWNERSHIP_TRANSFER = "ownership_transfer", "Byte av ägare/avtalspart"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_id = models.UUIDField()
    kind = models.CharField(max_length=24, choices=Kind.choices)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    # Begriplig status för kunden -- inte en intern kod.
    customer_message = models.TextField(blank=True, default="")
    detail = models.JSONField(default=dict, blank=True)
    license = models.ForeignKey(License, null=True, blank=True, on_delete=models.SET_NULL)
    vehicle = models.ForeignKey(Vehicle, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.UUIDField(null=True, blank=True)
    resolution_note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "fleet_change_review"
        indexes = [models.Index(fields=["company_id", "status", "-created_at"])]


class AuditEvent(models.Model):
    """
    Revisionslogg. Godkännande, spärr, köp, uppsägning, ägarbyte.

    Inga hemligheter: aldrig en token, aldrig en kod, aldrig ett lösenord.
    `detail` får bära id:n och beslut, inte credentials (§2).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_id = models.UUIDField(null=True, blank=True)
    actor_user_id = models.UUIDField(null=True, blank=True)
    actor_kind = models.CharField(max_length=24, default="system")
    action = models.CharField(max_length=64)
    subject_type = models.CharField(max_length=32, blank=True, default="")
    subject_id = models.CharField(max_length=64, blank=True, default="")
    detail = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fleet_audit_event"
        indexes = [
            models.Index(fields=["company_id", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
        ]


class OwnershipTransfer(models.Model):
    """
    Överföring av ägarrollen inom företaget: ny autentisering hos avsändaren
    och uttrycklig acceptans hos mottagaren (§10).
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Väntar på mottagarens acceptans"
        ACCEPTED = "accepted", "Genomförd"
        DECLINED = "declined", "Avböjd"
        EXPIRED = "expired", "Förfallen"
        CANCELED = "canceled", "Avbruten"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_id = models.UUIDField()
    from_user_id = models.UUIDField()
    to_user_id = models.UUIDField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "fleet_ownership_transfer"
        constraints = [
            models.UniqueConstraint(
                fields=["company_id"], condition=Q(status="pending"),
                name="fleet_one_pending_ownership_transfer",
            ),
        ]


class OutboxMessage(models.Model):
    """
    Bekräftelser och påminnelser (§10). Dedupliceras på `dedupe_key`, så att en
    omkörd task eller en dubblerad webhook inte skickar två gånger.

    Tjänstemeddelanden (aktivering, provslut, betalningsfel, uppsägning) hålls
    åtskilda från marknadsföring genom `channel`/`category`: ett avregistrerat
    marknadsföringsval får inte tysta en faktura som misslyckats.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Väntar"
        SENT = "sent", "Skickad"
        FAILED = "failed", "Misslyckad"
        SUPPRESSED = "suppressed", "Undertryckt"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_id = models.UUIDField(null=True, blank=True)
    category = models.CharField(max_length=40)
    channel = models.CharField(max_length=16, default="email")
    to_address = models.TextField(blank=True, default="")
    subject = models.TextField(blank=True, default="")
    body = models.TextField(blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    dedupe_key = models.CharField(max_length=128, unique=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "fleet_outbox_message"
        indexes = [models.Index(fields=["status", "-created_at"])]


class KnownAccount(models.Model):
    """
    Inloggade konton som servern har sett, med e-postadressen ur den VERIFIERADE
    token.

    **Varför en egen katalog.** Adminwebben måste kunna söka på en e-postadress
    och spärra den, men `auth.users` hör till Supabase Auth och Djangos roll i
    produktion ska inte behöva läsrätt där. Adressen skrivs när kontot anropar
    servern (fleet/accounts.py:seen), aldrig ur något klienten påstår.
    """

    user_id = models.UUIDField(primary_key=True)
    email = models.TextField(db_index=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField()

    class Meta:
        db_table = "fleet_known_account"


class AccountBlock(models.Model):
    """
    En spärr som plattformens personal lagt: ett helt företag, en e-postadress
    eller ett enskilt konto.

    Spärren kontrolleras på varje begäran i fleet/access.py -- inte genom att
    radera något. Ett spärrat företag behåller bilar, licenser och historik, så
    att en hävd spärr återställer exakt det som fanns. Hävningen skriver
    `lifted_at` i stället för att ta bort raden: vem som spärrade, varför och
    när ska gå att läsa i efterhand.
    """

    class Kind(models.TextChoices):
        COMPANY = "company", "Företag"
        EMAIL = "email", "E-postadress"
        USER = "user", "Konto"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=10, choices=Kind.choices)
    # Företagets uuid, kontots uuid eller e-postadressen i gemener.
    value = models.CharField(max_length=320)
    reason = models.TextField()
    created_by = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    lifted_at = models.DateTimeField(null=True, blank=True)
    lifted_by = models.UUIDField(null=True, blank=True)
    lift_note = models.TextField(blank=True, default="")

    class Meta:
        db_table = "fleet_account_block"
        constraints = [
            # En aktiv spärr per sak: två spärrar hade krävt två hävningar.
            models.UniqueConstraint(
                fields=["kind", "value"], condition=Q(lifted_at__isnull=True),
                name="fleet_one_active_block",
            ),
        ]


class SupportThread(models.Model):
    """
    Supportchatten: EN konversation per användare, som öppnas igen när
    användaren skriver.

    Användaren är antingen ett inloggat konto (ägare, administratör) eller en
    förartelefon -- förare har inget konto, bara en parkopplad telefon. En
    konversation per bolag hade låtit förarna läsa varandras och ägarens frågor.

    `company_id` och `requester_label` är en ögonblicksbild för supportens
    lista. Ett konto utan företag (registreringen är inte klar) kan ändå skriva:
    det är just då frågorna uppstår.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Öppen"
        CLOSED = "closed", "Avslutad"

    class Requester(models.TextChoices):
        MEMBER = "member", "Konto"
        DEVICE = "device", "Förartelefon"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    company_id = models.UUIDField(null=True, blank=True)
    requester_kind = models.CharField(max_length=10, choices=Requester.choices)
    user_id = models.UUIDField(null=True, blank=True)
    device_id = models.UUIDField(null=True, blank=True)
    requester_label = models.TextField(blank=True, default="")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    created_at = models.DateTimeField(auto_now_add=True)
    last_message_at = models.DateTimeField(null=True, blank=True)
    last_customer_message_at = models.DateTimeField(null=True, blank=True)
    last_staff_message_at = models.DateTimeField(null=True, blank=True)
    # Olästa räknas mot de här: användarens läsning mot supportens svar, och
    # tvärtom. Ingen räknare som kan glida isär från meddelandena.
    customer_read_at = models.DateTimeField(null=True, blank=True)
    staff_read_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.UUIDField(null=True, blank=True)

    class Meta:
        db_table = "fleet_support_thread"
        indexes = [
            models.Index(fields=["status", "-last_message_at"]),
            models.Index(fields=["company_id"]),
        ]
        constraints = [
            # En konversation per konto och per telefon. Två samtidiga första
            # meddelanden får inte skapa två trådar som supporten svarar i var
            # för sig.
            models.UniqueConstraint(
                fields=["user_id"], condition=Q(user_id__isnull=False),
                name="fleet_support_one_thread_per_user",
            ),
            models.UniqueConstraint(
                fields=["device_id"], condition=Q(device_id__isnull=False),
                name="fleet_support_one_thread_per_device",
            ),
            models.CheckConstraint(
                condition=(
                    Q(requester_kind="member", user_id__isnull=False, device_id__isnull=True)
                    | Q(requester_kind="device", device_id__isnull=False, user_id__isnull=True)
                ),
                name="fleet_support_requester_matches_kind",
            ),
        ]


class SupportMessage(models.Model):
    """Ett meddelande i supportchatten. Bara text; inga filer (beslut 2026-09-26)."""

    class Sender(models.TextChoices):
        CUSTOMER = "customer", "Användaren"
        STAFF = "staff", "Support"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    thread = models.ForeignKey(SupportThread, on_delete=models.CASCADE, related_name="messages")
    sender = models.CharField(max_length=10, choices=Sender.choices)
    # Vem som skrev: kontot (användare eller personal) eller telefonen.
    author_user_id = models.UUIDField(null=True, blank=True)
    author_device_id = models.UUIDField(null=True, blank=True)
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "fleet_support_message"
        indexes = [models.Index(fields=["thread", "created_at"])]
