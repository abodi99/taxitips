"""
Förarens inloggning med bara e-post.

Chefen bjuder in förarens e-post till en bil (fleet/driver_invites.py) och
bestämmer därmed bil och län. Föraren skriver sin e-post i appen och får en
sexsiffrig kod i mejlet; koden kopplar telefonen till bilen. Ingen kod att
läsa upp, inget lösenord att välja.

**Koden finns för säkerhetens skull, inte för formens.** Utan den hade vem som
helst som känner till en förares e-post kunnat ta förarens bil och tips. Den
bevisar att personen kommer åt inkorgen -- samma bevis som länken i den
gamla inbjudan gav.

**Inget avslöjas om vem som är inbjuden.** `start` svarar likadant oavsett om
adressen har en inbjudan; bara mejlet skiljer.

Samma inlösen som förut (`driver_invites.claim_invite`): en väntande inbjudan
blir ett godkännande, och en förare som redan löst in sin inbjudan (ny
telefon, utloggad) får tillbaka bilen -- om chefen inte spärrat telefonen.
Kontot i Supabase Auth behövs fortfarande som förarens identitet (telefonbyten
räknas per konto), men föraren loggar aldrig in där själv.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from billing.models import Company
from fleet import accounts, auth_admin, driver_invites, notifications, pairing, ratelimit
from fleet.models import DriverInvite, DriverLoginCode

log = logging.getLogger(__name__)

CODE_TTL = timedelta(minutes=10)
MAX_ATTEMPTS = 5

START = ratelimit.Limit("driver_login_start", limit=5, window_seconds=900)
VERIFY = ratelimit.Limit("driver_login_verify", limit=15, window_seconds=900)


class DriverLoginError(driver_invites.DriverInviteError):
    pass


def _hash(email: str, code: str) -> str:
    key = (getattr(settings, "SECRET_KEY", "") or "taxitips").encode()
    return hmac.new(key, f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


def _invite_for(email: str, now) -> DriverInvite | None:
    """En väntande inbjudan, annars den förare senast löste in (logga in igen)."""
    pending = (
        DriverInvite.objects.filter(
            email=email, status=DriverInvite.Status.PENDING, expires_at__gt=now
        ).select_related("vehicle").order_by("-created_at").first()
    )
    if pending is not None:
        return pending
    return (
        DriverInvite.objects.filter(
            email=email, status=DriverInvite.Status.CONSUMED,
            consumed_by_user__isnull=False, consumed_by_device__isnull=False,
        ).select_related("vehicle").order_by("-consumed_at").first()
    )


def start(email: str, *, client_ip: str = "", now=None) -> None:
    """Mejlar en kod om adressen har en inbjudan. Svarar likadant oavsett."""
    now = now or timezone.now()
    email = driver_invites.normalize_email(email)
    ratelimit.enforce(START, email)
    if client_ip:
        ratelimit.enforce(START, f"ip:{client_ip}")
    if accounts.account_block(email=email) is not None:
        return
    invite = _invite_for(email, now)
    if invite is None:
        return
    code = f"{secrets.randbelow(1_000_000):06d}"
    with transaction.atomic():
        # En ny kod ersätter den förra: bara den senaste i mejlkorgen gäller.
        DriverLoginCode.objects.filter(email=email, used_at__isnull=True).update(used_at=now)
        row = DriverLoginCode.objects.create(
            email=email, code_hash=_hash(email, code), expires_at=now + CODE_TTL,
        )
    company = Company.objects.filter(id=invite.company_id).first()
    message = notifications.driver_login_code(
        email=email, code=code, row_id=row.id,
        company_name=company.name if company else "", plate=invite.vehicle.plate,
    )
    # Föraren står och väntar med appen öppen: skicka nu, inte vid nästa körning.
    notifications.send_now(message)


def _user_for(invite: DriverInvite, email: str) -> str:
    """Förarens konto. Skapas i Supabase Auth första gången (ingen länk skickas)."""
    if invite.status == DriverInvite.Status.CONSUMED and invite.consumed_by_user:
        return str(invite.consumed_by_user)
    if invite.auth_user_id:
        return str(invite.auth_user_id)
    user_id = None
    if auth_admin.configured():
        try:
            user_id = auth_admin.invite_link(email, notifications.portal_url()).user_id
        except auth_admin.AuthAdminError as exc:
            log.warning("driver_login: kunde inte skapa konto: %s", exc)
    # Utan Supabase Auth (lokalt): ett stabilt id per adress.
    user_id = user_id or str(uuid.uuid5(uuid.NAMESPACE_URL, f"taxitips-driver:{email}"))
    DriverInvite.objects.filter(id=invite.id).update(auth_user_id=user_id)
    return user_id


def verify(
    email: str, code: str, *, installation_id: str, label: str = "", platform: str = "",
    push_token: str | None = None, client_ip: str = "", now=None,
) -> pairing.PairedDevice:
    """Rätt kod: telefonen kopplas till bilen i förarens inbjudan."""
    now = now or timezone.now()
    email = driver_invites.normalize_email(email)
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    ratelimit.enforce(VERIFY, email)
    if client_ip:
        ratelimit.enforce(VERIFY, f"ip:{client_ip}")
    wrong = DriverLoginError("invalid_code", "Fel kod. Kontrollera mejlet eller be om en ny kod.", status=400)

    with transaction.atomic():
        row = (
            DriverLoginCode.objects.select_for_update()
            .filter(email=email, used_at__isnull=True).order_by("-created_at").first()
        )
        if row is None or row.expires_at <= now:
            raise DriverLoginError(
                "code_expired", "Koden har gått ut. Be om en ny kod.", status=410,
            )
        if row.attempts >= MAX_ATTEMPTS:
            raise DriverLoginError(
                "too_many_attempts", "För många försök. Be om en ny kod.", status=429,
            )
        if len(code) != 6 or not hmac.compare_digest(row.code_hash, _hash(email, code)):
            # Räknas innan felet kastas, utanför blocket: annars hade
            # tillbakarullningen raderat försöket.
            DriverLoginCode.objects.filter(id=row.id).update(attempts=row.attempts + 1)
            wrong_row = row.id
        else:
            wrong_row = None
            DriverLoginCode.objects.filter(id=row.id).update(used_at=now)
    if wrong_row is not None:
        raise wrong

    invite = _invite_for(email, now)
    if invite is None:
        raise driver_invites.DriverInviteError(
            "no_invite", "Vi hittar ingen inbjudan för den här e-posten. Be din chef bjuda in dig.",
            status=404,
        )
    return driver_invites.claim_invite(
        user_id=_user_for(invite, email), email=email, installation_id=installation_id,
        label=label, platform=platform, push_token=push_token, now=now,
    )
