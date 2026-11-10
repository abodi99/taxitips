"""
Kundens egna uppgifter i kundportalen: kontaktperson och fakturering.

Två områden med var sin behörighet, så att en ekonomiansvarig kan rätta
fakturaadressen utan att kunna byta företagets kontaktperson:

* Kontakt (namn, mobil) -- Perm.MANAGE_MEMBERS, i praktiken ägaren.
* Fakturering (e-post, referens, adress) -- Perm.PURCHASE.

Organisationsnummer och företagsnamn ändras INTE här: ett byte av
organisationsnummer är ett byte av avtalspart och går genom granskningen
(api.change_contracting_party), och namnet kommer från Bolagsverket.

Mobilnumret prövas med samma regler som vid registreringen
(signup_checks.check_phone), så att uppföljningen i adminwebben inte får ett
påhittat nummer i efterhand.
"""

from __future__ import annotations

import re

from fleet import audit, roles, signup_checks
from fleet.models import CompanyProfile
from fleet.roles import Perm
from fleet.sales import SalesError

CONTACT_FIELDS = ("contactName", "contactPhone")
BILLING_FIELDS = ("billingEmail", "billingReference", "billingAddress")
ADDRESS_KEYS = ("line1", "line2", "postal_code", "city")

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_POSTAL = re.compile(r"^\d{3}\s?\d{2}$")


def _error(field: str, reason: str, message: str) -> SalesError:
    """Fältet som är fel följer med i `detail`, så att portalen kan peka på det."""
    return SalesError(reason, message, status=400, detail={"field": field})


def view(profile: CompanyProfile | None) -> dict:
    """Det portalen visar och låter kunden ändra."""
    if profile is None:
        return {
            "contactName": "", "contactPhone": "", "contactEmail": "",
            "billingEmail": "", "billingReference": "", "billingAddress": {},
            "needsOrgNumber": True,
        }
    address = profile.billing_address or {}
    return {
        "contactName": profile.contact_name,
        "contactPhone": profile.contact_phone,
        "contactEmail": profile.contact_email,
        "billingEmail": profile.billing_email,
        "billingReference": profile.billing_reference,
        "billingAddress": {
            "line1": address.get("line1", ""),
            "line2": address.get("line2", ""),
            "postalCode": address.get("postal_code", ""),
            "city": address.get("city", ""),
        },
        # BankID-registreringen: numret anges före första beställningen.
        "needsOrgNumber": not profile.org_number,
    }


def update(principal: roles.Principal, body: dict) -> dict:
    """Sparar de fält som skickats med. Fält som saknas lämnas orörda."""
    touches_contact = any(k in body for k in CONTACT_FIELDS)
    touches_billing = any(k in body for k in BILLING_FIELDS)
    if not (touches_contact or touches_billing):
        raise SalesError("nothing_to_update", "Inget att spara.", status=400)
    if touches_contact:
        roles.require(principal, Perm.MANAGE_MEMBERS)
    if touches_billing:
        roles.require(principal, Perm.PURCHASE)

    profile = CompanyProfile.objects.filter(company_id=principal.company_id).first()
    if profile is None:
        raise SalesError("no_company", "Företaget saknar uppgifter. Kontakta oss.", status=404)

    changed: dict[str, str] = {}

    if "contactName" in body:
        name = str(body.get("contactName") or "").strip()[:120]
        if not name:
            raise _error("contactName", "contact_name_required", "Skriv namnet på kontaktpersonen.")
        if name != profile.contact_name:
            profile.contact_name = name
            changed["contact_name"] = name

    if "contactPhone" in body:
        try:
            phone = signup_checks.check_phone(body.get("contactPhone"))
        except signup_checks.CheckError as exc:
            raise _error("contactPhone", exc.reason, exc.message) from exc
        if phone != profile.contact_phone:
            profile.contact_phone = phone
            # Ett nytt nummer är inte verifierat bara för att det gamla var det.
            profile.phone_verified_at = None
            changed["contact_phone"] = phone

    if "billingEmail" in body:
        email = str(body.get("billingEmail") or "").strip()[:254]
        if not _EMAIL.match(email):
            raise _error("billingEmail", "invalid_email", "Skriv en riktig e-postadress för fakturor.")
        try:
            signup_checks.check_email(email)
        except signup_checks.CheckError as exc:
            raise _error("billingEmail", exc.reason, exc.message) from exc
        if email != profile.billing_email:
            profile.billing_email = email
            changed["billing_email"] = email

    if "billingReference" in body:
        ref = str(body.get("billingReference") or "").strip()[:80]
        if ref != profile.billing_reference:
            profile.billing_reference = ref
            changed["billing_reference"] = ref

    if "billingAddress" in body:
        raw = body.get("billingAddress") or {}
        if not isinstance(raw, dict):
            raise _error("billingAddress", "invalid_address", "Adressen kunde inte läsas.")
        address = {
            "line1": str(raw.get("line1") or "").strip()[:120],
            "line2": str(raw.get("line2") or "").strip()[:120],
            "postal_code": str(raw.get("postalCode") or "").strip()[:12],
            "city": str(raw.get("city") or "").strip()[:80],
        }
        if not address["line1"] or not address["city"]:
            raise _error("billingAddress", "address_incomplete", "Skriv gatuadress och ort.")
        if address["postal_code"] and not _POSTAL.match(address["postal_code"]):
            raise _error("billingAddress", "invalid_postal_code", "Postnumret ska vara fem siffror, till exempel 252 75.")
        merged = {"country": "SE", **(profile.billing_address or {}), **address}
        if merged != (profile.billing_address or {}):
            profile.billing_address = merged
            changed["billing_address"] = ", ".join(
                v for v in (address["line1"], address["postal_code"], address["city"]) if v
            )

    if changed:
        profile.save()
        audit.record(
            "company_details_updated", company_id=principal.company_id,
            actor_user_id=principal.user_id, actor_kind="customer",
            subject_type="company", subject_id=principal.company_id,
            detail={"fields": sorted(changed)},
        )
    return {"changed": sorted(changed), "details": view(profile)}


