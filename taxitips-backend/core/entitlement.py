"""
Vem som får se poängsatt data -- Python-porten av SQL-funktionen
`public.current_entitlement(text)`.

Två vägar in, precis som i SQL-versionen:

1. **Förartoken** (`X-Device-Token`): token -> device -> company, som måste
   ha status trial/active eller subscription_status active.
2. **Inloggad ägare/administratör** (`Authorization: Bearer <supabase-jwt>`):
   JWT:ns `sub` -> aktiv rad i company_members -> samma bolagskontroll.

Väg 2 finns för att den en gång saknades: en ägare som loggat in med
e-post hade ingen device-token, fick `p_device_token = null`, och nekades
all data -- vilket såg ut precis som "inga störningar just nu". Se
20260902000005_entitlement_for_authenticated_owners.sql. En port som bara
tog med väg 1 hade återinfört buggen.

JWT:n verifieras för hand mot Supabases HS256-hemlighet. Ett bibliotek
till hade betytt ett beroende för trettio rader, och de trettio raderna är
lättare att granska än biblioteksberoendets uppgraderingskedja. Bara HS256
accepteras -- `alg: none` och asymmetriska algoritmer avvisas innan
signaturen ens beräknas.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass

from django.conf import settings

from billing.models import Company, CompanyMember, Device

log = logging.getLogger(__name__)

ACTIVE_COMPANY_STATUSES = ("trial", "active")


@dataclass(frozen=True)
class Entitlement:
    """Svaret, med skälet kvar -- ett tyst False är omöjligt att felsöka."""

    ok: bool
    reason: str
    company_id: str | None = None
    device_id: str | None = None

    def __bool__(self) -> bool:
        return self.ok


def _company_is_active(company: Company) -> bool:
    return (
        company.status in ACTIVE_COMPANY_STATUSES
        or company.subscription_status == "active"
    )


def _b64url_decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def verify_supabase_jwt(token: str) -> dict | None:
    """Verifierad payload, eller None. Kastar aldrig."""
    secret = getattr(settings, "SUPABASE_JWT_SECRET", "")
    if not secret or not token:
        return None
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        header = json.loads(_b64url_decode(header_b64))
        if header.get("alg") != "HS256":
            return None
        expected = hmac.new(
            secret.encode(),
            f"{header_b64}.{payload_b64}".encode(),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(expected, _b64url_decode(signature_b64)):
            return None
        payload = json.loads(_b64url_decode(payload_b64))
    except Exception:
        return None

    exp = payload.get("exp")
    if not isinstance(exp, (int, float)) or exp <= time.time():
        return None
    return payload


def entitlement_for_device_token(token: str | None) -> Entitlement:
    if not token:
        return Entitlement(False, "no_device_token")
    device = Device.objects.filter(token=token).first()
    if device is None:
        return Entitlement(False, "unknown_device_token")
    company = Company.objects.filter(id=device.company_id).first()
    if company is None:
        return Entitlement(False, "device_without_company", device_id=str(device.id))
    if not _company_is_active(company):
        return Entitlement(
            False,
            f"company_{company.status}",
            company_id=str(company.id),
            device_id=str(device.id),
        )
    return Entitlement(True, "device", str(company.id), str(device.id))


def entitlement_for_user_id(user_id: str | None) -> Entitlement:
    if not user_id:
        return Entitlement(False, "no_user")
    member = CompanyMember.objects.filter(user_id=user_id, status="active").first()
    if member is None:
        return Entitlement(False, "no_active_membership")
    company = Company.objects.filter(id=member.company_id).first()
    if company is None or not _company_is_active(company):
        return Entitlement(False, "company_inactive", company_id=str(member.company_id))
    return Entitlement(True, "member", str(member.company_id))


def entitlement_for_request(request) -> Entitlement:
    """
    Läser förartoken och/eller Supabase-JWT ur requesten.

    Device-token först, samma ordning som SQL-funktionens coalesce: appens
    vanligaste anrop är förarens, och den vägen kostar en fråga.
    """
    token = request.headers.get("X-Device-Token") or request.GET.get("device_token")
    result = entitlement_for_device_token(token)
    if result.ok:
        return result

    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        payload = verify_supabase_jwt(auth[7:].strip())
        if payload:
            member = entitlement_for_user_id(payload.get("sub"))
            if member.ok:
                return member
            result = member
    return result
