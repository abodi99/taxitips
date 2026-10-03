"""
Förarinbjudan med e-post: chefen bjuder in förarens e-post till en bil, och
föraren loggar in med bara sin e-post. Ingen kod att läsa upp, inget lösenord.

Flödet (sedan 2026-10-03):

1. **Chefen** (MANAGE_DEVICES, eller personal i admin) bjuder in en adress
   för en bestämd bil. Bilen och dess län bestäms här, inte av föraren.
   Mejlet säger: hämta appen, tryck "Jag är förare", skriv din e-post.
2. **Föraren** skriver sin e-post i appen och får en sexsiffrig kod i ett
   eget mejl (fleet/driver_login.py). Koden bevisar att personen kommer åt
   inkorgen; utan den kunde vem som helst ta förarens bil.
3. **Servern** löser in inbjudan med `claim_invite` -- samma väg som förut:
   en telefon per företag, ominstallation ersätter, licensens län, risksignal,
   revision och provets start (`pairing.approve_device`).

Förarens konto i Supabase Auth skapas av servern vid första inloggningen och
är förarens identitet (telefonbyten räknas per konto). Föraren loggar aldrig
in där själv.

**Äldre klienter.** `POST /api/fleet/driver-invites/claim` med en
Supabase-inloggning (lösenordsvägen) finns kvar tills de gamla apparna är
borta; det är samma `claim_invite`.
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from billing.models import Company
from fleet import accounts, audit, notifications, pairing, ratelimit
from fleet.models import DriverInvite, License, Vehicle

log = logging.getLogger(__name__)

INVITE_DAYS = 7
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class DriverInviteError(Exception):
    def __init__(self, reason: str, message: str, status: int = 400):
        super().__init__(reason)
        self.reason = reason
        self.message = message
        self.status = status


def normalize_email(value) -> str:
    email = accounts.normalize_email(value)
    if not email:
        raise DriverInviteError("email_required", "Skriv förarens e-post.")
    if len(email) > 254 or not _EMAIL.match(email):
        raise DriverInviteError("invalid_email", "E-postadressen ser inte rätt ut.")
    return email


def enabled() -> bool:
    """
    Inbjudan med e-post fungerar alltid: mejlet har ingen länk, och föraren
    loggar in med en kod i mejlet (fleet/driver_login.py). Finns kvar för
    klienterna som frågar.
    """
    return True


def _redirect_url() -> str:
    return getattr(settings, "FLEET_DRIVER_INVITE_REDIRECT", "") or "https://taxitips.se/forare"


def _send(invite: DriverInvite, now) -> DriverInvite:
    """Nytt mejl till föraren: hämta appen och skriv din e-post. Ingen länk."""
    send_count = invite.send_count + 1
    DriverInvite.objects.filter(id=invite.id).update(send_count=send_count, last_sent_at=now)
    invite.refresh_from_db()
    company = Company.objects.filter(id=invite.company_id).first()
    notifications.driver_invite(
        invite, company_name=company.name if company else "", plate=invite.vehicle.plate,
    )
    return invite


@transaction.atomic
def create_invite(
    *,
    license: License,
    vehicle: Vehicle,
    email: str,
    label: str = "",
    created_by=None,
    now=None,
    send_limit: ratelimit.Limit = ratelimit.DRIVER_INVITE_SEND,
) -> DriverInvite:
    """
    `send_limit` är bromsen för utskicket. Massinbjudan räknar mot sin egen
    dygnsgräns (ratelimit.DRIVER_INVITE_BULK) i stället för timgränsen, men
    reglerna i övrigt är desamma -- samma prövning, samma mejl.
    """
    now = now or timezone.now()
    email = normalize_email(email)
    pairing.check_pairable(license, vehicle)
    accounts.assert_email_allowed(email)
    ratelimit.enforce(send_limit, str(license.company_id))

    # En väntande inbjudan per adress och företag: den nya ersätter den gamla
    # (samma princip som en ny engångskod för samma bil).
    replaced = DriverInvite.objects.filter(
        company_id=license.company_id, email=email, status=DriverInvite.Status.PENDING
    ).update(status=DriverInvite.Status.REVOKED, revoked_at=now, revoked_by=created_by)

    invite = DriverInvite.objects.create(
        company_id=license.company_id, license=license, vehicle=vehicle,
        email=email, label=" ".join(str(label or "").split())[:80],
        created_by=created_by, expires_at=now + timedelta(days=INVITE_DAYS),
    )
    invite = _send(invite, now)
    audit.record(
        "driver_invited", company_id=license.company_id, actor_user_id=created_by,
        actor_kind="admin", subject_type="driver_invite", subject_id=invite.id,
        detail={
            "email": email, "license_id": str(license.id), "vehicle_id": str(vehicle.id),
            "replaced": replaced,
        },
    )
    return invite


@transaction.atomic
def resend_invite(invite: DriverInvite, *, actor_user_id=None, now=None) -> DriverInvite:
    """Ny länk, nytt mejl och sju nya dagar. En använd eller borttagen inbjudan skickas inte."""
    now = now or timezone.now()
    invite = DriverInvite.objects.select_for_update().get(id=invite.id)
    if invite.status != DriverInvite.Status.PENDING:
        raise DriverInviteError("invite_closed", "Inbjudan är redan använd eller borttagen.", status=409)
    pairing.check_pairable(invite.license, invite.vehicle)
    accounts.assert_email_allowed(invite.email)
    ratelimit.enforce(ratelimit.DRIVER_INVITE_RESEND, str(invite.id))
    ratelimit.enforce(ratelimit.DRIVER_INVITE_SEND, str(invite.company_id))
    DriverInvite.objects.filter(id=invite.id).update(expires_at=now + timedelta(days=INVITE_DAYS))
    invite.refresh_from_db()
    invite = _send(invite, now)
    audit.record(
        "driver_invite_resent", company_id=invite.company_id, actor_user_id=actor_user_id,
        actor_kind="admin", subject_type="driver_invite", subject_id=invite.id,
        detail={"email": invite.email, "send_count": invite.send_count},
    )
    return invite


def revoke_invite(invite: DriverInvite, *, actor_user_id=None, now=None) -> None:
    """Länken kan fortfarande ge ett lösenord, men inlösen i appen nekas."""
    now = now or timezone.now()
    changed = DriverInvite.objects.filter(
        id=invite.id, status=DriverInvite.Status.PENDING
    ).update(status=DriverInvite.Status.REVOKED, revoked_at=now, revoked_by=actor_user_id)
    if changed:
        audit.record(
            "driver_invite_revoked", company_id=invite.company_id, actor_user_id=actor_user_id,
            actor_kind="admin", subject_type="driver_invite", subject_id=invite.id,
            detail={"email": invite.email},
        )


@transaction.atomic
def claim_invite(
    *,
    user_id: str,
    email: str,
    installation_id: str,
    label: str = "",
    platform: str = "",
    push_token: str | None = None,
    now=None,
) -> pairing.PairedDevice:
    """
    Telefonens sida: den inloggade förarens inbjudan blir ett godkännande.

    `user_id` och `email` ska komma ur en VERIFIERAD Supabase-JWT.
    """
    now = now or timezone.now()
    email = accounts.normalize_email(email)
    if not user_id or not email:
        raise DriverInviteError("login_required", "Logga in för att fortsätta.", status=401)
    if not installation_id or len(installation_id) < 8:
        raise pairing.PairingError("installation_id_required", "Appen kunde inte identifiera telefonen.")

    ratelimit.enforce(ratelimit.DRIVER_INVITE_CLAIM, str(user_id))
    ratelimit.enforce(ratelimit.DRIVER_INVITE_CLAIM, pairing.hash_installation(installation_id)[:32])
    accounts.assert_email_allowed(email)

    invite = (
        DriverInvite.objects.select_for_update()
        .filter(email=email, status=DriverInvite.Status.PENDING)
        .order_by("-created_at")
        .first()
    )
    if invite is None:
        # Föraren som loggar in igen (utloggad, ny telefon): samma konto som
        # löste in inbjudan får tillbaka bilen -- så länge chefen inte spärrat.
        again = _relogin(
            user_id=user_id, email=email, installation_id=installation_id,
            label=label, platform=platform, push_token=push_token, now=now,
        )
        if again is not None:
            return again
        # Den inloggade äger adressen; att säga att inbjudan redan är använd
        # avslöjar inget för någon annan och sparar ett supportärende.
        if DriverInvite.objects.filter(email=email, status=DriverInvite.Status.CONSUMED).exists():
            raise DriverInviteError(
                "invite_used",
                "Inbjudan är redan använd. Be din chef skicka en ny.",
                status=404,
            )
        raise DriverInviteError(
            "no_invite",
            "Vi hittar ingen inbjudan för den här e-posten. Be din chef bjuda in dig.",
            status=404,
        )
    if invite.auth_user_id and str(invite.auth_user_id) != str(user_id):
        # Loggen, inte revisionen: felet rullar tillbaka transaktionen, och en
        # revisionsrad här hade försvunnit med den.
        log.warning("driver_invites: inbjudan %s löstes in av ett annat konto", invite.id)
        raise DriverInviteError(
            "no_invite",
            "Vi hittar ingen inbjudan för det här kontot. Be din chef skicka inbjudan igen.",
            status=404,
        )
    if invite.expires_at <= now:
        raise DriverInviteError(
            "invite_expired",
            "Inbjudan har gått ut. Be din chef skicka den igen.",
            status=410,
        )

    license = License.objects.get(id=invite.license_id)
    vehicle = Vehicle.objects.get(id=invite.vehicle_id)
    pairing.check_pairable(license, vehicle)

    # Atomisk förbrukning: villkoret ligger i WHERE, inte i Python.
    consumed = DriverInvite.objects.filter(
        id=invite.id, status=DriverInvite.Status.PENDING, consumed_at__isnull=True
    ).update(status=DriverInvite.Status.CONSUMED, consumed_at=now, consumed_by_user=user_id)
    if consumed != 1:
        raise DriverInviteError("no_invite", "Inbjudan är redan använd.", status=404)

    name = invite.label or label or "Förare"
    from billing.models import Device
    from fleet import device_swaps

    prev = Device.objects.filter(user_id=user_id).order_by("-last_seen_at").first()
    existing = Device.objects.filter(token=installation_id).first()
    if prev is not None and (existing is None or str(existing.id) != str(prev.id)):
        device_swaps.assert_can_swap(user_id, now=now)

    paired = pairing.approve_device(
        company_id=invite.company_id,
        license=license,
        vehicle=vehicle,
        approved_by=invite.created_by,
        installation_id=installation_id,
        device_label=name,
        approval_label=name,
        platform=platform,
        push_token=push_token,
        via="email_invite",
        now=now,
    )
    device = Device.objects.filter(id=paired.device_id).first()
    if device is not None:
        device_swaps.link_account_device(
            user_id=user_id, device=device, via="email_invite",
            previous_device_id=prev.id if prev else None, now=now,
        )
    DriverInvite.objects.filter(id=invite.id).update(consumed_by_device=paired.device_id)
    audit.record(
        "driver_invite_claimed", company_id=invite.company_id, actor_user_id=user_id,
        actor_kind="driver", subject_type="driver_invite", subject_id=invite.id,
        detail={"email": email, "device_id": paired.device_id, "approval_id": paired.approval_id},
    )
    return paired


def _relogin(
    *, user_id: str, email: str, installation_id: str, label: str,
    platform: str, push_token: str | None, now,
) -> pairing.PairedDevice | None:
    """
    E-post och lösenord ska gå att använda igen, inte bara första gången.

    Bara samma konto som löste in inbjudan (`consumed_by_user`), och bara om
    förarens senaste godkännande inte är spärrat av chefen. En ny telefon
    ersätter den förra: ett förarkonto kör aldrig på två telefoner samtidigt,
    annars hade en inbjudan kunnat delas mellan flera förare.

    Returnerar None när det inte finns något att logga in igen till -- då
    gäller de vanliga felen (`invite_used`, `no_invite`).
    """
    from fleet import sessions
    from fleet.models import DeviceApproval, DeviceCredential, VehicleSession

    invite = (
        DriverInvite.objects.select_for_update()
        .filter(email=email, status=DriverInvite.Status.CONSUMED, consumed_by_user=user_id)
        .order_by("-consumed_at")
        .first()
    )
    if invite is None or invite.consumed_by_device is None:
        return None
    previous = (
        DeviceApproval.objects.filter(device_id=invite.consumed_by_device, license_id=invite.license_id)
        .order_by("-approved_at")
        .first()
    )
    if previous is not None and previous.status == DeviceApproval.Status.BLOCKED:
        raise DriverInviteError(
            "driver_blocked",
            "Din chef har tagit bort telefonen från bilen. Be om en ny inbjudan.",
            status=403,
        )
    if previous is not None and (previous.revoke_reason or "").startswith("vehicle_"):
        raise DriverInviteError(
            "vehicle_changed",
            "Bilen har bytts ut. Be din chef bjuda in dig till den nya bilen.",
            status=409,
        )

    license = License.objects.get(id=invite.license_id)
    vehicle = Vehicle.objects.get(id=invite.vehicle_id)
    pairing.check_pairable(license, vehicle)

    name = invite.label or label or "Förare"
    from billing.models import Device
    from fleet import device_swaps

    old_device = str(invite.consumed_by_device)
    existing = Device.objects.filter(token=installation_id).first()
    if existing is None or str(existing.id) != old_device:
        device_swaps.assert_can_swap(user_id, now=now)

    paired = pairing.approve_device(
        company_id=invite.company_id,
        license=license,
        vehicle=vehicle,
        approved_by=invite.created_by,
        installation_id=installation_id,
        device_label=name,
        approval_label=name,
        platform=platform,
        push_token=push_token,
        via="email_relogin",
        now=now,
    )
    device = Device.objects.filter(id=paired.device_id).first()
    if device is not None:
        device_swaps.link_account_device(
            user_id=user_id, device=device, via="email_relogin",
            previous_device_id=old_device, now=now,
        )
    if old_device != str(paired.device_id):
        # Den förra telefonen släpper bilen: godkännande, hemlighet och pass.
        old = list(DeviceApproval.objects.filter(
            device_id=old_device, license_id=invite.license_id, status=DeviceApproval.Status.ACTIVE,
        ).values_list("id", flat=True))
        DeviceApproval.objects.filter(id__in=old).update(
            status=DeviceApproval.Status.REPLACED, revoked_at=now, revoke_reason="driver_relogin",
        )
        DeviceCredential.objects.filter(
            device_id=old_device, approval_id__in=old, revoked_at__isnull=True,
        ).update(revoked_at=now, revoke_reason="driver_relogin")
        for open_session in VehicleSession.objects.filter(
            device_id=old_device, approval_id__in=old, ended_at__isnull=True,
        ):
            sessions.end_session(open_session, reason=VehicleSession.EndReason.TAKEOVER, now=now)
    DriverInvite.objects.filter(id=invite.id).update(consumed_by_device=paired.device_id)
    audit.record(
        "driver_relogin", company_id=invite.company_id, actor_user_id=user_id,
        actor_kind="driver", subject_type="driver_invite", subject_id=invite.id,
        detail={"device_id": paired.device_id, "previous_device_id": old_device,
                "replaced_previous": old_device != str(paired.device_id)},
    )
    return paired


def view(invite: DriverInvite, now=None) -> dict:
    now = now or timezone.now()
    return {
        "inviteId": str(invite.id),
        "email": invite.email,
        "label": invite.label,
        "licenseId": str(invite.license_id),
        "vehicleId": str(invite.vehicle_id),
        "status": invite.status,
        "expired": invite.status == DriverInvite.Status.PENDING and invite.expires_at <= now,
        "createdAt": invite.created_at.isoformat() if invite.created_at else None,
        "expiresAt": invite.expires_at.isoformat(),
        "lastSentAt": invite.last_sent_at.isoformat() if invite.last_sent_at else None,
    }


def pending_for_company(company_id, now=None) -> list[DriverInvite]:
    """Väntande inbjudningar, också utgångna -- de kan skickas igen."""
    return list(
        DriverInvite.objects.filter(company_id=company_id, status=DriverInvite.Status.PENDING)
        .select_related("vehicle")
        .order_by("-created_at")
    )
