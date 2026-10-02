"""
Bilar, billicenser, länsrättigheter och bilbyten.

**Licensen är bunden till en bil, inte en roterande plats.** Vilken bil den
betjänar avgörs av den ÖPPNA raden i `VehicleAssignment`, som det finns exakt
en av per licens (partiellt unikt index). Det är den invarianten som gör att
ordinarie bil och ersättningsbil aldrig kan köra på samma licens samtidigt
(§4) -- inte en kontroll i Python som ett andra kodflöde kan glömma.

**Länsrättigheter hör till bilen.** `LicenseCounty` hänger på licensen, inte på
företaget: företagets samlade län får inte automatiskt tillfalla alla bilar
(§5). Baslänet ligger också som en rad där, så att åtkomstkontrollen läser EN
lista i stället för att slå ihop ett fält och en tabell.

**Riktning i tiden.** Tillägg (extra län, fler bilar) gäller efter betalning.
Minskningar och byte av baslän gäller vid nästa förnyelse. Det är inte en
policy som råkar vara så -- det är skillnaden mellan `active_from`/`active_to`
här och `PendingChange` i fleet/orders.py.
"""

from __future__ import annotations

import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from core import areas
from fleet import audit, sessions
from fleet.models import (
    ChangeReview,
    DeviceApproval,
    License,
    LicenseCounty,
    RiskConfig,
    RiskSignal,
    Vehicle,
    VehicleAssignment,
    VehicleSession,
)

_PLATE_JUNK = re.compile(r"[^A-Z0-9ÅÄÖ]+")


