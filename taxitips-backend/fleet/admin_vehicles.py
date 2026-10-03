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
from fleet import county_changes, licensing, sessions
from fleet.admin_api import _body, _record, _staff, handle
from fleet.models import License, Subscription, VehicleSession
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
    body = _body(request)
    base, extras = licensing.set_trial_counties(
        license, base=body.get("base") or license.base_county, extras=body.get("extras") or [],
    )
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


@csrf_exempt
@require_POST
@handle
def allow_county_change(request, license_id):
    """
    POST /api/admin/licenses/<id>/allow-county-change {"note": "…"}

    Ger bilen ett extra länbyte den här kalendermånaden (Europe/Stockholm),
    när kunden har bytt två gånger och har ett riktigt skäl. Kunden byter
    sedan själv; personalen byter inte åt hen. Samma tänk som extra
    telefonbyte (fleet/device_swaps.py).
    """
    principal = _staff(request, Perm.ADMIN_SELL)
    license = _license_or_404(license_id)
    note = str(_body(request).get("note") or "").strip()[:300]
    result = county_changes.grant_extra_change(
        license, actor_user_id=principal.user_id, note=note,
    )
    summary = result["countyChanges"]
    _record(
        principal, "admin_county_change_grant", company_id=license.company_id,
        subject_type="license", subject_id=license.id,
        detail={"month": summary["month"], "remaining": summary["remaining"], "note": note},
    )
    return _json(request, {"ok": True, **result})


def _reason(request) -> str:
    reason = str(_body(request).get("reason") or "").strip()[:300]
    if not reason:
        raise licensing.LicensingError("reason_required", "Skriv varför ändringen görs. Det loggas.")
    return reason


def _base_county_permission(principal, licenses) -> None:
    """Provbilar: säljare. Betalda bilar: bara plattformsadministratören."""
    if any(lic.status != License.Status.TRIAL for lic in licenses) and not principal.can(Perm.ADMIN_MANAGE):
        raise licensing.LicensingError(
            "admin_only", "Bara en plattformsadministratör byter baslän direkt på en betald bil.",
            status=403,
        )


@csrf_exempt
@require_POST
@handle
def set_base_county_now(request, license_id):
    """
    POST /api/admin/licenses/<id>/base-county {"county": "12", "reason": "..."}

    Byter baslän på EN bil direkt, i stället för vid förnyelsen. Prisneutralt
    (baslänet ingår i priset); ett schemalagt byte på bilen ersätts.
    """
    principal = _staff(request, Perm.ADMIN_SELL)
    license = _license_or_404(license_id)
    _base_county_permission(principal, [license])
    reason = _reason(request)
    result = licensing.change_base_county_now(
        license=license, county=str(_body(request).get("county") or ""),
    )
    _record(
        principal, "admin_base_county_set", company_id=license.company_id,
        subject_type="license", subject_id=license.id, detail={**result, "reason": reason},
    )
    return _json(request, {"ok": True, **result})


@csrf_exempt
@require_POST
@handle
def set_company_base_county(request, company_id):
    """
    POST /api/admin/companies/<id>/base-county {"county": "12", "reason": "..."}

    Byter baslän på ALLA företagets bilar direkt -- t.ex. när ett bolag
    registrerats i fel län eller flyttar verksamheten. Samma regler som för en
    bil, i en transaktion: antingen byts alla eller ingen.
    """
    principal = _staff(request, Perm.ADMIN_SELL)
    licenses = list(License.objects.filter(company_id=company_id, status__in=_OPEN).order_by("created_at"))
    if not licenses:
        raise licensing.LicensingError("no_licenses", "Företaget har inga bilar att byta baslän på.")
    _base_county_permission(principal, licenses)
    reason = _reason(request)
    county = str(_body(request).get("county") or "")
    with transaction.atomic():
        results = [licensing.change_base_county_now(license=lic, county=county) for lic in licenses]
    _record(
        principal, "admin_company_base_county_set", company_id=company_id,
        subject_type="company", subject_id=company_id,
        detail={"to": county, "reason": reason, "licenses": results},
    )
    return _json(request, {"ok": True, "county": county, "changed": len(results), "licenses": results})


@csrf_exempt
@require_POST
@handle
def undo_pending_change(request, change_id):
    """
    POST /api/admin/pending-changes/<id>/undo {"reason": "..."}

    Ångrar en ändring som väntar på nästa förnyelse: baslänsbyte, borttaget
    län eller avslutade bilar. Påverkar vad som förnyas -- därför bara
    plattformsadministratören, med skäl.
    """
    from fleet.models import PendingChange

    principal = _staff(request, Perm.ADMIN_MANAGE)
    change = PendingChange.objects.filter(id=change_id).first()
    if change is None:
        raise licensing.LicensingError("unknown_change", "Ändringen finns inte.", status=404)
    reason = _reason(request)
    licensing.undo_pending_change(change)
    _record(
        principal, "admin_pending_change_undone", company_id=change.company_id,
        subject_type="pending_change", subject_id=change.id,
        detail={"kind": change.kind, "payload": change.payload, "reason": reason},
    )
    return _json(request, {"ok": True})
