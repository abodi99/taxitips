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

JWT:n verifieras för hand. Två signeringsformer stöds, för att Supabase
bytte under fötterna på oss:

* **ES256/RS256 via JWKS** -- moderna Supabase-projekt (och en lokal
  `supabase start` idag) signerar asymmetriskt med en roterande nyckel som
  publiceras på `/auth/v1/.well-known/jwks.json`. Det här är normalfallet.
* **HS256 mot den delade hemligheten** -- äldre projekt och den legacy-
  hemlighet `SUPABASE_JWT_SECRET` bär.

`alg: none` avvisas alltid, och algoritmen läses aldrig från token för att
välja *om* signaturen ska kontrolleras -- bara vilken kontroll som gäller.

Skälet att det står här och inte i ett bibliotek: koden är trettio rader
och lättare att granska än ett beroendes uppgraderingskedja. Skälet att
BÅDA formerna finns: en implementation som bara tog HS256 (den ursprungliga
här) släppte igenom exakt noll inloggade ägare mot ett modernt Supabase --
och felet syntes som "inga störningar just nu", precis som buggen
20260902000005 en gång rättade.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import threading
import time
from dataclasses import dataclass

import requests
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


def _b64url_int(segment: str) -> int:
    return int.from_bytes(_b64url_decode(segment), "big")


# JWKS hämtas en gång och cachas per kid. Nyckeln roterar, så en okänd kid
# tvingar en ny hämtning -- men bara en, och aldrig oftare än
# _JWKS_MIN_REFRESH, så en trasig token inte kan användas för att hamra
# Supabase.
_JWKS_MIN_REFRESH = 60
_jwks_cache: dict[str, dict] = {}
_jwks_fetched_at = 0.0
_jwks_lock = threading.Lock()


def _jwks_key(kid: str) -> dict | None:
    global _jwks_fetched_at
    key = _jwks_cache.get(kid)
    if key:
        return key
    with _jwks_lock:
        if kid in _jwks_cache:
            return _jwks_cache[kid]
        if time.monotonic() - _jwks_fetched_at < _JWKS_MIN_REFRESH:
            return None
        url = str(getattr(settings, "SUPABASE_URL", "")).rstrip("/")
        if not url:
            return None
        try:
            res = requests.get(f"{url}/auth/v1/.well-known/jwks.json", timeout=5)
            res.raise_for_status()
            for k in res.json().get("keys") or []:
                if k.get("kid"):
                    _jwks_cache[k["kid"]] = k
        except Exception as exc:
            log.warning("entitlement: kunde inte hämta JWKS: %s", exc)
        _jwks_fetched_at = time.monotonic()
    return _jwks_cache.get(kid)


def _verify_asymmetric(key: dict, alg: str, signing_input: bytes, signature: bytes) -> bool:
    """ES256 (EC P-256) och RS256, med `cryptography`. Kastar aldrig."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa, utils

    try:
        if alg == "ES256" and key.get("kty") == "EC":
            public = ec.EllipticCurvePublicNumbers(
                _b64url_int(key["x"]), _b64url_int(key["y"]), ec.SECP256R1()
            ).public_key()
            # JWS bär signaturen som råa r||s; cryptography vill ha DER.
            half = len(signature) // 2
            der = utils.encode_dss_signature(
                int.from_bytes(signature[:half], "big"),
                int.from_bytes(signature[half:], "big"),
            )
            public.verify(der, signing_input, ec.ECDSA(hashes.SHA256()))
            return True
        if alg == "RS256" and key.get("kty") == "RSA":
            public = rsa.RSAPublicNumbers(
                _b64url_int(key["e"]), _b64url_int(key["n"])
            ).public_key()
            public.verify(signature, signing_input, padding.PKCS1v15(), hashes.SHA256())
            return True
    except Exception:
        return False
    return False


def verify_supabase_jwt(token: str) -> dict | None:
    """Verifierad payload, eller None. Kastar aldrig."""
    if not token:
        return None
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
        header = json.loads(_b64url_decode(header_b64))
        alg = str(header.get("alg") or "")
        signing_input = f"{header_b64}.{payload_b64}".encode()
        signature = _b64url_decode(signature_b64)

        if alg == "HS256":
            secret = getattr(settings, "SUPABASE_JWT_SECRET", "")
            if not secret:
                return None
            expected = hmac.new(secret.encode(), signing_input, hashlib.sha256).digest()
            if not hmac.compare_digest(expected, signature):
                return None
        elif alg in ("ES256", "RS256"):
            key = _jwks_key(str(header.get("kid") or ""))
            if not key or not _verify_asymmetric(key, alg, signing_input, signature):
                return None
        else:
            # Inklusive "none". En okänd algoritm är inte ett skäl att
            # hoppa över kontrollen.
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
