"""
Säljflödet: det en säljare gör i adminwebben under ett samtal med ett taxibolag.

1. **Företaget** läggs upp med organisationsnummer, kontaktperson och
   fakturauppgifter (`create_company`). Organisationsnumret kontrolleras
   (Luhn) och får bara finnas en gång -- ett andra konto för samma bolag hade
   gett ett andra gratisprov och två sanningar om vem som betalar.
2. **Starten** blir ett av tre:
   * ett kortfritt prov i 14 dagar med högst tre bilar (`start_trial`), under
     samma regler som självregistreringen: ett prov per organisationsnummer
     och 24 månader;
   * en kupong (`redeem_coupon`), se `fleet.models.Coupon`;
   * en betald beställning (fleet/commerce.py) med betallänk från Stripe.
3. **Förarna** får engångskoder per bil (fleet/pairing.py, fem minuter).
4. **Kundens administratör** bjuds in med sin e-postadress (`invite_owner`)
   och kommer in i kundportalen när hen loggar in med den.

Varje steg loggas i `fleet_audit_event` med `actor_kind="sales"`, så att det
syns vad som gjorts i telefon och av vem.
"""

from __future__ import annotations

import re
import secrets
import uuid
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from billing.models import Company, CompanyMember
from fleet import audit, licensing, orders, orgnr, stripe_sync, trials
from fleet.models import (
    CompanyProfile,
    Coupon,
    CouponRedemption,
    License,
    OwnerInvite,
    Subscription,
    SubscriptionStatus,
    Trial,
    VerificationStatus,
)

_JOIN_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_COUPON_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
OWNER_INVITE_DAYS = 14
COUPON_MAX_DAYS = 365
COUPON_MAX_VEHICLES = 50


