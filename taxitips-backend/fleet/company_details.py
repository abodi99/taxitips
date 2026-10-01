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
