"""
Skiftbyte: exakt en aktiv telefon per billicens, exakt en aktiv bil per telefon.

**Varför databasen avgör och inte Python.** Två förare som trycker "Ta över
bilen" i samma sekund ger två samtidiga anrop. En kontroll i applikationen
("finns det redan en aktiv session? -> nej -> skapa") läser båda innan någon
skriver, och båda får en session. De två partiella unika indexen i
`VehicleSession.Meta.constraints` kan bara lyckas en gång, och
`select_for_update` på licensraden serialiserar dessutom anropen så att den
som förlorar får ett begripligt svar i stället för ett unikhetsfel.

**Låsordning.** När en telefon byter mellan två bilar måste två licensrader
låsas. De låses alltid i stigande id-ordning (`order_by("id")`), vilket är det
som gör två samtidiga byten åt motsatta håll till en kö i stället för en
baklåsning.

**Den gamla telefonen kommer aldrig tillbaka av sig själv.** En session som
avslutats får aldrig återupplivas: bakgrundsuppdatering, tokenförnyelse och
återanslutning går alla genom `heartbeat()`, som bara rör `last_seen_at` på en
ÖPPEN rad. Att ta tillbaka bilen kräver ett nytt, uttryckligt övertagande (§3).

**Nätbortfall släpper ingen licens.** Det finns ingen tidsgräns som stänger en
session automatiskt. `EndReason.EXPIRED` finns för administrativ städning, och
inget schemalagt jobb använder den -- en app i bakgrunden eller en tunnel utan
täckning ska inte se ut som ett skiftbyte (§3).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from billing.models import Device
from fleet import audit
from fleet.models import (
    DeviceApproval,
    License,
    RiskConfig,
    RiskSignal,
    Vehicle,
    VehicleSession,
)


class SessionError(Exception):
    def __init__(self, reason: str, message: str, status: int = 409, detail: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.message = message
        self.status = status
        self.detail = detail or {}


@dataclass(frozen=True)
class SessionResult:
    session: VehicleSession
    took_over_from: str | None = None
    left_license: str | None = None

    def as_dict(self) -> dict:
        s = self.session
        return {
            "sessionId": str(s.id),
            "licenseId": str(s.license_id),
            "vehicleId": str(s.vehicle_id),
            "deviceId": str(s.device_id),
            "startedAt": s.started_at.isoformat(),
            "tookOverFromDevice": self.took_over_from,
            "leftLicense": self.left_license,
        }


def active_session_for_device(device_id) -> VehicleSession | None:
    return VehicleSession.objects.filter(device_id=device_id, ended_at__isnull=True).first()


def active_session_for_license(license_id) -> VehicleSession | None:
    return VehicleSession.objects.filter(license_id=license_id, ended_at__isnull=True).first()


def holder_label(session: VehicleSession) -> str:
    """Namnet administratören satt på telefonen, för meddelandet "X har bilen"."""
    device = Device.objects.filter(id=session.device_id).first()
    return (device.label if device and device.label else "En annan telefon")


@transaction.atomic
def start_session(
    *,
    device_id,
    license_id,
    force: bool = False,
    now=None,
) -> SessionResult:
    """
    Starta eller ta över en bilsession.

    `force=False` är normalfallet: är bilen upptagen får anroparen
    `takeover_required` tillbaka med uppgift om vem som har den, och appen
    frågar föraren. `force=True` är svaret på den frågan -- inte ett sätt att
    hoppa över den.
    """
    now = now or timezone.now()

    # Telefonen låses FÖRST. Utan det kan samma telefon begära två olika bilar
    # samtidigt: de två anropen låser då var sin licensrad, ser ingen konflikt
    # och skapar var sin session -- och telefonen har två aktiva bilar. Med
    # låset serialiseras allt som rör en telefon, oavsett vilka licenser det
    # gäller. (Det partiella unika indexet fångar det ändå, men som ett
    # unikhetsfel i stället för ett begripligt svar.)
    list(Device.objects.select_for_update().filter(id=device_id))

    held = list(
        VehicleSession.objects.filter(device_id=device_id, ended_at__isnull=True)
        .values_list("license_id", flat=True)
    )
    lock_ids = sorted({str(license_id)} | {str(x) for x in held})
    # Stigande id-ordning: se modulens docstring om låsordning.
    locked = list(License.objects.select_for_update().filter(id__in=lock_ids).order_by("id"))
    license = next((row for row in locked if str(row.id) == str(license_id)), None)
    if license is None:
        raise SessionError("unknown_license", "Licensen finns inte.", status=404)

    approval = (
        DeviceApproval.objects.filter(
            device_id=device_id, license_id=license.id, status=DeviceApproval.Status.ACTIVE
        )
        .select_related("vehicle")
        .first()
    )
    if approval is None:
        raise SessionError(
            "not_approved",
            "Telefonen är inte godkänd för den här bilen.",
            status=403,
        )
    if license.status not in (License.Status.ACTIVE, License.Status.TRIAL, License.Status.PENDING_CANCEL):
        raise SessionError("license_inactive", "Licensen är inte aktiv.", status=403)

    # Bilen licensen betjänar just nu. Under en tillfällig ersättning är det
    # ersättningsbilen -- godkännandet pekar på den bil telefonen godkändes
    # för, och de två måste stämma.
    serving = current_vehicle(license)
    if serving is not None and str(serving.id) != str(approval.vehicle_id):
        raise SessionError(
            "vehicle_mismatch",
            f"Licensen används av {serving.plate} just nu. Telefonen är godkänd för "
            f"{approval.vehicle.plate}.",
            status=409,
            detail={"servingVehicle": serving.plate, "approvedVehicle": approval.vehicle.plate},
        )

    # Redan aktiv på just den här licensen: ett hjärtslag, inte ett byte.
    existing = VehicleSession.objects.filter(license_id=license.id, ended_at__isnull=True).first()
    if existing is not None and str(existing.device_id) == str(device_id):
        VehicleSession.objects.filter(id=existing.id).update(last_seen_at=now)
        existing.refresh_from_db()
        return SessionResult(session=existing)

    took_over_from = None
    if existing is not None:
        if not force:
            raise SessionError(
                "takeover_required",
                f"{holder_label(existing)} använder bilen. Vill du ta över?",
                status=409,
                detail={
                    "currentDeviceLabel": holder_label(existing),
                    "since": existing.started_at.isoformat(),
                    "vehicleId": str(existing.vehicle_id),
                },
            )
        VehicleSession.objects.filter(id=existing.id, ended_at__isnull=True).update(
            ended_at=now,
            ended_reason=VehicleSession.EndReason.TAKEOVER,
            ended_by_device=device_id,
        )
        took_over_from = str(existing.device_id)

    # Telefonen lämnar sin förra bil. En telefon får bara ha en aktiv bil.
    left_license = None
    leaving = VehicleSession.objects.filter(device_id=device_id, ended_at__isnull=True).first()
    if leaving is not None:
        VehicleSession.objects.filter(id=leaving.id, ended_at__isnull=True).update(
            ended_at=now, ended_reason=VehicleSession.EndReason.DEVICE_MOVED
        )
        left_license = str(leaving.license_id)

    try:
        session = VehicleSession.objects.create(
            company_id=license.company_id,
            license=license,
            vehicle=approval.vehicle,
            device_id=device_id,
            approval=approval,
            started_at=now,
            last_seen_at=now,
        )
    except IntegrityError:
        # De partiella unika indexen är sista ordet. Kommer vi hit har någon
        # hunnit före trots låsen -- svaret ska vara begripligt, inte ett
        # databasfel. Transaktionen rullas tillbaka av `atomic`.
        raise SessionError(
            "takeover_conflict",
            "Någon annan hann före. Prova igen.",
            status=409,
        )

    if took_over_from:
        RiskSignal.objects.create(
            company_id=license.company_id, kind=RiskSignal.Kind.TAKEOVER,
            license=license, vehicle=approval.vehicle, device_id=device_id, created_at=now,
        )
    audit.record(
        "session_started",
        company_id=license.company_id,
        actor_kind="driver",
        subject_type="session",
        subject_id=session.id,
        detail={
            "license_id": str(license.id), "vehicle_id": str(approval.vehicle_id),
            "device_id": str(device_id), "took_over_from_device": took_over_from,
            "left_license": left_license,
        },
    )
    return SessionResult(session=session, took_over_from=took_over_from, left_license=left_license)


def heartbeat(session: VehicleSession, now=None) -> bool:
    """
    Markera sessionen som levande.

    Uppdaterar BARA en öppen rad: villkoret `ended_at__isnull=True` ligger i
    UPDATE:n. Utan det hade en gammal telefon kunnat väcka en avslutad session
    genom en bakgrundsuppdatering, vilket är precis vad §3 förbjuder.
    """
    now = now or timezone.now()
    return (
        VehicleSession.objects.filter(id=session.id, ended_at__isnull=True).update(last_seen_at=now)
        == 1
    )


def end_session(session: VehicleSession, *, reason: str, now=None, actor_user_id=None) -> bool:
    now = now or timezone.now()
    ended = VehicleSession.objects.filter(id=session.id, ended_at__isnull=True).update(
        ended_at=now, ended_reason=reason
    )
    if ended:
        audit.record(
            "session_ended", company_id=session.company_id, actor_user_id=actor_user_id,
            actor_kind="driver" if actor_user_id is None else "admin",
            subject_type="session", subject_id=session.id, detail={"reason": reason},
        )
    return bool(ended)


def end_sessions_for_device(device_id, *, reason: str, now=None) -> int:
    now = now or timezone.now()
    return VehicleSession.objects.filter(device_id=device_id, ended_at__isnull=True).update(
        ended_at=now, ended_reason=reason
    )


def end_sessions_for_license(license_id, *, reason: str, now=None) -> int:
    now = now or timezone.now()
    return VehicleSession.objects.filter(license_id=license_id, ended_at__isnull=True).update(
        ended_at=now, ended_reason=reason
    )


def current_vehicle(license: License) -> Vehicle | None:
    """
    Bilen licensen betjänar just nu: den öppna raden i `VehicleAssignment`.

    Ett fält på licensen hade varit snabbare och fel -- två flöden (permanent
    byte och återgång från ersättningsbil) hade kunnat skriva det samtidigt.
    """
    from fleet.models import VehicleAssignment

    assignment = (
        VehicleAssignment.objects.filter(license=license, ended_at__isnull=True)
        .select_related("vehicle")
        .first()
    )
    return assignment.vehicle if assignment else None


def takeover_pressure(license_id, *, now=None) -> tuple[int, int]:
    """(antal övertaganden senaste timmen, gränsen). Underlag för riskkontrollen."""
    now = now or timezone.now()
    config = RiskConfig.current()
    count = RiskSignal.objects.filter(
        license_id=license_id, kind=RiskSignal.Kind.TAKEOVER,
        created_at__gte=now - timedelta(hours=1),
    ).count()
    return count, config.takeovers_per_hour