class SalesError(Exception):
    def __init__(self, reason: str, message: str, status: int = 400, detail: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.message = message
        self.status = status
        self.detail = detail or {}


def _clean(value, limit: int = 200) -> str:
    return str(value or "").strip()[:limit]


def _email(value, field: str, *, required: bool = False) -> str:
    email = _clean(value, 254).lower()
    if not email:
        if required:
            raise SalesError("email_required", f"Ange {field}.")
        return ""
    if not _EMAIL.match(email):
        raise SalesError("invalid_email", f"{field.capitalize()} ser inte ut som en e-postadress.")
    return email


def _address(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "line1": _clean(raw.get("line1"), 200),
        "line2": _clean(raw.get("line2"), 200),
        "postal_code": _clean(raw.get("postal_code") or raw.get("postalCode"), 20),
        "city": _clean(raw.get("city"), 100),
        "country": (_clean(raw.get("country"), 2) or "SE").upper(),
    }


# ---------------------------------------------------------------------------
# Företaget
# ---------------------------------------------------------------------------


def existing_company_for(org_number: str, country: str = "SE") -> Company | None:
    normalized = orgnr.normalize(org_number, country)
    if not normalized:
        return None
    company = Company.objects.filter(org_number=normalized).first()
    if company is not None:
        return company
    profile = CompanyProfile.objects.filter(org_number=normalized, country=country.upper()).first()
    if profile is not None:
        return Company.objects.filter(id=profile.company_id).first()
    return None


def lookup(org_number: str, country: str = "SE") -> dict:
    """Vad säljaren behöver veta om ett organisationsnummer innan något skapas."""
    country = (country or "SE").upper()
    normalized = orgnr.normalize(org_number, country)
    valid = orgnr.is_valid(org_number, country)
    existing = existing_company_for(org_number, country) if valid else None
    eligibility = trials.eligibility(country=country, org_number=org_number) if valid else None
    return {
        "orgNumber": orgnr.format_se(normalized) if country == "SE" else normalized,
        "normalized": normalized,
        "valid": valid,
        "existingCompany": (
            {"id": str(existing.id), "name": existing.name} if existing else None
        ),
        "trial": eligibility.as_dict() if eligibility else None,
    }


def _new_join_code() -> str:
    for _ in range(20):
        code = "".join(secrets.choice(_JOIN_ALPHABET) for _ in range(6))
        if not Company.objects.filter(join_code=code).exists():
            return code
    raise SalesError("join_code_failed", "Kunde inte skapa en bolagskod. Försök igen.", status=500)


@transaction.atomic
def create_company(
    *,
    name: str,
    org_number: str,
    country: str = "SE",
    legal_name: str = "",
    contact_name: str,
    contact_role: str = "",
    contact_email: str,
    contact_phone: str = "",
    billing_email: str = "",
    billing_reference: str = "",
    billing_address: dict | None = None,
    verification_note: str,
    actor_user_id,
) -> Company:
    """
    Lägger upp ett nytt kundföretag.

    `verification_note` är obligatorisk av samma skäl som för säljarinbjudan
    (§7): den är det enda spåret av HUR säljaren kontrollerade att personen i
    telefon får företräda bolaget.
    """
    country = (country or "SE").upper()
    name = _clean(name, 200)
    if not name:
        raise SalesError("name_required", "Ange företagets namn.")
    if not orgnr.is_valid(org_number, country):
        raise SalesError("invalid_org_number", "Organisationsnumret går inte att tolka.")
    normalized = orgnr.normalize(org_number, country)
    existing = existing_company_for(normalized, country)
    if existing is not None:
        raise SalesError(
            "company_exists",
            f"{existing.name} finns redan med det organisationsnumret.",
            status=409, detail={"companyId": str(existing.id), "name": existing.name},
        )
    contact_name = _clean(contact_name, 200)
    if not contact_name:
        raise SalesError("contact_required", "Ange kontaktpersonens namn.")
    contact_email = _email(contact_email, "kontaktpersonens e-post", required=True)
    billing_email = _email(billing_email, "fakturamejlen") or contact_email
    note = _clean(verification_note, 1000)
    if not note:
        raise SalesError(
            "verification_note_required",
            "Skriv hur du kontrollerade att kontaktpersonen får företräda bolaget.",
        )

    company = Company.objects.create(
        id=uuid.uuid4(), name=name, email=billing_email, org_number=normalized,
        join_code=_new_join_code(), seats=1,
        # Den gamla statusen i `companies` ger ingen åtkomst för ett företag
        # som har ett abonnemang i den nya modellen -- `inactive` gör att den
        # inte heller gör det i någon äldre kodväg som fortfarande läser den.
        status="inactive", subscription_status="inactive", created_at=timezone.now(),
    )
    CompanyProfile.objects.create(
        company_id=company.id, country=country, org_number=normalized,
        legal_name=_clean(legal_name, 200) or name,
        contact_name=contact_name, contact_role=_clean(contact_role, 100),
        contact_email=contact_email, contact_phone=_clean(contact_phone, 40),
        billing_email=billing_email, billing_reference=_clean(billing_reference, 100),
        billing_address=_address(billing_address),
        verification_status=VerificationStatus.VERIFIED,
        verification_note=note,
    )
    orders.get_or_create_subscription(company.id)
    audit.record(
        "sales_company_created", company_id=company.id, actor_user_id=actor_user_id,
        actor_kind="sales", subject_type="company", subject_id=company.id,
        detail={"org_number": normalized, "name": name, "verification_note": note[:300]},
    )
    return company


def update_profile(company: Company, data: dict, *, actor_user_id) -> CompanyProfile:
    """
    Ändrar kund- och fakturauppgifter. Organisationsnumret går inte att ändra
    här: ett nytt organisationsnummer är en ny avtalspart (fleet/ownership.py).
    """
    profile, _ = CompanyProfile.objects.get_or_create(
        company_id=company.id,
        defaults={"country": "SE", "org_number": company.org_number or ""},
    )
    changed = {}
    fields = {
        "legal_name": ("legalName", 200), "contact_name": ("contactName", 200),
        "contact_role": ("contactRole", 100), "contact_phone": ("contactPhone", 40),
        "billing_reference": ("billingReference", 100),
    }
    for field, (key, limit) in fields.items():
        if key in data:
            value = _clean(data.get(key), limit)
            if value != getattr(profile, field):
                changed[field] = value
    if "contactEmail" in data:
        value = _email(data.get("contactEmail"), "kontaktpersonens e-post", required=True)
        if value != profile.contact_email:
            changed["contact_email"] = value
    if "billingEmail" in data:
        value = _email(data.get("billingEmail"), "fakturamejlen")
        if value != profile.billing_email:
            changed["billing_email"] = value
    if "billingAddress" in data:
        value = _address(data.get("billingAddress"))
        if value != (profile.billing_address or {}):
            changed["billing_address"] = value

    company_changes = {}
    if "name" in data:
        name = _clean(data.get("name"), 200)
        if not name:
            raise SalesError("name_required", "Ange företagets namn.")
        if name != company.name:
            company_changes["name"] = name
    if "billing_email" in changed:
        company_changes["email"] = changed["billing_email"] or profile.contact_email

    if not changed and not company_changes:
        return profile
    if changed:
        CompanyProfile.objects.filter(company_id=company.id).update(**changed)
    if company_changes:
        Company.objects.filter(id=company.id).update(**company_changes)
    profile.refresh_from_db()
    company.refresh_from_db()
    audit.record(
        "sales_company_updated", company_id=company.id, actor_user_id=actor_user_id,
        actor_kind="sales", subject_type="company", subject_id=company.id,
        detail={"fields": sorted([*changed.keys(), *company_changes.keys()])},
    )

    subscription = Subscription.objects.filter(company_id=company.id).first()
    if subscription and (subscription.stripe_customer_id or company.stripe_customer_id):
        if stripe_sync.available():
            try:
                stripe_sync.update_customer(company, subscription)
            except Exception:
                audit.record(
                    "stripe_not_updated", company_id=company.id, actor_kind="system",
                    subject_type="company", subject_id=company.id,
                    detail={"step": "update_customer"},
                )
    return profile


# ---------------------------------------------------------------------------
# Prov och tillfällig åtkomst
# ---------------------------------------------------------------------------


def _vehicle_specs(raw: list) -> list[orders.VehicleSpec]:
    specs = []
    for v in raw or []:
        specs.append(orders.VehicleSpec(
            plate=str(v.get("plate", "")), base_county=str(v.get("baseCounty", "")),
            label=str(v.get("label", "")), extra_counties=[str(c) for c in (v.get("extraCounties") or [])],
        ))
    return specs


def _add_trial_vehicles(trial: Trial, specs: list[orders.VehicleSpec], *, actor_user_id, now) -> list[License]:
    """
    Provbilar: licens med status `trial`, baslän och de län kunden vill prova.
    Länen kostar inget under provet; de följer med bara om kunden beställer
    dem (fleet/orders.py:apply_order).
    """
    if not specs:
        raise SalesError("vehicles_required", "Lägg till minst en bil.")
    current = trials.trial_vehicle_count(trial)
    if current + len(specs) > trial.vehicle_limit:
        raise SalesError(
            "trial_vehicle_limit",
            f"Högst {trial.vehicle_limit} bilar ({current} finns redan).",
        )
    created = []
    for spec in specs:
        licensing.assert_county_available(spec.base_county)
        for county in spec.extra_counties:
            licensing.assert_county_available(county)
        vehicle = licensing.create_vehicle(
            company_id=trial.company_id, plate=spec.plate, label=spec.label,
            actor_user_id=actor_user_id,
        )
        license = licensing.create_license(
            company_id=trial.company_id, vehicle=vehicle, base_county=spec.base_county,
            status=License.Status.TRIAL, trial=trial, actor_user_id=actor_user_id, now=now,
        )
        for county in spec.extra_counties:
            if county != spec.base_county:
                licensing.activate_extra_county(license=license, county_code=county, now=now)
        created.append(license)
    return created


def _profile_or_error(company: Company) -> CompanyProfile:
    profile = CompanyProfile.objects.filter(company_id=company.id).first()
    if profile is None or not profile.org_number:
        raise SalesError("org_number_missing", "Företaget saknar organisationsnummer.")
    return profile


@transaction.atomic
def start_trial(company: Company, vehicles: list, *, actor_user_id, now=None) -> Trial:
    """
    Kortfritt prov i 14 dagar, eller fler provbilar i ett pågående prov.

    Samma regler som självregistreringen: ett prov per organisationsnummer och
    24 månader, högst tre bilar, och klockan startar vid första telefonen.
    Utan beställning slutar provet utan debitering.
    """
    now = now or timezone.now()
    specs = _vehicle_specs(vehicles)
    trial = trials.active_trial(company.id)
    if trial is None:
        profile = _profile_or_error(company)
        trial = trials.create_trial(
            company_id=company.id, country=profile.country, org_number=profile.org_number,
            source=Trial.Source.SALES, requires_payment_method=False,
            actor_user_id=actor_user_id, now=now,
        )
    _add_trial_vehicles(trial, specs, actor_user_id=actor_user_id, now=now)
    orders.get_or_create_subscription(company.id)
    audit.record(
        "sales_trial_started", company_id=company.id, actor_user_id=actor_user_id,
        actor_kind="sales", subject_type="trial", subject_id=trial.id,
        detail={"vehicles": [s.as_dict()["plate"] for s in specs]},
    )
    trial.refresh_from_db()
    return trial


# ---------------------------------------------------------------------------
# Kuponger
# ---------------------------------------------------------------------------


def normalize_coupon_code(value) -> str:
    return re.sub(r"[^A-Z0-9-]", "", str(value or "").strip().upper())[:32]


def create_coupon(
    *,
    code: str = "",
    description: str = "",
    days: int,
    vehicle_limit: int = 3,
    max_redemptions: int | None = None,
    valid_until=None,
    actor_user_id,
) -> Coupon:
    code = normalize_coupon_code(code)
    if not code:
        code = "TT-" + "".join(secrets.choice(_COUPON_ALPHABET) for _ in range(6))
    if len(code) < 4:
        raise SalesError("invalid_code", "Koden ska ha minst fyra tecken (A–Z, 0–9, -).")
    try:
        days = int(days)
        vehicle_limit = int(vehicle_limit or 3)
        max_redemptions = int(max_redemptions) if max_redemptions not in (None, "") else None
    except (TypeError, ValueError):
        raise SalesError("invalid_number", "Dagar, bilar och antal inlösen ska vara heltal.")
    if not 1 <= days <= COUPON_MAX_DAYS:
        raise SalesError("invalid_days", f"Dagar: 1–{COUPON_MAX_DAYS}.")
    if not 1 <= vehicle_limit <= COUPON_MAX_VEHICLES:
        raise SalesError("invalid_vehicle_limit", f"Bilar: 1–{COUPON_MAX_VEHICLES}.")
    if max_redemptions is not None and max_redemptions < 1:
        raise SalesError("invalid_max", "Antal inlösen ska vara minst 1, eller tomt för obegränsat.")
    try:
        coupon = Coupon.objects.create(
            code=code, description=_clean(description, 300), days=days,
            vehicle_limit=vehicle_limit, max_redemptions=max_redemptions,
            valid_until=valid_until, created_by=actor_user_id,
        )
    except IntegrityError:
        raise SalesError("code_taken", f"Koden {code} finns redan.", status=409)
    audit.record(
        "coupon_created", actor_user_id=actor_user_id, actor_kind="platform_admin",
        subject_type="coupon", subject_id=coupon.id,
        detail={"code": code, "days": days, "vehicle_limit": vehicle_limit,
                "max_redemptions": max_redemptions},
    )
    return coupon


def deactivate_coupon(coupon: Coupon, *, actor_user_id, now=None) -> Coupon:
    now = now or timezone.now()
    Coupon.objects.filter(id=coupon.id).update(is_active=False, deactivated_at=now)
    audit.record(
        "coupon_deactivated", actor_user_id=actor_user_id, actor_kind="platform_admin",
        subject_type="coupon", subject_id=coupon.id, detail={"code": coupon.code},
    )
    coupon.refresh_from_db()
    return coupon


def _usable_coupon(code: str, now) -> Coupon:
    normalized = normalize_coupon_code(code)
    coupon = Coupon.objects.select_for_update().filter(code=normalized).first()
    if coupon is None or not coupon.is_active:
        raise SalesError("invalid_coupon", "Kupongen finns inte eller är avstängd.", status=404)
    if coupon.valid_until and coupon.valid_until <= now:
        raise SalesError("coupon_expired", "Kupongen har gått ut.")
    if coupon.max_redemptions is not None and coupon.redemption_count >= coupon.max_redemptions:
        raise SalesError("coupon_used_up", "Kupongen är redan använd så många gånger den får.")
    return coupon


@transaction.atomic
def redeem_coupon(company: Company, code: str, *, vehicles: list | None = None, actor_user_id, now=None) -> CouponRedemption:
    """
    Löser in en kupong åt ett företag. Vad den blir avgörs av företagets läge,
    se `fleet.models.Coupon`. Kupongraden låses, så att två inlösen samtidigt
    inte kan gå förbi `max_redemptions`.
    """
    now = now or timezone.now()
    coupon = _usable_coupon(code, now)
    if CouponRedemption.objects.filter(coupon=coupon, company_id=company.id).exists():
        raise SalesError("already_redeemed", "Företaget har redan använt den här kupongen.", status=409)

    subscription = orders.get_or_create_subscription(company.id)
    days = coupon.days
    detail: dict = {}
    trial = None

    paying = subscription.status in (
        SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING, SubscriptionStatus.PAST_DUE
    ) and subscription.current_period_end is not None and subscription.current_period_end > now

    if paying and subscription.stripe_subscription_id:
        # Betalande i Stripe: nästa debitering flyttas. Utan Stripe-kontakt går
        # det inte -- att bara förlänga perioden hos oss hade gett kunden en
        # faktura i dag ändå.
        if not stripe_sync.available():
            raise SalesError(
                "stripe_unavailable",
                "Företaget betalar via Stripe, och Stripe är inte kopplat här. Kupongen kan inte "
                "flytta debiteringen.", status=503,
            )
        try:
            new_end = stripe_sync.defer_billing(subscription, days)
        except Exception as exc:
            raise SalesError("stripe_error", f"Stripe svarade med ett fel: {str(exc)[:200]}", status=502)
        Subscription.objects.filter(id=subscription.id).update(current_period_end=new_end)
        effect = CouponRedemption.Effect.BILLING_DEFERRED
        detail = {"nextBillingAt": new_end.isoformat()}
    elif paying:
        new_end = subscription.current_period_end + timedelta(days=days)
        Subscription.objects.filter(id=subscription.id).update(current_period_end=new_end)
        effect = CouponRedemption.Effect.PERIOD_EXTENDED
        detail = {"periodEnd": new_end.isoformat()}
    else:
        trial = _temporary_access(company, coupon, _vehicle_specs(vehicles or []),
                                  actor_user_id=actor_user_id, now=now)
        effect = CouponRedemption.Effect.TEMPORARY_ACCESS
        detail = {"accessUntil": trial.ends_at.isoformat() if trial.ends_at else None,
                  "vehicleLimit": trial.vehicle_limit}

    try:
        redemption = CouponRedemption.objects.create(
            coupon=coupon, company_id=company.id, effect=effect, days=days, trial=trial,
            detail=detail, redeemed_by=actor_user_id,
        )
    except IntegrityError:
        raise SalesError("already_redeemed", "Företaget har redan använt den här kupongen.", status=409)
    Coupon.objects.filter(id=coupon.id).update(redemption_count=coupon.redemption_count + 1)
    audit.record(
        "coupon_redeemed", company_id=company.id, actor_user_id=actor_user_id,
        actor_kind="sales", subject_type="coupon", subject_id=coupon.id,
        detail={"code": coupon.code, "effect": effect, "days": days, **detail},
    )
    return redemption


def _temporary_access(company: Company, coupon: Coupon, specs, *, actor_user_id, now) -> Trial:
    """
    Tillfällig åtkomst: ett prov med kupongens dagar och billimit som startar
    NU. Pågår redan ett prov förlängs det i stället, och bilarna läggs till.
    Precis som ett prov debiteras det aldrig av sig självt.
    """
    trial = trials.active_trial(company.id)
    if trial is not None:
        if trial.status == Trial.Status.PENDING:
            trial = trials.start_trial(trial, now=now)
        new_limit = max(trial.vehicle_limit, coupon.vehicle_limit)
        Trial.objects.filter(id=trial.id).update(
            ends_at=(trial.ends_at or now) + timedelta(days=coupon.days), vehicle_limit=new_limit
        )
        trial.refresh_from_db()
        if specs:
            _add_trial_vehicles(trial, specs, actor_user_id=actor_user_id, now=now)
        return trial

    if not specs:
        raise SalesError("vehicles_required", "Lägg till minst en bil för den tillfälliga åtkomsten.")
    profile = _profile_or_error(company)
    # Ingen `eligibility`-kontroll: kupongen ÄR beslutet att ge gratisdagar.
    # Raden räknas ändå i provhistoriken, så ett senare självregistrerat prov
    # på samma organisationsnummer ger inte ytterligare gratisdagar.
    trial = Trial.objects.create(
        company_id=company.id, org_key=orgnr.org_key(profile.country, profile.org_number),
        source=Trial.Source.COUPON, requires_payment_method=False,
        vehicle_limit=coupon.vehicle_limit, status=Trial.Status.ACTIVE,
        started_at=now, ends_at=now + timedelta(days=coupon.days),
    )
    _add_trial_vehicles(trial, specs, actor_user_id=actor_user_id, now=now)
    audit.record(
        "trial_created", company_id=company.id, actor_user_id=actor_user_id,
        actor_kind="sales", subject_type="trial", subject_id=trial.id,
        detail={"source": "coupon", "coupon": coupon.code, "days": coupon.days},
    )
    return trial


# ---------------------------------------------------------------------------
# Kundens administratör
# ---------------------------------------------------------------------------


def invite_owner(company: Company, email: str, *, actor_user_id, now=None) -> OwnerInvite:
    from fleet import accounts

    now = now or timezone.now()
    email = _email(email, "e-postadressen", required=True)
    accounts.assert_email_allowed(email)
    OwnerInvite.objects.filter(
        company_id=company.id, email=email, status=OwnerInvite.Status.PENDING
    ).update(status=OwnerInvite.Status.REVOKED)
    invite = OwnerInvite.objects.create(
        company_id=company.id, email=email, created_by=actor_user_id,
        expires_at=now + timedelta(days=OWNER_INVITE_DAYS),
    )
    audit.record(
        "owner_invited", company_id=company.id, actor_user_id=actor_user_id,
        actor_kind="sales", subject_type="owner_invite", subject_id=invite.id,
        detail={"email": email},
    )
    return invite


@transaction.atomic
def claim_owner_invite(*, user_id: str, email: str, now=None) -> CompanyMember | None:
    """
    Knyter ett inloggat konto till företaget som bjöd in dess e-postadress.

    `email` ska komma ur en VERIFIERAD Supabase-JWT: Supabase Auth ger bara ut
    en sådan efter att personen öppnat länken i sin inkorg. Ett konto som
    redan tillhör ett företag får inte ett andra -- principal_for läser ett
    medlemskap, och två hade gjort det slumpmässigt vilket bolag som visas.
    """
    now = now or timezone.now()
    from fleet import accounts

    email = (email or "").strip().lower()
    if not user_id or not email:
        return None
    accounts.assert_email_allowed(email)
    if CompanyMember.objects.filter(user_id=user_id, status="active").exists():
        raise SalesError(
            "already_member", "Kontot hör redan till ett företag.", status=409
        )
    invite = (
        OwnerInvite.objects.select_for_update()
        .filter(email=email, status=OwnerInvite.Status.PENDING, expires_at__gt=now)
        .order_by("-created_at")
        .first()
    )
    if invite is None:
        return None
    member = CompanyMember.objects.create(
        id=uuid.uuid4(), company_id=invite.company_id, user_id=user_id,
        role=invite.role, status="active", created_at=now,
    )
    OwnerInvite.objects.filter(id=invite.id).update(
        status=OwnerInvite.Status.CONSUMED, consumed_at=now, consumed_by_user=user_id
    )
    audit.record(
        "owner_invite_claimed", company_id=invite.company_id, actor_user_id=user_id,
        actor_kind="customer", subject_type="owner_invite", subject_id=invite.id,
        detail={"email": email, "role": invite.role},
    )
    return member