# ---------------------------------------------------------------------------
# Organisationsnumret, första gången (BankID-registreringen)
# ---------------------------------------------------------------------------
#
# En kund som registrerat sig med BankID har inget organisationsnummer. Det
# anges här, i portalen, innan första beställningen -- en gång. Ett byte av
# ett nummer som redan finns är fortfarande ett byte av avtalspart och går
# genom granskningen (api.change_contracting_party).

COMPANY_DETAILS_REQUIRED = (
    "Fyll i organisationsnummer och fakturauppgifter innan du beställer. "
    "Det tar en minut, och inget kostar förrän du godkänner beställningen."
)


def needs_org_number(company_id) -> bool:
    """Varken profilen eller företagsraden har ett organisationsnummer."""
    from billing.models import Company

    profile = CompanyProfile.objects.filter(company_id=company_id).first()
    if profile is not None and profile.org_number:
        return False
    return not Company.objects.filter(id=company_id).exclude(org_number__isnull=True).exclude(
        org_number=""
    ).exists()


def require_company_details(company_id) -> None:
    """Spärren före beställning: servern, inte bara portalen."""
    if needs_org_number(company_id):
        raise SalesError(
            "company_details_required", COMPANY_DETAILS_REQUIRED, status=409,
            detail={"field": "orgNumber"},
        )


def set_org_number(principal: roles.Principal, body: dict) -> dict:
    roles.require(principal, Perm.PURCHASE)
    return add_org_number(
        principal.company_id, body, actor_user_id=principal.user_id, actor_kind="customer",
    )


def add_org_number(company_id, body: dict, *, actor_user_id, actor_kind: str = "customer") -> dict:
    """
    Sätter organisationsnumret första gången, med alla kontroller (Bolagsverket,
    dubblett). Delas av kunden i portalen och av säljaren i admin: en kund som
    lagts upp utan nummer måste kunna få det på plats innan första beställningen.
    """
    from django.db import transaction
    from django.utils import timezone

    from billing.models import Company
    from fleet import orgnr, registration, sales

    country = "SE"
    raw = str(body.get("orgNumber") or "")
    with transaction.atomic():
        profile = CompanyProfile.objects.select_for_update().filter(company_id=company_id).first()
        if profile is None:
            raise _error("orgNumber", "no_profile", "Företaget saknar uppgifter. Kontakta TaxiTips.")
        if profile.org_number:
            raise _error(
                "orgNumber", "org_number_set",
                "Organisationsnumret är redan angivet. Kontakta TaxiTips för att byta.",
            )
        if not orgnr.is_valid(raw, country):
            raise _error("orgNumber", "invalid_org_number", "Organisationsnumret går inte att tolka.")
        normalized = orgnr.normalize(raw, country)
        other = sales.existing_company_for(normalized, country)
        if other is not None and str(other.id) != str(company_id):
            raise SalesError(
                "company_exists", registration.COMPANY_EXISTS_MESSAGE, status=409,
                detail={"field": "orgNumber"},
            )
        from fleet import bolagsverket

        try:
            kind = signup_checks.check_identity(normalized, today=timezone.localdate())
            registry = bolagsverket.try_lookup(normalized)
            signup_checks.check_registry(normalized, kind, registry)
        except signup_checks.CheckError as exc:
            raise _error("orgNumber", exc.reason, exc.message) from exc
        if registry is not None and registry.blocks_signup:
            raise _error(
                "orgNumber", "company_deregistered",
                f"{registry.name} är avregistrerat hos Bolagsverket ({registry.status_text}).",
            )
        found = registry is not None and registry.found
        legal_name = sales._clean(body.get("legalName"), 200) or (registry.name if found else "")
        if not legal_name:
            raise _error(
                "legalName", "name_required",
                "Vi hittade inte bolaget hos Bolagsverket. Skriv företagets juridiska namn.",
            )
        profile.org_number = normalized
        profile.legal_name = legal_name
        profile.save(update_fields=["org_number", "legal_name"])
        if registry is not None:
            bolagsverket.apply_to_profile(profile, registry)
        Company.objects.filter(id=company_id).update(org_number=normalized)
        audit.record(
            "org_number_added", company_id=company_id, actor_user_id=actor_user_id,
            actor_kind=actor_kind, subject_type="company", subject_id=company_id,
            detail={"org_number": normalized, "kind": kind,
                    "registry": (registry.status if registry else "unavailable")},
        )
    return {"orgNumber": normalized, "legalName": legal_name, "kind": kind}
