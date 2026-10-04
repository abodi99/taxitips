"""
Notisinställningarna för ett företags telefoner, som en administratör ser dem.

Kundens administratör (MANAGE_DEVICES, fleet/notify_api.py) och plattformens
personal (ADMIN_SELL, fleet/admin_notify.py) ändrar samma sak som föraren själv
ändrar i appen: `devices.notify_prefs`, genom samma validering
(core/notify_prefs.apply_update). Tre regler håller ihop det:

* **Bara företagets egna telefoner.** Anroparen slår upp telefonen med
  företaget i frågan; en telefon i ett annat företag finns inte (404).
* **Länen aldrig utöver bilens licens.** Rättigheten är unionen av länen för
  bilarna telefonen är godkänd för (fleet/access.license_counties) -- samma
  rättighet som prövas strax före sändningen (fleet/push_gate.py). Ett val
  utanför den sparas inte.
* **Företagets standard gäller nya telefoner.** Den sätts när en telefon
  kopplas till en bil i företaget för första gången (fleet/pairing.py) och
  bär bara reglerna, aldrig område eller paus (core/notify_prefs.DEFAULT_FIELDS).
  Befintliga telefoner rörs bara om administratören uttryckligen ber om det.
"""

from __future__ import annotations

import logging

from django.db import DatabaseError, transaction
from django.utils import timezone

from billing.models import Device
from core import areas, notify_prefs
from fleet import device_prefs, features
from fleet.access import enforce_licenses, license_counties
from fleet.models import CompanyNotifyDefault, DeviceApproval, License

log = logging.getLogger(__name__)

# Reglerna en standard bär och skriver över på en telefon. Område och paus aldrig.
RULE_FIELDS = ("enabled", "weak", "minLevel", "categories", "types", "quietHours", "maxPerHour")

_OPEN = (License.Status.ACTIVE, License.Status.TRIAL, License.Status.PENDING_CANCEL)
_PHONE_LIMIT = 200


def company_default(company_id) -> dict | None:
    """
    Företagets sparade standard, eller None.

    Tål att tabellen saknas: en deploy som hunnit före migreringen 0022 får
    inte fälla en parkoppling för en bekvämlighet. Läsningen ligger i en egen
    savepoint, så att ett fel inte förgiftar anroparens transaktion.
    """
    if not company_id:
        return None
    try:
        with transaction.atomic():
            row = (
                CompanyNotifyDefault.objects.filter(company_id=company_id)
                .values_list("prefs", flat=True).first()
            )
    except DatabaseError:
        log.warning("notify_settings: fleet_company_notify_default går inte att läsa")
        return None
    return dict(row) if isinstance(row, dict) else None


def merge_rules(prefs: dict | None, rules: dict | None) -> dict:
    """Telefonens prefs med reglerna utbytta. Område och paus står kvar."""
    out = dict(prefs) if isinstance(prefs, dict) else {}
    for key in RULE_FIELDS:
        out.pop(key, None)
    out.update({k: v for k, v in (rules or {}).items() if k in RULE_FIELDS})
    return out


def prefs_for_new_phone(company_id, current: dict | None) -> dict:
    """Det en telefon som just kommit till företaget ska ha: standarden, om en finns."""
    default = company_default(company_id)
    if not default:
        return dict(current) if isinstance(current, dict) else {}
    return merge_rules(current, default)


def device_entitlement(device, now=None) -> tuple[list[str], bool]:
    """
    (län, begränsad) för telefonen: unionen av länen för bilarna den är
    godkänd för. Ett företag utan billicenser (före licensmodellen) är inte
    begränsat; ett med licenser men utan godkännande för telefonen har inga län.
    """
    now = now or timezone.now()
    license_ids = list(
        DeviceApproval.objects.filter(
            device_id=device.id, company_id=device.company_id,
            status=DeviceApproval.Status.ACTIVE, license__status__in=_OPEN,
        ).values_list("license_id", flat=True)
    )
    if license_ids:
        counties: set[str] = set()
        for license_id in license_ids:
            counties |= set(license_counties(license_id, now))
        return sorted(counties), True
    if enforce_licenses() or License.objects.filter(company_id=device.company_id).exists():
        return [], True
    return [], False


def update_device(device, body: dict, *, now=None) -> dict:
    """Validera och spara. Anroparen har redan prövat att telefonen hör till rätt företag."""
    now = now or timezone.now()
    entitled, restricted = device_entitlement(device, now)
    prefs = notify_prefs.apply_update(
        device.notify_prefs, body, entitled=entitled, restricted=restricted, now=now,
    )
    if isinstance(body.get("counties"), list) and not prefs.get("counties") and entitled:
        # Inga län kryssade = hela bilens område, inte inga notiser alls
        # (`no_area`). Att tysta en telefon görs med läget Tyst, synligt.
        prefs = device_prefs.apply_counties_to_prefs(prefs, entitled)
    device_prefs.write_device_prefs(device.id, prefs)
    device.notify_prefs = prefs
    return prefs


