"""
Parkoppling: hur en telefon blir godkänd för en bil, och hur den spärras.

**Vad som ersätts.** `public.join_device(p_join_code, p_label)` är SECURITY
DEFINER och delar ut en permanent enhetstoken direkt ur företagets statiska
bolagskod. Koden står på ett papper i fikarummet. Den som läser den får betald
data tills någon byter kod, och bytet låser ut alla förare samtidigt. Den vägen
stängs (se supabase-migrationen 20260920000001) och ersätts av två steg:

1. **Administratören** väljer bil och skapar en engångskod, giltig högst fem
   minuter (`RiskConfig.pairing_code_ttl_seconds`).
2. **Telefonen** löser in koden tillsammans med sitt installations-id och får
   en hemlighet som bara finns hashad på servern.

Bolagskoden får härefter bara göra en sak: hitta företaget och lägga en
ANSÖKAN (`JoinRequest`). Ingen liveåtkomst, inga permanenta credentials.

**Varför koden konsumeras med ett villkorat UPDATE.** Två telefoner som läser
samma QR-kod i samma sekund gör två samtidiga anrop. En kontroll i Python
("finns koden och är oanvänd? -> använd den") släpper igenom båda. `UPDATE ...
WHERE consumed_at IS NULL` avgörs av databasen och kan bara lyckas en gång.

**Ominstallation** ger en ny hemlighet och kräver ett nytt godkännande, men
rör aldrig provtiden -- den bor på `Trial` och är nyckelad på företagets
organisationsnummer, inte på telefonen (§2).
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from billing.models import Company, Device
from fleet import audit, ratelimit
from fleet.models import (
    DeviceApproval,
    DeviceCredential,
    JoinRequest,
    License,
    PairingCode,
    RiskConfig,
    RiskSignal,
    Vehicle,
)

# Inga tvetydiga tecken: 0/O och 1/I är samma sak när koden läses upp i telefon.
_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 8
_MAX_TTL_SECONDS = 300  # §2: giltig HÖGST fem minuter. Konfigurationen får sänka, aldrig höja.


class PairingError(Exception):
    def __init__(self, reason: str, message: str, status: int = 400):
        super().__init__(reason)
        self.reason = reason
        self.message = message
        self.status = status


def normalize_code(value: str | None) -> str:
    """Versaler, inga mellanslag eller bindestreck. 'abcd-efgh' == 'ABCDEFGH'."""
    if not value:
        return ""
    return "".join(ch for ch in str(value).upper() if ch in _ALPHABET)


def hash_code(code: str) -> str:
    return hashlib.sha256(normalize_code(code).encode()).hexdigest()


def hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def hash_installation(installation_id: str) -> str:
    return hashlib.sha256((installation_id or "").encode()).hexdigest()


def _new_code() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(_CODE_LENGTH))


@dataclass(frozen=True)
class IssuedCode:
    """Koden i klartext lämnar servern EN gång: i svaret till administratören."""

    code: str
    expires_at: object
    pairing_id: str
    vehicle_id: str
    license_id: str

    def as_dict(self) -> dict:
        return {
            "code": self.code,
            # QR-nyttolasten bär samma kod. Ingen extra hemlighet, inget extra
            # format att hålla i synk.
            "qrPayload": f"taxitips://pair?code={self.code}",
            "expiresAt": self.expires_at.isoformat(),
            "pairingId": self.pairing_id,
            "vehicleId": self.vehicle_id,
            "licenseId": self.license_id,
        }


def issue_code(
    *,
    license: License,
    vehicle: Vehicle,
    created_by: str | None,
    label: str = "",
    now=None,
) -> IssuedCode:
    """
    Skapar engångskoden. Klartexten returneras och sparas aldrig.

    Bilen måste höra till samma företag som licensen -- annars hade en
    administratör kunnat parkoppla en telefon mot en annan kunds licens genom
    att skicka ett främmande id.
    """
    now = now or timezone.now()
    if str(vehicle.company_id) != str(license.company_id):
        raise PairingError("vehicle_company_mismatch", "Bilen hör inte till företaget.")
    if vehicle.status != Vehicle.Status.ACTIVE:
        raise PairingError("vehicle_archived", "Bilen är borttagen.")
    if license.status not in (License.Status.ACTIVE, License.Status.TRIAL, License.Status.PENDING_CANCEL):
        raise PairingError("license_inactive", "Licensen är inte aktiv.")

    ratelimit.enforce(ratelimit.PAIRING_ISSUE, str(license.company_id))

    config = RiskConfig.current()
    ttl = min(int(config.pairing_code_ttl_seconds or _MAX_TTL_SECONDS), _MAX_TTL_SECONDS)
    expires_at = now + timedelta(seconds=ttl)

    # Bara en giltig kod per bil i taget: en administratör som klickar två
    # gånger ska inte lämna en glömd kod öppen i fem minuter.
    PairingCode.objects.filter(
        vehicle=vehicle, status=PairingCode.Status.PENDING, consumed_at__isnull=True
    ).update(status=PairingCode.Status.REVOKED)

    for _ in range(5):
        code = _new_code()
        digest = hash_code(code)
        if PairingCode.objects.filter(code_hash=digest).exists():
            continue
        pairing = PairingCode.objects.create(
            company_id=license.company_id,
            license=license,
            vehicle=vehicle,
            code_hash=digest,
            label=label[:80],
            created_by=created_by,
            expires_at=expires_at,
        )
        audit.record(
            "pairing_code_issued",
            company_id=license.company_id,
            actor_user_id=created_by,
            actor_kind="admin",
            subject_type="vehicle",
            subject_id=vehicle.id,
            detail={"license_id": str(license.id), "pairing_id": str(pairing.id), "ttl_seconds": ttl},
        )
        return IssuedCode(
            code=code, expires_at=expires_at, pairing_id=str(pairing.id),
            vehicle_id=str(vehicle.id), license_id=str(license.id),
        )
    raise PairingError("code_generation_failed", "Kunde inte skapa en kod. Försök igen.")


@dataclass(frozen=True)
class PairedDevice:
    device_id: str
    company_id: str
    vehicle_id: str
    license_id: str
    approval_id: str
    secret: str
    plate: str

    def as_dict(self) -> dict:
        return {
            "deviceId": self.device_id,
            "companyId": self.company_id,
            "vehicleId": self.vehicle_id,
            "licenseId": self.license_id,
            "approvalId": self.approval_id,
            # Hemligheten lämnar servern EN gång. Telefonen lägger den i
            # plattformens säkra lagring; servern har bara hashen.
            "deviceToken": self.secret,
            "plate": self.plate,
        }


@transaction.atomic
def redeem_code(
    *,
    code: str,
    installation_id: str,
    label: str = "",
    platform: str = "",
    push_token: str | None = None,
    now=None,
) -> PairedDevice:
    """
    Telefonens sida av parkopplingen.

    Ordningen är medveten: hastighetsbroms -> slå upp -> kontrollera tid och
    försök -> konsumera atomiskt -> skapa enhet och godkännande. Konsumtionen
    sker innan något skrivs, så att två samtidiga inlösningar av samma kod ger
    exakt en godkänd telefon.
    """
    now = now or timezone.now()
    normalized = normalize_code(code)
    if len(normalized) != _CODE_LENGTH:
        raise PairingError("invalid_code", "Koden ser inte rätt ut. Be om en ny.")
    if not installation_id or len(installation_id) < 8:
        raise PairingError("installation_id_required", "Appen kunde inte identifiera telefonen.")

    ratelimit.enforce(ratelimit.PAIRING_REDEEM, hash_installation(installation_id)[:32])

    pairing = PairingCode.objects.select_for_update().filter(code_hash=hash_code(normalized)).first()
    if pairing is None:
        # Samma svar som en förbrukad kod: en angripare ska inte kunna skilja
        # "fel kod" från "rätt kod, redan använd".
        raise PairingError("invalid_code", "Koden är ogiltig eller redan använd.")

    PairingCode.objects.filter(id=pairing.id).update(attempts=pairing.attempts + 1)
    if pairing.attempts + 1 > pairing.max_attempts:
        PairingCode.objects.filter(id=pairing.id).update(status=PairingCode.Status.REVOKED)
        raise PairingError("too_many_attempts", "För många försök med den koden. Be om en ny.")
    if pairing.status != PairingCode.Status.PENDING or pairing.consumed_at is not None:
        raise PairingError("invalid_code", "Koden är ogiltig eller redan använd.")
    if pairing.expires_at <= now:
        PairingCode.objects.filter(id=pairing.id).update(status=PairingCode.Status.REVOKED)
        raise PairingError("code_expired", "Koden har gått ut. Be administratören om en ny.")

    # Atomisk konsumtion: villkoret ligger i WHERE, inte i Python.
    consumed = PairingCode.objects.filter(
        id=pairing.id, consumed_at__isnull=True, status=PairingCode.Status.PENDING
    ).update(consumed_at=now, status=PairingCode.Status.CONSUMED)
    if consumed != 1:
        raise PairingError("invalid_code", "Koden är ogiltig eller redan använd.")

    license = License.objects.select_related(None).get(id=pairing.license_id)
    vehicle = Vehicle.objects.get(id=pairing.vehicle_id)
    company = Company.objects.filter(id=pairing.company_id).first()
    if company is None:
        raise PairingError("unknown_company", "Företaget finns inte.")

    device = _upsert_device(
        company_id=pairing.company_id,
        installation_id=installation_id,
        label=label or pairing.label or "Förare",
        platform=platform,
        push_token=push_token,
        now=now,
    )
    PairingCode.objects.filter(id=pairing.id).update(consumed_by_device=device.id)

    # Ominstallation eller ny bil: tidigare godkännanden för SAMMA licens
    # ersätts, övriga bilar rörs inte -- en telefon får vara godkänd för flera
    # bilar (§3 talar om byten mellan två bilar på samma telefon).
    DeviceApproval.objects.filter(
        device_id=device.id, license=license, status=DeviceApproval.Status.ACTIVE
    ).update(status=DeviceApproval.Status.REPLACED, revoked_at=now, revoke_reason="repaired")

    approval = DeviceApproval.objects.create(
        company_id=pairing.company_id,
        device_id=device.id,
        license=license,
        vehicle=vehicle,
        label=label[:80] or pairing.label[:80],
        approved_at=now,
        approved_by=pairing.created_by,
    )

    secret = secrets.token_urlsafe(32)
    # Gamla hemligheter för samma enhet återkallas: en ominstallation ska inte
    # lämna en giltig token kvar på den telefon som lämnades in.
    DeviceCredential.objects.filter(device_id=device.id, revoked_at__isnull=True).update(
        revoked_at=now, revoke_reason="repaired"
    )
    DeviceCredential.objects.create(
        device_id=device.id,
        company_id=pairing.company_id,
        token_hash=hash_token(secret),
        prefix=secret[:8],
        scheme=DeviceCredential.Scheme.HASHED_V1,
        approval=approval,
    )

    # Körområdet: en nyparkopplad telefon ärver licensens län.
    #
    # Utan det här är `notify_prefs` tomt, och varje notiskandidat faller på
    # `no_area` i core/notify.py -- telefonen är parkopplad, betald och
    # godkänd, och får ändå ingenting. Det ser ut som att pushen är trasig.
    # Föraren kan smalna av i inställningarna efteråt; rättigheten är ändå
    # licensens, så valet kan aldrig vidga åtkomsten (se fleet/access.py).
    prefs = dict(device.notify_prefs or {})
    if not (prefs.get("counties") or prefs.get("regions") or prefs.get("municipalities")):
        prefs["counties"] = list(license_counties_for(license, now))
        Device.objects.filter(id=device.id).update(notify_prefs=prefs)

    RiskSignal.objects.create(
        company_id=pairing.company_id, kind=RiskSignal.Kind.PAIRING,
        license=license, vehicle=vehicle, device_id=device.id, created_at=now,
    )
    audit.record(
        "device_approved",
        company_id=pairing.company_id,
        actor_user_id=pairing.created_by,
        actor_kind="admin",
        subject_type="device",
        subject_id=device.id,
        detail={
            "vehicle_id": str(vehicle.id), "license_id": str(license.id),
            "approval_id": str(approval.id), "plate": vehicle.plate,
        },
    )
    return PairedDevice(
        device_id=str(device.id), company_id=str(pairing.company_id),
        vehicle_id=str(vehicle.id), license_id=str(license.id),
        approval_id=str(approval.id), secret=secret, plate=vehicle.plate,
    )


def license_counties_for(license: License, now) -> tuple[str, ...]:
    """
    Licensens aktiva län. Egen liten funktion här i stället för ett anrop till
    fleet.access: den modulen importerar den här, och tvärtom hade blivit
    cirkulärt.
    """
    from fleet.models import LicenseCounty

    rows = LicenseCounty.objects.filter(license=license, active_from__lte=now).exclude(
        active_to__lte=now
    )
    return tuple(sorted({row.county_code for row in rows}))


def _upsert_device(*, company_id, installation_id: str, label: str, platform: str,
                   push_token: str | None, now) -> Device:
    """
    Enhetsraden i Supabases `devices`.

    `token` behålls som installations-id för bakåtkompatibilitet med den
    befintliga koden (push, notify_prefs, feedback slår upp på den), men är
    inte längre ett bevis: åtkomsten avgörs av `DeviceCredential` och
    `DeviceApproval`. Se fleet/access.py.
    """
    display = f"{label} ({platform})" if platform else label
    device = Device.objects.filter(token=installation_id).first()
    if device is None:
        if push_token:
            Device.objects.filter(push_token=push_token).exclude(token=installation_id).update(
                push_token=None
            )
        return Device.objects.create(
            id=uuid.uuid4(), company_id=company_id, token=installation_id,
            label=display[:80], kind="driver", push_token=push_token,
            notify_prefs={}, created_at=now, last_seen_at=now,
        )
    if push_token:
        Device.objects.filter(push_token=push_token).exclude(id=device.id).update(push_token=None)
    Device.objects.filter(id=device.id).update(
        company_id=company_id, label=display[:80], kind="driver",
        push_token=push_token or device.push_token, last_seen_at=now,
    )
    device.refresh_from_db()
    return device


@transaction.atomic
def block_device(
    *,
    approval: DeviceApproval,
    actor_user_id: str | None,
    reason: str = "lost_phone",
    now=None,
) -> DeviceApproval:
    """
    Spärra en telefon. Kräver inte tillgång till telefonen (§2).

    Spärren tar effekt omedelbart även om enhetens token fortfarande är giltig,
    eftersom varje skyddad begäran läser godkännandet. Den avslutar också den
    aktiva bilsessionen och nollar push-token, så att redan köade notiser inte
    fortsätter till en telefon som inte längre får se innehållet.
    """
    from fleet import sessions

    now = now or timezone.now()
    DeviceApproval.objects.filter(id=approval.id).update(
        status=DeviceApproval.Status.BLOCKED, revoked_at=now,
        revoked_by=actor_user_id, revoke_reason=reason[:200],
    )
    DeviceCredential.objects.filter(
        device_id=approval.device_id, approval_id=approval.id, revoked_at__isnull=True
    ).update(revoked_at=now, revoke_reason=reason[:200])

    sessions.end_sessions_for_device(
        approval.device_id, reason=sessions.VehicleSession.EndReason.BLOCKED, now=now
    )

    # Inga fler notiser till den här telefonen. Redan levererat innehåll går
    # inte att återkalla -- se core/notify.py och §3.
    if not DeviceApproval.objects.filter(
        device_id=approval.device_id, status=DeviceApproval.Status.ACTIVE
    ).exists():
        Device.objects.filter(id=approval.device_id).update(push_token=None)

    audit.record(
        "device_blocked",
        company_id=approval.company_id,
        actor_user_id=actor_user_id,
        actor_kind="admin",
        subject_type="device",
        subject_id=approval.device_id,
        detail={"approval_id": str(approval.id), "reason": reason[:200]},
    )
    approval.refresh_from_db()
    return approval


def create_join_request(*, company: Company, installation_id: str, label: str = "", now=None) -> JoinRequest:
    """
    Vad bolagskoden får göra: en ansökan. Ingen token, ingen åtkomst.

    Ansökan förfaller efter ett dygn -- en glömd ansökan ska inte ligga och
    vänta på ett godkännande i veckor.
    """
    now = now or timezone.now()
    ratelimit.enforce(ratelimit.JOIN_LOOKUP, hash_installation(installation_id)[:32])
    request = JoinRequest.objects.create(
        company_id=company.id,
        label=label[:80],
        installation_hash=hash_installation(installation_id),
        expires_at=now + timedelta(days=1),
    )
    audit.record(
        "join_request_created", company_id=company.id, actor_kind="driver",
        subject_type="join_request", subject_id=request.id, detail={"label": label[:80]},
    )
    return request
