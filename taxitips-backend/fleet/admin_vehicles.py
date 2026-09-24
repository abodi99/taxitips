"""
Adminwebbens bilhantering för en kund: byt bil (regnr), ändra län, ta bort.

**Pengar avgör vägen.** En provbil kostar inget, så den ändras och tas bort
direkt. En betald bil ändras via en offert och beställning (fleet/orders.py):
fler län kostar, färre län och färre bilar gäller vid nästa förnyelse -- samma
regler som kunden själv har i portalen (§8). Den här filen gör bara det som
inte påverkar fakturan, plus en nödväg för plattformsadministratören.

Varje ändring loggas med vem som gjorde den.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.api import _json
from fleet import licensing, sessions
from fleet.admin_api import _body, _record, _staff, handle
from fleet.models import License, LicenseCounty, Subscription, VehicleSession
from fleet.roles import Perm

_OPEN = (License.Status.ACTIVE, License.Status.TRIAL, License.Status.PENDING_CANCEL)


def _license_or_404(license_id) -> License:
    license = License.objects.filter(id=license_id).first()
    if license is None:
        raise licensing.LicensingError("unknown_license", "Bilen finns inte.", status=404)
    if license.status not in _OPEN:
        raise licensing.LicensingError("license_closed", "Bilen är redan borttagen.")
    return license


@csrf_exempt
@require_POST
@handle
def change_vehicle(request, license_id):
    """
    POST /api/admin/licenses/<id>/vehicle {"plate": "ABC123", "mode": "permanent"|"temporary"|"return"}

    Byter bil på licensen: nytt regnr (även för att rätta ett stavfel),
    tillfällig ersättningsbil, eller tillbaka från ersättningsbilen. Län och
    betalperiod följer med licensen; telefonerna för den gamla bilen måste
    godkännas på nytt (fleet/licensing.py:change_vehicle).
    """
    principal = _staff(request, Perm.ADMIN_SELL)
    license = _license_or_404(license_id)
    body = _body(request)
    mode = str(body.get("mode") or "permanent")
    if mode == "return":
        assignment = licensing.return_from_replacement(license=license, actor_user_id=principal.user_id)
    else:
        vehicle = licensing.create_vehicle(
            company_id=license.company_id, plate=str(body.get("plate") or ""),
            actor_user_id=principal.user_id,
        )
        if mode == "temporary":
            assignment = licensing.start_temporary_replacement(
                license=license, replacement_vehicle=vehicle, actor_user_id=principal.user_id,
            )
        else:
            assignment = licensing.change_vehicle_permanently(
                license=license, new_vehicle=vehicle, actor_user_id=principal.user_id,
            )
    _record(
        principal, "admin_vehicle_changed", company_id=license.company_id,
        subject_type="license", subject_id=license.id,
        detail={"mode": mode, "plate": assignment.vehicle.plate},
    )
    return _json(request, {"ok": True, "plate": assignment.vehicle.plate, "kind": assignment.kind})


@csrf_exempt
@require_POST
@handle
def set_trial_counties(request, license_id):
    """
    POST /api/admin/licenses/<id>/counties {"base": "12", "extras": ["13", "14"]}

    Bara för provbilar: länen kostar inget under provet och ändras direkt. En
    betald bil ändrar län via offerten (tillägg kostar, borttag gäller vid
    förnyelse).
    """
    principal = _staff(request, Perm.ADMIN_SELL)
    license = _license_or_404(license_id)
    if license.status != License.Status.TRIAL:
        raise licensing.LicensingError(
            "paid_license",
            "Bilen är betald. Ändra län via offerten, så att fakturan stämmer.",
        )
    body = _body(request)
    base = licensing.assert_county_available(str(body.get("base") or license.base_county))
    extras = sorted({licensing.assert_county_available(str(c)) for c in (body.get("extras") or [])} - {base})
    now = timezone.now()
    with transaction.atomic():
        LicenseCounty.objects.filter(license=license).exclude(active_to__lte=now).update(active_to=now)
        LicenseCounty.objects.create(
            license=license, county_code=base, kind=LicenseCounty.Kind.BASE, active_from=now,
        )
        for county in extras:
            LicenseCounty.objects.create(
                license=license, county_code=county, kind=LicenseCounty.Kind.EXTRA, active_from=now,
            )
        License.objects.filter(id=license.id).update(base_county=base, scheduled_base_county="")
    _record(
        principal, "admin_trial_counties_set", company_id=license.company_id,
        subject_type="license", subject_id=license.id, detail={"base": base, "extras": extras},
    )
    return _json(request, {"ok": True, "base": base, "extras": extras})


@csrf_exempt
@require_POST
@handle
def remove_license(request, license_id):
    """
    POST /api/admin/licenses/<id>/remove {"reason": "..."}

    Tar bort en bil NU. Provbilar: alltid (kostar inget, frigör en provplats).
    Betalda bilar: bara plattformsadministratören, och bara när abonnemanget
    inte debiteras via Stripe -- där ändrar en direkt borttagning inte fakturan,
    och kunden hade betalat för en bil som inte finns. För dem gäller
    "Avsluta vid förnyelse". Ingen återbetalning görs automatiskt.
    """
    principal = _staff(request, Perm.ADMIN_SELL)
    license = _license_or_404(license_id)
    reason = str(_body(request).get("reason") or "").strip()[:300]
    if not reason:
        raise licensing.LicensingError("reason_required", "Skriv varför bilen tas bort.")
    if license.status != License.Status.TRIAL:
        if not principal.can(Perm.ADMIN_MANAGE):
            raise licensing.LicensingError(
                "admin_only", "Bara en plattformsadministratör tar bort en betald bil direkt.",
                status=403,
            )
        subscription = Subscription.objects.filter(company_id=license.company_id).first()
        if subscription and subscription.stripe_subscription_id:
            raise licensing.LicensingError(
                "stripe_billed",
                "Abonnemanget debiteras via Stripe. Använd \"Avsluta vid förnyelse\" så att fakturan stämmer.",
            )
    now = timezone.now()
    with transaction.atomic():
        License.objects.filter(id=license.id).update(
            status=License.Status.CANCELED, canceled_at=now, ends_at=now,
        )
        ended = sessions.end_sessions_for_license(
            license.id, reason=VehicleSession.EndReason.LICENSE_CHANGE, now=now,
        )
    _record(
        principal, "admin_license_removed", company_id=license.company_id,
        subject_type="license", subject_id=license.id,
        detail={"was": license.status, "reason": reason, "sessions_ended": ended},
    )
    return _json(request, {"ok": True})