def set_company_default(company_id, body: dict, *, actor_user_id=None,
                        apply_to_phones: bool = False, now=None) -> tuple[dict, int]:
    """
    Spara företagets standard. Med `apply_to_phones` skrivs reglerna också på
    företagets befintliga telefoner (område och paus står kvar). Returnerar
    (standarden, antal telefoner som skrevs om).
    """
    now = now or timezone.now()
    current = company_default(company_id) or {}
    updated = notify_prefs.apply_update(
        current, body, allowed=notify_prefs.DEFAULT_FIELDS, now=now,
    )
    rules = {k: v for k, v in updated.items() if k in RULE_FIELDS}
    CompanyNotifyDefault.objects.update_or_create(
        company_id=company_id,
        defaults={"prefs": rules, "updated_at": now, "updated_by": actor_user_id},
    )
    changed = 0
    if apply_to_phones:
        for device in Device.objects.filter(company_id=company_id):
            device_prefs.write_device_prefs(device.id, merge_rules(device.notify_prefs, rules))
            changed += 1
    return rules, changed


def audit_detail(body: dict, prefs: dict, entitled=None) -> dict:
    """Vad revisionsloggen bär: vilka fält och vilket läge -- inga hemligheter finns här."""
    return {
        "fields": sorted(str(k) for k in (body or {}).keys())[:20],
        "preset": notify_prefs.preset_of(prefs, entitled=entitled),
    }


def phone_row(device, *, plates=None, entitled=None, restricted=None, now=None) -> dict:
    now = now or timezone.now()
    if entitled is None or restricted is None:
        entitled, restricted = device_entitlement(device, now)
    prefs = device.notify_prefs if isinstance(device.notify_prefs, dict) else {}
    return {
        "deviceId": str(device.id),
        "label": device.label or "",
        "kind": device.kind or "",
        "plates": list(plates or []),
        "prefs": prefs,
        "preset": notify_prefs.preset_of(prefs, entitled=entitled),
        "summary": notify_prefs.summary(prefs, entitled=entitled, now=now),
        "counties": areas.device_counties(prefs),
        "entitledCounties": list(entitled),
        "areaLocked": bool(restricted and not entitled),
    }


def overview(company_id, *, now=None) -> dict:
    """Standarden och varje telefon i företaget, med katalogerna formuläret behöver."""
    now = now or timezone.now()
    devices = list(Device.objects.filter(company_id=company_id).order_by("-last_seen_at")[:_PHONE_LIMIT])
    approvals = list(
        DeviceApproval.objects.filter(
            company_id=company_id, status=DeviceApproval.Status.ACTIVE,
            device_id__in=[d.id for d in devices], license__status__in=_OPEN,
        ).select_related("vehicle")
    )
    counties_by_license: dict[str, set[str]] = {}
    plates: dict[str, list[str]] = {}
    licenses: dict[str, set[str]] = {}
    for a in approvals:
        key = str(a.device_id)
        if a.vehicle and a.vehicle.plate:
            plates.setdefault(key, []).append(a.vehicle.plate)
        licenses.setdefault(key, set()).add(str(a.license_id))
        if str(a.license_id) not in counties_by_license:
            counties_by_license[str(a.license_id)] = set(license_counties(a.license_id, now))
    company_restricted = enforce_licenses() or License.objects.filter(company_id=company_id).exists()
    phones = []
    all_entitled: set[str] = set()
    for device in devices:
        owned = licenses.get(str(device.id), set())
        entitled = sorted(set().union(*(counties_by_license[lic] for lic in owned))) if owned else []
        all_entitled |= set(entitled)
        phones.append(phone_row(
            device, plates=sorted(plates.get(str(device.id), [])),
            entitled=entitled, restricted=bool(owned) or company_restricted, now=now,
        ))
    default = company_default(company_id) or {}
    municipalities = areas.municipality_catalog()
    shown = all_entitled or ({c for c in municipalities} if not company_restricted else set())
    return {
        "default": default,
        "defaultPreset": notify_prefs.preset_of(default),
        "defaultSummary": notify_prefs.summary(default, now=now),
        "phones": phones,
        "countyCatalog": areas.county_catalog(),
        # Bara länen någon av företagets bilar har: hela katalogen är 290 kommuner.
        "municipalityCatalog": {c: municipalities.get(c, []) for c in sorted(shown)},
        "features": features.for_company(company_id, now).as_dict(),
        **notify_prefs.catalogs(),
    }
