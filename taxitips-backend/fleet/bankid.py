"""
BankID: legitimering vid registrering och när ägaren glömt lösenord eller
bytt e-post.

**Samma väg som Volontera.** Certifikatet ligger hos BankID-proxyn på vår egen
server; Volontera når den från Supabase edge-funktioner
(`volunteerhelp_client/supabase/functions/_shared/proxy.ts`). Här sker samma
anrop från Django, eftersom registreringen och provet bor här. Proxyn tar
`/auth`, `/collect` och `/cancel` med samma kropp som BankID RP v6 plus
`useProduction`, och kräver `Authorization: Bearer <BANKID_PROXY_SECRET>`.

**Klienten bestämmer aldrig vem den är.** När BankID svarar `complete`
utfärdar vi en kort biljett (signerad med Djangos SECRET_KEY, 15 minuter) som
bär personnumrets nyckel och namnet. Registreringen och återställningen tar
bara biljetten -- inte ett personnummer från appen.

**Personnumret sparas inte.** Biljetten och databasen bär `pnr_key`, en HMAC
av personnumret med `BANKID_PNR_PEPPER`. Den räcker för "en person, ett konto
och ett prov" och går inte att vända tillbaka till ett personnummer utan
pepparn.

**En order är vår.** Proxyn delas med Volontera. En orderRef som inte
startades här (`fleet_bankid_order`, 10 min) ger ingen biljett, och samma order
ger bara en biljett. Raden ligger i databasen och inte i cachen, eftersom
start och collect kan hamna i olika serverprocesser.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
from dataclasses import dataclass

import requests
from django.conf import settings
from datetime import timedelta

from django.core import signing
from django.utils import timezone

log = logging.getLogger(__name__)

TICKET_SALT = "fleet.bankid.ticket.v1"
TICKET_MAX_AGE = 15 * 60
ORDER_TTL = 10 * 60
HTTP_TIMEOUT = 12

# Det här ser användaren i BankID-appen innan hen godkänner.
USER_VISIBLE_TEXT = {
    "register": (
        "Du legitimerar dig för att starta ett gratis prov hos TaxiTips. "
        "Det binder dig inte till något och kostar inget."
    ),
    "recover": "Du legitimerar dig för att komma åt ditt TaxiTips-konto.",
    "login": "Du loggar in i TaxiTips.",
}
PURPOSES = tuple(USER_VISIBLE_TEXT)

# BankID:s hintCode -> det appen visar. Okända koder får den allmänna texten.
HINT_TEXT = {
    "outstandingTransaction": "Öppna BankID-appen.",
    "noClient": "Öppna BankID-appen.",
    "started": "Söker efter BankID …",
    "userMrtd": "Fortsätt i BankID-appen.",
    "userSign": "Skriv din säkerhetskod i BankID-appen.",
    "userCallConfirm": "Bekräfta i BankID-appen.",
    "expiredTransaction": "Det tog för lång tid. Försök igen.",
    "certificateErr": "Ditt BankID går inte att använda. Kontakta din bank.",
    "userCancel": "Du avbröt i BankID-appen.",
    "cancelled": "Legitimeringen avbröts.",
    "startFailed": "BankID-appen startade inte. Försök igen.",
    "notSupportedByUserApp": "Uppdatera BankID-appen och försök igen.",
}


class BankIdError(Exception):
    def __init__(self, reason: str, message: str, status: int = 400):
        super().__init__(reason)
        self.reason = reason
        self.message = message
        self.status = status


@dataclass(frozen=True)
class Identity:
    pnr_key: str
    full_name: str
    given_name: str
    order_ref: str
    purpose: str


# ---------------------------------------------------------------------------
# Proxyn
# ---------------------------------------------------------------------------


def configured() -> bool:
    return bool((getattr(settings, "BANKID_PROXY_URL", "") or "").strip())


def _use_production() -> bool:
    return bool(getattr(settings, "BANKID_USE_PRODUCTION", False))


def _proxy(path: str, payload: dict) -> dict:
    base = (getattr(settings, "BANKID_PROXY_URL", "") or "").strip().rstrip("/")
    if not base:
        raise BankIdError("bankid_unavailable", "BankID är inte tillgängligt just nu.", status=503)
    current = (getattr(settings, "BANKID_PROXY_SECRET", "") or "").strip()
    previous = (getattr(settings, "BANKID_PROXY_SECRET_PREVIOUS", "") or "").strip()
    body = {"useProduction": _use_production(), **payload}

    def send(secret: str) -> requests.Response:
        headers = {"Content-Type": "application/json"}
        if secret:
            headers["Authorization"] = f"Bearer {secret}"
        return requests.post(f"{base}{path}", json=body, headers=headers, timeout=HTTP_TIMEOUT)

    try:
        res = send(current)
        # Byte av hemlighet utan avbrott, som i Volonteras proxy.ts.
        if res.status_code in (401, 403) and previous and previous != current:
            log.warning("bankid: %s nekad med ny hemlighet, provar föregående", path)
            res = send(previous)
    except requests.RequestException as exc:
        log.warning("bankid: %s %s", path, exc.__class__.__name__)
        raise BankIdError("bankid_unavailable", "BankID svarar inte just nu. Försök igen om en stund.", status=503) from exc
    try:
        data = res.json()
    except ValueError:
        data = {}
    if res.status_code >= 300:
        log.warning("bankid: %s status=%s body=%s", path, res.status_code, (res.text or "")[:300])
        code = str(data.get("errorCode") or data.get("error") or "")
        if code == "alreadyInProgress":
            raise BankIdError(
                "bankid_in_progress",
                "En legitimering pågår redan för det här BankID:t. Avbryt den i BankID-appen och försök igen.",
                status=409,
            )
        raise BankIdError("bankid_unavailable", "BankID svarar inte just nu. Försök igen om en stund.", status=503)
    return data if isinstance(data, dict) else {}


def start(*, purpose: str, end_user_ip: str) -> dict:
    """Startar en legitimering. Svaret har det appen behöver för autostart och QR."""
    if purpose not in PURPOSES:
        raise BankIdError("invalid_purpose", "Okänt syfte.")
    text = USER_VISIBLE_TEXT[purpose]
    payload = {
        "endUserIp": end_user_ip or "127.0.0.1",
        "userVisibleData": base64.b64encode(text.encode("utf-8")).decode("ascii"),
    }
    data = _proxy("/auth", payload)
    order_ref = str(data.get("orderRef") or data.get("sessionId") or "")
    auto_start = str(data.get("autoStartToken") or "")
    if not order_ref or not auto_start:
        log.warning("bankid: /auth utan orderRef/autoStartToken")
        raise BankIdError("bankid_unavailable", "BankID svarar inte just nu. Försök igen om en stund.", status=503)
    from fleet.models import BankIdOrder

    # BankID ger en ny orderRef varje gång; en gammal rad med samma ref ska inte ärvas.
    BankIdOrder.objects.filter(order_ref=order_ref[:64]).delete()
    BankIdOrder.objects.create(order_ref=order_ref[:64], purpose=purpose)
    return {
        "orderRef": order_ref,
        "autoStartToken": auto_start,
        "qrStartToken": data.get("qrStartToken") or None,
        "qrStartSecret": data.get("qrStartSecret") or None,
    }


def _known_order(order_ref: str):
    from fleet.models import BankIdOrder

    cutoff = timezone.now() - timedelta(seconds=ORDER_TTL)
    order = BankIdOrder.objects.filter(order_ref=(order_ref or "")[:64], created_at__gte=cutoff).first()
    if order is None or not order_ref:
        raise BankIdError("unknown_order", "Legitimeringen har gått ut. Börja om.", status=404)
    return order


def collect(order_ref: str) -> dict:
    """
    Frågar BankID hur det går. Så länge ordern pågår returneras status och en
    text att visa. När den är klar returneras namnet och biljetten.
    """
    order = _known_order(order_ref)
    if order.collected_at is not None:
        raise BankIdError("order_used", "Legitimeringen är redan använd. Börja om.", status=409)
    data = _proxy("/collect", {"orderRef": order_ref})
    status = str(data.get("status") or "")
    hint = str(data.get("hintCode") or "")
    if status == "pending":
        return {
            "status": "pending", "hintCode": hint,
            "message": HINT_TEXT.get(hint, "Fortsätt i BankID-appen."),
            "qrData": data.get("qrData") or None,
        }
    if status == "failed":
        order.delete()
        return {
            "status": "failed", "hintCode": hint,
            "message": HINT_TEXT.get(hint, "Legitimeringen misslyckades. Försök igen."),
        }
    if status != "complete":
        raise BankIdError("bankid_unavailable", "BankID svarar inte just nu. Försök igen om en stund.", status=503)

    attrs = (data.get("completionData") or {}).get("user") or data.get("userAttributes") or {}
    personal_number = re.sub(r"\D", "", str(attrs.get("personalNumber") or ""))
    full_name = str(attrs.get("name") or "").strip()
    given_name = str(attrs.get("givenName") or "").strip() or (full_name.split(" ")[0] if full_name else "")
    if len(personal_number) != 12 or not full_name:
        log.warning("bankid: complete utan giltigt personnummer eller namn")
        raise BankIdError("bankid_unavailable", "BankID gav inget fullständigt svar. Försök igen.", status=503)

    # Samma order ger bara en biljett, även om två collect körs samtidigt.
    claimed = type(order).objects.filter(pk=order.pk, collected_at__isnull=True).update(
        collected_at=timezone.now()
    )
    if not claimed:
        raise BankIdError("order_used", "Legitimeringen är redan använd. Börja om.", status=409)
    ticket = issue_ticket(
        pnr_key=pnr_key(personal_number), full_name=full_name, given_name=given_name,
        order_ref=order.order_ref, purpose=order.purpose,
    )
    result = {"status": "complete", "name": full_name, "givenName": given_name, "ticket": ticket}
    if order.purpose == "recover":
        # Den legitimerade personen får se sin egen inloggning, så att hen vet
        # vilken adress lösenordet gäller. None = inget BankID-konto.
        from fleet import registration

        result["accountEmail"] = registration.bankid_account_email(pnr_key(personal_number))
    return result


def cancel(order_ref: str) -> None:
    from fleet.models import BankIdOrder

    deleted, _ = BankIdOrder.objects.filter(
        order_ref=(order_ref or "")[:64], collected_at__isnull=True
    ).delete()
    if not deleted:
        return
    try:
        _proxy("/cancel", {"orderRef": order_ref})
    except BankIdError:
        # En order som inte avbryts går ut av sig själv efter 30 sekunder.
        pass


# ---------------------------------------------------------------------------
# Personnummer och biljett
# ---------------------------------------------------------------------------


def pnr_key(personal_number: str) -> str:
    """HMAC av personnumret (12 siffror). 32 hex-tecken räcker och passar Trial.org_key."""
    pepper = (getattr(settings, "BANKID_PNR_PEPPER", "") or "").strip()
    if not pepper:
        raise BankIdError("bankid_unavailable", "BankID är inte tillgängligt just nu.", status=503)
    digits = re.sub(r"\D", "", personal_number or "")
    return hmac.new(pepper.encode(), digits.encode(), hashlib.sha256).hexdigest()[:32]


def trial_key(pnr: str) -> str:
    """Provspärrens nyckel för en BankID-registrering: en person, ett prov."""
    return f"PNR:{pnr}"


def issue_ticket(*, pnr_key: str, full_name: str, given_name: str, order_ref: str, purpose: str) -> str:
    return signing.dumps(
        {"k": pnr_key, "n": full_name, "g": given_name, "o": order_ref, "p": purpose},
        salt=TICKET_SALT, compress=True,
    )


def read_ticket(ticket: str, *, purpose: str, consume: bool = False) -> Identity:
    """
    Läser biljetten. `consume=True` gör att den inte kan användas igen
    (återställningen); registreringen behöver inte det, eftersom en person
    bara kan ha ett konto.
    """
    try:
        data = signing.loads(ticket or "", salt=TICKET_SALT, max_age=TICKET_MAX_AGE)
    except signing.SignatureExpired as exc:
        raise BankIdError("ticket_expired", "Legitimeringen har gått ut. Legitimera dig igen.", status=401) from exc
    except signing.BadSignature as exc:
        raise BankIdError("invalid_ticket", "Legitimera dig med BankID först.", status=401) from exc
    if data.get("p") != purpose or not data.get("k"):
        raise BankIdError("invalid_ticket", "Legitimera dig med BankID först.", status=401)
    if consume:
        # Anroparen kör i en transaktion; rullas den tillbaka kan biljetten tas igen.
        from fleet.models import BankIdOrder

        used = BankIdOrder.objects.filter(order_ref=data.get("o", ""), consumed_at__isnull=True).update(
            consumed_at=timezone.now()
        )
        if not used:
            raise BankIdError("ticket_used", "Legitimeringen är redan använd. Legitimera dig igen.", status=409)
    return Identity(
        pnr_key=data["k"], full_name=data.get("n", ""), given_name=data.get("g", ""),
        order_ref=data.get("o", ""), purpose=data["p"],
    )