class LicensingError(Exception):
    def __init__(self, reason: str, message: str, status: int = 400, detail: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.message = message
        self.status = status
        self.detail = detail or {}


def normalize_plate(value: str | None) -> str:
    """'abc 123' och 'ABC123' är samma bil. Versaler, inga skiljetecken."""
    if not value:
        return ""
    return _PLATE_JUNK.sub("", str(value).upper())[:16]


def assert_county_available(code: str) -> str:
    """
    Bara län som finns i produktens täckningskonfiguration.

    GPS-positionen ger ingen behörighet och inget län (§5): föraren kan stå var
    som helst, rättigheten är köpt. Och ett län vi inte har data för får inte gå
    att köpa -- kunden hade betalat för en tom lista.
    """
    code = str(code or "").strip()
    if code not in areas.COUNTY_NAMES:
        raise LicensingError("unknown_county", f"Länskoden {code!r} finns inte.")
    return code


# ---------------------------------------------------------------------------
# Bilar
# ---------------------------------------------------------------------------


def create_vehicle(*, company_id, plate: str, label: str = "", actor_user_id=None) -> Vehicle:
    normalized = normalize_plate(plate)
    if len(normalized) < 2:
        raise LicensingError("invalid_plate", "Registreringsnumret ser inte rätt ut.")
    existing = Vehicle.objects.filter(
        company_id=company_id, plate=normalized, status=Vehicle.Status.ACTIVE
    ).first()
    if existing is not None:
        return existing
    vehicle = Vehicle.objects.create(
        company_id=company_id, plate=normalized, label=(label or "")[:120]
    )
    audit.record(
        "vehicle_created", company_id=company_id, actor_user_id=actor_user_id,
        actor_kind="admin", subject_type="vehicle", subject_id=vehicle.id,
        detail={"plate": normalized},
    )
    return vehicle


@transaction.atomic
def archive_vehicle(vehicle: Vehicle, *, actor_user_id=None, now=None) -> Vehicle:
    now = now or timezone.now()
    if VehicleAssignment.objects.filter(vehicle=vehicle, ended_at__isnull=True).exists():
        raise LicensingError(
            "vehicle_in_use", "Bilen används av en licens. Byt bil på licensen först."
        )
    Vehicle.objects.filter(id=vehicle.id).update(
        status=Vehicle.Status.ARCHIVED, archived_at=now
    )
    audit.record(
        "vehicle_archived", company_id=vehicle.company_id, actor_user_id=actor_user_id,
        actor_kind="admin", subject_type="vehicle", subject_id=vehicle.id,
        detail={"plate": vehicle.plate},
    )
    vehicle.refresh_from_db()
    return vehicle


# ---------------------------------------------------------------------------
# Licenser
# ---------------------------------------------------------------------------


@transaction.atomic
def create_license(
    *,
    company_id,
    vehicle: Vehicle,
    base_county: str,
    status: str = License.Status.ACTIVE,
    trial=None,
    actor_user_id=None,
    now=None,
) -> License:
    """
    En ny billicens med sitt baslän och sin första bil.

    Baslänet väljs per bil när den aktiveras -- också under provet (§5). Utan
    det hade en provbil antingen fått hela landet eller inget län alls.
    """
    now = now or timezone.now()
    base_county = assert_county_available(base_county)
    if str(vehicle.company_id) != str(company_id):
        raise LicensingError("vehicle_company_mismatch", "Bilen hör inte till företaget.")
    if VehicleAssignment.objects.filter(vehicle=vehicle, ended_at__isnull=True).exists():
        raise LicensingError(
            "vehicle_already_licensed", f"{vehicle.plate} har redan en licens."
        )

    license = License.objects.create(
        company_id=company_id, status=status, base_county=base_county, trial=trial
    )
    LicenseCounty.objects.create(
        license=license, county_code=base_county, kind=LicenseCounty.Kind.BASE, active_from=now
    )
    VehicleAssignment.objects.create(
        license=license, vehicle=vehicle, kind=VehicleAssignment.Kind.INITIAL,
        started_at=now, created_by=actor_user_id,
    )
    audit.record(
        "license_created", company_id=company_id, actor_user_id=actor_user_id,
        actor_kind="admin", subject_type="license", subject_id=license.id,
        detail={"vehicle_id": str(vehicle.id), "plate": vehicle.plate,
                "base_county": base_county, "status": status},
    )
    return license


def active_licenses(company_id):
    return License.objects.filter(
        company_id=company_id,
        status__in=[License.Status.ACTIVE, License.Status.PENDING_CANCEL],
    )


def billable_license_count(company_id) -> int:
    """
    Antalet KÖPTA billicenser. Provbilar räknas inte -- de är ett annat fält i
    ett annat flöde, och det är hela skillnaden mellan tre provbilar och tre
    debiterade licenser (§7).
    """
    return active_licenses(company_id).count()


def extra_county_count(company_id, now=None) -> int:
    """Summan av alla bilars extra län. Priset är per bil OCH extra län."""
    now = now or timezone.now()
    license_ids = list(active_licenses(company_id).values_list("id", flat=True))
    return (
        LicenseCounty.objects.filter(
            license_id__in=license_ids, kind=LicenseCounty.Kind.EXTRA, active_from__lte=now
        )
        .exclude(active_to__lte=now)
        .count()
    )


# ---------------------------------------------------------------------------
# Län på en licens
# ---------------------------------------------------------------------------


def activate_extra_county(*, license: License, county_code: str, order=None, now=None) -> LicenseCounty:
    """
    Aktiverar ett extra län. Anropas EFTER lyckad betalning, aldrig före (§5).

    Att kalla den här funktionen är det som ger rättigheten -- den känner inte
    till betalningen och ska inte göra det. Den som anropar ansvarar för att
    ordern är betald; det sker i fleet/orders.py, som är det enda stället där
    betalningsstatus läses.
    """
    now = now or timezone.now()
    county_code = assert_county_available(county_code)
    existing = (
        LicenseCounty.objects.filter(license=license, county_code=county_code)
        .exclude(active_to__lte=now)
        .first()
    )
    if existing is not None:
        return existing
    row = LicenseCounty.objects.create(
        license=license, county_code=county_code, kind=LicenseCounty.Kind.EXTRA,
        active_from=now, order=order,
    )
    audit.record(
        "county_activated", company_id=license.company_id, actor_kind="system",
        subject_type="license", subject_id=license.id,
        detail={"county": county_code, "order_id": str(order.id) if order else None},
    )
    return row


def schedule_county_removal(*, license: License, county_code: str, effective_at, actor_user_id=None):
    """Minskning gäller vid nästa förnyelse -- inte nu (§8)."""
    row = (
        LicenseCounty.objects.filter(
            license=license, county_code=county_code, kind=LicenseCounty.Kind.EXTRA
        )
        .exclude(active_to__isnull=False)
        .first()
    )
    if row is None:
        raise LicensingError("county_not_found", f"Licensen har inget extra län {county_code}.")
    LicenseCounty.objects.filter(id=row.id).update(active_to=effective_at)
    audit.record(
        "county_removal_scheduled", company_id=license.company_id,
        actor_user_id=actor_user_id, actor_kind="admin",
        subject_type="license", subject_id=license.id,
        detail={"county": county_code, "effective_at": effective_at.isoformat()},
    )
    row.refresh_from_db()
    return row


@transaction.atomic
def apply_base_county_change(*, license: License, now=None) -> License:
    """
    Verkställer ett schemalagt baslänsbyte vid förnyelsen.

    Tar samtidigt bort ett extra län som blivit överflödigt: kunden som
    behövde det nya länet direkt köpte det som tillägg, och utan den här
    raden hade hen betalat för samma län två gånger efter bytet (§5).
    """
    now = now or timezone.now()
    target = license.scheduled_base_county
    if not target:
        return license

    old_base = license.base_county
    LicenseCounty.objects.filter(
        license=license, kind=LicenseCounty.Kind.BASE
    ).exclude(active_to__lte=now).update(active_to=now)

    # Det nya baslänet kan redan finnas som betalt extra län. Det avslutas här
    # -- annars fortsätter tillägget debiteras bredvid baslänet.
    removed_extra = LicenseCounty.objects.filter(
        license=license, county_code=target, kind=LicenseCounty.Kind.EXTRA
    ).exclude(active_to__lte=now).update(active_to=now)

    LicenseCounty.objects.create(
        license=license, county_code=target, kind=LicenseCounty.Kind.BASE, active_from=now
    )
    License.objects.filter(id=license.id).update(base_county=target, scheduled_base_county="")
    license.refresh_from_db()
    audit.record(
        "base_county_changed", company_id=license.company_id, actor_kind="system",
        subject_type="license", subject_id=license.id,
        detail={"from": old_base, "to": target, "removed_redundant_extra": bool(removed_extra)},
    )
    return license


def change_base_county_now(*, license: License, county: str, now=None) -> dict:
    """
    Byter baslän DIREKT -- plattformsadministratörens väg, när kunden behöver
    det nu och inte vid förnyelsen (§5 gäller kundens egen ändring).

    Prisneutralt: baslänet ingår i bilens pris oavsett län. Ett extra län som
    blir baslän avslutas, som vid ett schemalagt byte -- annars hade det
    fortsatt debiteras bredvid baslänet. Ett schemalagt byte på samma bil
    ersätts: det gamla beslutet gäller inte längre.
    """
    from fleet.models import PendingChange

    now = now or timezone.now()
    county = assert_county_available(county)
    old = license.base_county
    with transaction.atomic():
        removed_extra = 0
        if county != old:
            LicenseCounty.objects.filter(
                license=license, kind=LicenseCounty.Kind.BASE
            ).exclude(active_to__lte=now).update(active_to=now)
            removed_extra = LicenseCounty.objects.filter(
                license=license, county_code=county, kind=LicenseCounty.Kind.EXTRA
            ).exclude(active_to__lte=now).update(active_to=now)
            LicenseCounty.objects.create(
                license=license, county_code=county, kind=LicenseCounty.Kind.BASE, active_from=now,
            )
        License.objects.filter(id=license.id).update(base_county=county, scheduled_base_county="")
        superseded = PendingChange.objects.filter(
            company_id=license.company_id, kind=PendingChange.Kind.CHANGE_BASE_COUNTY,
            status=PendingChange.Status.PENDING, payload__licenseId=str(license.id),
        ).update(status=PendingChange.Status.SUPERSEDED, canceled_at=now)
    license.refresh_from_db()
    return {
        "licenseId": str(license.id), "from": old, "to": county,
        "removedRedundantExtra": bool(removed_extra), "supersededScheduled": superseded,
    }


def undo_pending_change(change, *, now=None):
    """
    Ångrar en schemalagd ändring innan den verkställts, och tar tillbaka det
    den redan hunnit sätta (schemalagt baslän, slutdatum på ett län eller en bil).
    En uppsägning ångras med "Ångra uppsägning" -- den rör Stripe.
    """
    from fleet.models import PendingChange

    now = now or timezone.now()
    if change.status != PendingChange.Status.PENDING:
        raise LicensingError("not_pending", "Ändringen är redan verkställd eller ångrad.")
    payload = change.payload or {}
    with transaction.atomic():
        if change.kind == PendingChange.Kind.CHANGE_BASE_COUNTY:
            License.objects.filter(
                id=payload.get("licenseId"), company_id=change.company_id,
                scheduled_base_county=payload.get("county", ""),
            ).update(scheduled_base_county="")
        elif change.kind == PendingChange.Kind.REMOVE_COUNTY:
            row = LicenseCounty.objects.filter(
                license_id=payload.get("licenseId"), license__company_id=change.company_id,
                county_code=payload.get("county"), kind=LicenseCounty.Kind.EXTRA,
                active_to__gt=now,
            ).order_by("-created_at").first()
            if row is not None and not LicenseCounty.objects.filter(
                license_id=row.license_id, county_code=row.county_code, active_to__isnull=True,
            ).exists():
                LicenseCounty.objects.filter(id=row.id).update(active_to=None)
        elif change.kind == PendingChange.Kind.REDUCE_LICENSES:
            License.objects.filter(
                id__in=[str(x) for x in payload.get("licenseIds", [])],
                company_id=change.company_id, status=License.Status.PENDING_CANCEL,
            ).update(status=License.Status.ACTIVE, ends_at=None)
        else:
            raise LicensingError(
                "use_undo_cancel", "En uppsägning ångras med \"Ångra uppsägning\" under Betalning.",
            )
        PendingChange.objects.filter(id=change.id).update(
            status=PendingChange.Status.CANCELED, canceled_at=now,
        )


# ---------------------------------------------------------------------------
# Bilbyten
# ---------------------------------------------------------------------------


def vehicle_change_pressure(license: License, *, now=None) -> tuple[int, int]:
    """
    (antal separata bilbyten senaste 30 dagarna, gränsen).

    Räknas på distinkta `case_ref`: en tillfällig ersättning och dess återgång
    är ETT ärende och ska inte räknas som två flyttar (§4).
    """
    now = now or timezone.now()
    config = RiskConfig.current()
    cases = (
        RiskSignal.objects.filter(
            license=license, kind=RiskSignal.Kind.VEHICLE_CHANGE,
            created_at__gte=now - timedelta(days=30),
        )
        .values_list("case_ref", flat=True)
        .distinct()
    )
    return len(set(cases)), config.vehicle_changes_per_30d


def _guard_vehicle_change(license: License, *, now, case_ref) -> None:
    """
    Fler än två separata byten på 30 dagar kräver granskning innan ytterligare
    självservice (§4).

    Granskningen stänger INTE av företaget: den blockerar nästa ändring, och
    senast giltiga åtkomst ligger kvar under tiden.
    """
    count, limit = vehicle_change_pressure(license, now=now)
    open_review = ChangeReview.objects.filter(
        company_id=license.company_id, license=license,
        kind=ChangeReview.Kind.VEHICLE_CHANGE_RATE, status=ChangeReview.Status.OPEN,
    ).first()
    if open_review is not None:
        raise LicensingError(
            "review_required",
            "Ett tidigare bilbyte granskas. Vi hör av oss innan nästa byte kan göras.",
            status=409,
            detail={"reviewId": str(open_review.id), "reviewStatus": open_review.status},
        )
    if count >= limit:
        review = ChangeReview.objects.create(
            company_id=license.company_id, license=license,
            kind=ChangeReview.Kind.VEHICLE_CHANGE_RATE,
            customer_message=(
                f"Licensen har bytt bil {count} gånger på 30 dagar. Vi granskar "
                "bytet innan det kan göras i självservice. Åtkomsten som gäller "
                "nu påverkas inte."
            ),
            detail={"changes_30d": count, "limit": limit, "case_ref": str(case_ref)},
        )
        raise LicensingError(
            "review_required", review.customer_message, status=409,
            detail={"reviewId": str(review.id)},
        )


@transaction.atomic
def change_vehicle(
    *,
    license: License,
    new_vehicle: Vehicle,
    kind: str,
    actor_user_id=None,
    planned_end=None,
    case_ref=None,
    now=None,
) -> VehicleAssignment:
    """
    Flyttar licensen till en annan bil.

    Betalperioden, länen och provhistoriken följer LICENSEN och rörs inte här
    -- de ligger på `Subscription`, `LicenseCounty` och `Trial`. Den gamla
    bilens åtkomst återkallas: sessionen avslutas och godkännandena för de
    telefoner som hörde till den bilen ersätts, så att en telefon i den gamla
    bilen inte fortsätter se tips (§4).
    """
    import uuid as _uuid

    now = now or timezone.now()
    if str(new_vehicle.company_id) != str(license.company_id):
        raise LicensingError("vehicle_company_mismatch", "Bilen hör inte till företaget.")
    if new_vehicle.status != Vehicle.Status.ACTIVE:
        raise LicensingError("vehicle_archived", "Bilen är borttagen.")

    locked = License.objects.select_for_update().get(id=license.id)
    current = (
        VehicleAssignment.objects.select_for_update()
        .filter(license=locked, ended_at__isnull=True)
        .select_related("vehicle")
        .first()
    )
    if current is not None and str(current.vehicle_id) == str(new_vehicle.id):
        return current

    conflicting = VehicleAssignment.objects.filter(
        vehicle=new_vehicle, ended_at__isnull=True
    ).exclude(license=locked).first()
    if conflicting is not None:
        raise LicensingError(
            "vehicle_already_licensed",
            f"{new_vehicle.plate} används redan av en annan licens.",
        )

    if kind == VehicleAssignment.Kind.PERMANENT:
        _guard_vehicle_change(locked, now=now, case_ref=case_ref or _uuid.uuid4())

    case = case_ref or (current.case_ref if (current and kind == VehicleAssignment.Kind.RETURN)
                        else _uuid.uuid4())

    old_vehicle_id = None
    if current is not None:
        old_vehicle_id = current.vehicle_id
        VehicleAssignment.objects.filter(id=current.id, ended_at__isnull=True).update(
            ended_at=now, ended_reason=kind
        )

    assignment = VehicleAssignment.objects.create(
        license=locked, vehicle=new_vehicle, kind=kind, case_ref=case,
        started_at=now, planned_end=planned_end, created_by=actor_user_id,
    )

    # Gamla bilens åtkomst upphör. Sessionen först: en förare som sitter i den
    # gamla bilen ska sluta se tips nu, inte när token går ut.
    sessions.end_sessions_for_license(
        locked.id, reason=VehicleSession.EndReason.LICENSE_CHANGE, now=now
    )
    if old_vehicle_id is not None:
        DeviceApproval.objects.filter(
            license=locked, vehicle_id=old_vehicle_id, status=DeviceApproval.Status.ACTIVE
        ).update(
            status=DeviceApproval.Status.REPLACED, revoked_at=now,
            revoked_by=actor_user_id, revoke_reason=f"vehicle_{kind}",
        )

    if kind in (VehicleAssignment.Kind.PERMANENT, VehicleAssignment.Kind.TEMPORARY):
        RiskSignal.objects.create(
            company_id=locked.company_id, kind=RiskSignal.Kind.VEHICLE_CHANGE,
            license=locked, vehicle=new_vehicle, case_ref=case, created_at=now,
        )
    audit.record(
        f"vehicle_{kind}", company_id=locked.company_id, actor_user_id=actor_user_id,
        actor_kind="admin", subject_type="license", subject_id=locked.id,
        detail={
            "from_vehicle_id": str(old_vehicle_id) if old_vehicle_id else None,
            "to_vehicle_id": str(new_vehicle.id), "plate": new_vehicle.plate,
            "case_ref": str(case),
            "planned_end": planned_end.isoformat() if planned_end else None,
        },
    )
    return assignment


def change_vehicle_permanently(*, license, new_vehicle, actor_user_id=None, now=None):
    return change_vehicle(
        license=license, new_vehicle=new_vehicle,
        kind=VehicleAssignment.Kind.PERMANENT, actor_user_id=actor_user_id, now=now,
    )


def start_temporary_replacement(
    *, license, replacement_vehicle, planned_end=None, actor_user_id=None, now=None
):
    """
    Tillfällig ersättningsbil. Ordinarie bil och ersättningsbil kan inte köra
    på samma licens samtidigt -- den öppna raden är en, per konstruktion.
    """
    return change_vehicle(
        license=license, new_vehicle=replacement_vehicle,
        kind=VehicleAssignment.Kind.TEMPORARY, planned_end=planned_end,
        actor_user_id=actor_user_id, now=now,
    )


def return_from_replacement(*, license: License, actor_user_id=None, now=None):
    """
    Återgång till ordinarie bil, i SAMMA ärende.

    Ärendet (`case_ref`) följer med, så att återgången inte räknas som ett nytt
    byte i 30-dagarsgränsen (§4).
    """
    now = now or timezone.now()
    current = (
        VehicleAssignment.objects.filter(license=license, ended_at__isnull=True)
        .select_related("vehicle").first()
    )
    if current is None or current.kind != VehicleAssignment.Kind.TEMPORARY:
        raise LicensingError(
            "no_temporary_replacement", "Licensen har ingen tillfällig ersättningsbil."
        )
    previous = (
        VehicleAssignment.objects.filter(license=license, case_ref=current.case_ref)
        .exclude(id=current.id).order_by("-started_at").first()
    )
    if previous is None:
        raise LicensingError(
            "no_original_vehicle", "Hittar ingen ordinarie bil att återgå till."
        )
    return change_vehicle(
        license=license, new_vehicle=previous.vehicle,
        kind=VehicleAssignment.Kind.RETURN, case_ref=current.case_ref,
        actor_user_id=actor_user_id, now=now,
    )


# ---------------------------------------------------------------------------
# Provbilar: län och borttagning (samma regler i adminwebben och appen)
# ---------------------------------------------------------------------------


def set_trial_counties(license: License, *, base: str, extras: list[str] | None = None, now=None):
    """
    Byter län på en PROVBIL, direkt. Kostar inget under provet. En betald bil
    byter län via en offert (tillägg kostar, borttag gäller vid förnyelse),
    så att fakturan stämmer.
    """
    if license.status != License.Status.TRIAL:
        raise LicensingError(
            "paid_license", "Bilen är betald. Län på en betald bil ändras via en beställning.",
        )
    now = now or timezone.now()
    base = assert_county_available(str(base or license.base_county))
    extra_codes = sorted({assert_county_available(str(c)) for c in (extras or [])} - {base})
    with transaction.atomic():
        LicenseCounty.objects.filter(license=license).exclude(active_to__lte=now).update(active_to=now)
        LicenseCounty.objects.create(
            license=license, county_code=base, kind=LicenseCounty.Kind.BASE, active_from=now,
        )
        for county in extra_codes:
            LicenseCounty.objects.create(
                license=license, county_code=county, kind=LicenseCounty.Kind.EXTRA, active_from=now,
            )
        License.objects.filter(id=license.id).update(base_county=base, scheduled_base_county="")
    return base, extra_codes


def remove_trial_license(license: License, *, now=None) -> int:
    """
    Tar bort en PROVBIL nu och frigör provplatsen. Returnerar antalet pass som
    stängdes. En betald bil tas aldrig bort här -- den avslutas vid förnyelse.
    """
    from fleet import sessions

    if license.status != License.Status.TRIAL:
        raise LicensingError(
            "paid_license", "Bilen är betald och avslutas vid förnyelse, inte direkt.",
        )
    now = now or timezone.now()
    with transaction.atomic():
        License.objects.filter(id=license.id).update(
            status=License.Status.CANCELED, canceled_at=now, ends_at=now,
        )
        return sessions.end_sessions_for_license(
            license.id, reason=sessions.VehicleSession.EndReason.LICENSE_CHANGE, now=now,
        )
