"""
Körområde på telefonen (`devices.notify_prefs`).

Licensens län är rättigheten. Telefonens val får smalna av, aldrig vidga.
När admin byter baslän måste det sparade valet följa med — annars blir
snittet tomt och föraren ser / får ingenting (samma fel som vid bilbyte
före pairing-fixen 2026-09).
"""

from __future__ import annotations

from django.utils import timezone

from billing.models import Device
from fleet.models import DeviceApproval


def apply_counties_to_prefs(prefs: dict, counties: list[str]) -> dict:
    """Sätter län och klipper kommuner/orter som inte längre hör till."""
    out = dict(prefs or {})
    codes = sorted({str(c) for c in counties if str(c).strip()})
    out["counties"] = codes
    out["municipalities"] = [
        m for m in (out.get("municipalities") or []) if str(m)[:2] in codes
    ]
    # Äldre fält: får inte styra notiser bakom ryggen på länsvalet.
    out["regions"] = []
    out["cities"] = []
    return out


# Licensens län när telefonens val senast sattes. Ett län som tillkommit sedan
# dess (köpt extra län, beviljande) har föraren aldrig kunnat välja bort, och
# ska därför ge notiser direkt -- annars stannade notiserna på baslänet som
# kopplingen satte, fast licensen omfattade två län.
ENTITLED_KEY = "entitledCounties"


def align_prefs_to_entitlement(prefs: dict | None, entitled: list[str] | tuple[str, ...]) -> tuple[dict, bool]:
    """
    Telefonens län mot licensens: valet får smalna av, aldrig vidga.

    * Län som inte längre ingår tas bort; blir inget kvar gäller hela licensen.
    * Län som tillkommit sedan valet sattes (`ENTITLED_KEY`) läggs till.
    * Saknas anteckningen (val sparade före den) och valet är snävare än
      licensen, gäller hela licensen -- det snävare valet var kopplingens
      baslän, inte förarens.

    Returnerar (nya_prefs, ändrades). Tom rättighet rör ingenting.
    """
    entitled_set = {str(c) for c in entitled if str(c).strip()}
    if not entitled_set:
        return dict(prefs or {}), False
    current = dict(prefs or {})
    target = sorted(entitled_set)
    chosen = [str(c) for c in (current.get("counties") or []) if str(c).strip()]
    kept = {c for c in chosen if c in entitled_set}
    recorded = current.get(ENTITLED_KEY)
    if isinstance(recorded, list):
        kept |= entitled_set - {str(c) for c in recorded}
    elif kept:
        kept = set(entitled_set)
    wanted = sorted(kept) or target

    municipalities_ok = all(
        str(m)[:2] in wanted for m in (current.get("municipalities") or [])
    )
    if (
        chosen == wanted and recorded == target and municipalities_ok
        and not (current.get("regions") or current.get("cities"))
    ):
        return current, False
    out = apply_counties_to_prefs(current, wanted)
    out[ENTITLED_KEY] = target
    return out, True


def write_device_prefs(device_id, prefs: dict) -> None:
    Device.objects.filter(id=device_id).update(notify_prefs=prefs)


def account_device_ids(license) -> list:
    """
    Telefonerna som kör licensen genom KONTOT (kontobaserat medlemskap, 2026-10).

    En sådan telefon har inget `DeviceApproval` -- den hittas via licensens
    tilldelade konto (`assignee_user_id`) och telefonradens `devices.user_id`,
    i licensens eget bolag. Bara när kontot har sin öppna app-session på JUST
    den här licensen: utan session gäller kontots medlemsväg (bolagets län),
    och med en session på en annan licens är det den licensens län som gäller.
    """
    from fleet.models import MembershipSession

    user_id = getattr(license, "assignee_user_id", None)
    if not user_id:
        return []
    if not MembershipSession.objects.filter(
        user_id=user_id, license_id=license.id, ended_at__isnull=True
    ).exists():
        return []
    return list(
        Device.objects.filter(user_id=user_id, company_id=license.company_id)
        .values_list("id", flat=True)
    )


def sync_devices_for_license(license, *, counties: list[str] | tuple[str, ...] | None = None, now=None) -> int:
    """
    Uppdaterar körområdet på alla telefoner som kör licensen: de med aktivt
    godkännande på bilen, och kontots telefoner när licensen är ett
    medlemskap som tagits i appen (`account_device_ids`).

    Anropas efter varje länändring (baslänsbyte, provlän, extra län,
    beviljande) och när ett medlemskap tas i appen. Returnerar antal telefoner
    som skrevs om.
    """
    from fleet.pairing import license_counties_for

    if counties is None:
        counties = license_counties_for(license, now or timezone.now())
    device_ids = set(
        DeviceApproval.objects.filter(
            license_id=license.id,
            status=DeviceApproval.Status.ACTIVE,
        ).values_list("device_id", flat=True)
    )
    device_ids.update(account_device_ids(license))
    if not device_ids:
        return 0
    changed = 0
    for device in Device.objects.filter(id__in=device_ids):
        prefs, did = align_prefs_to_entitlement(device.notify_prefs, counties)
        if did:
            write_device_prefs(device.id, prefs)
            changed += 1
    return changed


def heal_device_prefs(device, entitled: list[str] | tuple[str, ...]) -> list[str]:
    """
    Läs-väg: laga en telefon vars sparade län inte längre finns på licensen.

    Returnerar länkoden som ska gälla för anropet (efter eventuell skrivning).
    """
    from core.areas import device_counties

    prefs, did = align_prefs_to_entitlement(device.notify_prefs, entitled)
    if did:
        write_device_prefs(device.id, prefs)
        device.notify_prefs = prefs
    return device_counties(prefs)
