"""
Länbyten per bil: högst två per kalendermånad (Europe/Stockholm).

Varför en gräns
---------------
Länet är det kunden betalar för. En bil som fritt kan hoppa mellan län -- Skåne
på förmiddagen, Stockholm på kvällen -- får alla län till priset av ett. Två
byten i månaden räcker för den som faktiskt flyttar verksamheten eller valde
fel län, men inte för att rotera. Gränsen gäller även under provet: annars
blir provbilen ett gratis kort till alla län.

Vad som räknas som ett byte
---------------------------
* **Provbil, direkt** (`POST /api/fleet/trial/vehicles/<id>/county`): ett anrop
  där baslänet byts, eller där bilen får ett extra län den inte hade (byte av
  ett extra län mot ett annat). Att bara ta bort ett extra län räknas inte --
  det smalnar av, det hoppar inte.
* **Betald bil, beställning** (`baseCountyChanges` i `/api/fleet/orders`):
  varje rad som byter baslän mot ett annat län än det nuvarande eller det som
  redan är schemalagt. Bytet räknas när kunden beställer det, inte när det
  verkställs vid förnyelsen: det är beställningen kunden kan upprepa. En
  misslyckad eller avbruten beställning räknas inte.

Det som INTE räknas: att köpa ett extra län (`addCounties`, och den köpta delen
av ett byte med `immediate`) -- det kostar pengar och är inget hopp. Och
personalens ändringar i adminwebben: de begränsas inte, men loggas i
revisionsloggen som förut.

Gräns: två byten per bil och kalendermånad. Därefter `county_change_limit`
tills personal med ADMIN_SELL ger ett extra byte (`grant_extra_change`) --
samma tänk som telefonbytena i fleet/device_swaps.py, och samma månad.

Räkningen ligger i databasen (`fleet_county_change`), inte i cachen:
produktionen har ingen delad cache, och en broms som nollställs vid omstart
är ingen gräns.
"""

from __future__ import annotations

import uuid

from django.db import transaction
from django.db.models import Count
from django.utils import timezone

from fleet import device_swaps, licensing
from fleet.models import CountyChange, CountyChangeGrant, License, LicenseCounty, Order

MONTHLY_LIMIT = 2

# Samma kalendermånad som telefonbytena -- två olika månadsgränser i samma
# kundsamtal hade varit omöjliga att förklara.
month_key = device_swaps.month_key
month_bounds = device_swaps.month_bounds

VIA_TRIAL = "trial"
VIA_ORDER = "order"

# En beställning som aldrig blev av har inte bytt något län.
_VOID_ORDER_STATUSES = (Order.Status.FAILED, Order.Status.CANCELED)

_TIMES = {1: "en gång", 2: "två gånger", 3: "tre gånger", 4: "fyra gånger", 5: "fem gånger"}


class CountyChangeError(Exception):
    def __init__(self, reason: str, message: str, status: int = 403, detail: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.message = message
        self.status = status
        self.detail = detail or {}


def limit_message(plate: str, used: int) -> str:
    who = f"Bilen {plate}" if plate else "Bilen"
    times = _TIMES.get(used, f"{used} gånger")
    return (
        f"{who} har redan bytt län {times} den här månaden. "
        "Det går att byta igen nästa månad. Behöver du byta nu? "
        "Kontakta support så hjälper vi dig."
    )


# ---------------------------------------------------------------------------
# Räkna
# ---------------------------------------------------------------------------


def _counted(license_ids, now):
    start, end = month_bounds(now)
    void = Order.objects.filter(status__in=_VOID_ORDER_STATUSES).values("id")
    return (
        CountyChange.objects.filter(
            license_id__in=license_ids, created_at__gte=start, created_at__lt=end,
        )
        .exclude(order_id__in=void)
    )


def summaries_for(license_ids, *, now=None) -> dict[str, dict]:
    """
    `countyChanges` för många bilar med två frågor, oavsett hur många bilar
    bolaget har -- översikten för ett bolag med 200 bilar ska inte bli 400
    frågor till.
    """
    now = now or timezone.now()
    ids = [str(i) for i in license_ids]
    if not ids:
        return {}
    used = {
        str(row["license_id"]): row["n"]
        for row in _counted(ids, now).values("license_id").annotate(n=Count("id"))
    }
    key = month_key(now)
    extra = {
        str(row["license_id"]): row["n"]
        for row in CountyChangeGrant.objects.filter(license_id__in=ids, month_key=key)
        .values("license_id").annotate(n=Count("id"))
    }
    out = {}
    for i in ids:
        u, e = used.get(i, 0), extra.get(i, 0)
        out[i] = {
            "month": key, "used": u, "limit": MONTHLY_LIMIT, "extra": e,
            "remaining": max(0, MONTHLY_LIMIT + e - u),
        }
    return out


def summary_for(license_id, *, now=None) -> dict:
    """`{"month": "2026-10", "used": n, "limit": 2, "extra": k, "remaining": r}`"""
    return summaries_for([license_id], now=now)[str(license_id)]


def assert_can_change(license: License, *, count: int = 1, now=None) -> dict:
    """Höjer `county_change_limit` om bilen inte har `count` byten kvar."""
    from fleet import sessions

    summary = summary_for(license.id, now=now)
    if summary["remaining"] < count:
        vehicle = sessions.current_vehicle(license)
        plate = vehicle.plate if vehicle else ""
        raise CountyChangeError(
            "county_change_limit", limit_message(plate, summary["used"]),
            detail={"licenseId": str(license.id), "plate": plate, "countyChanges": summary},
        )
    return summary


def _record(license: License, *, from_county, to_county, via, actor_user_id, order_id=None, now):
    return CountyChange.objects.create(
        id=uuid.uuid4(), license_id=license.id, company_id=license.company_id,
        from_county=from_county or "", to_county=to_county or "", via=via,
        order_id=order_id, actor_user_id=actor_user_id, created_at=now,
    )


# ---------------------------------------------------------------------------
# Provbilen: byt län direkt
# ---------------------------------------------------------------------------


def _active_counties(license: License, now) -> tuple[set[str], set[str]]:
    rows = LicenseCounty.objects.filter(license=license).exclude(active_to__lte=now)
    base = {r.county_code for r in rows if r.kind == LicenseCounty.Kind.BASE}
    extras = {r.county_code for r in rows if r.kind == LicenseCounty.Kind.EXTRA}
    return base, extras


def change_trial_counties(
    license: License, *, base: str, extras: list[str] | None = None, actor_user_id=None, now=None,
) -> dict:
    """
    Kundens länbyte på en provbil. Utan `extras` behålls bilens extra län
    (utom det som blir baslän) -- en kund som bara byter baslän ska inte
    tappa län som säljaren gett provet.

    Kunden får byta ett extra län mot ett annat men inte lägga till fler än
    bilen har: hur många län provet omfattar bestämmer säljaren (ett per bil
    i självregistreringen, se sales._add_trial_vehicles).
    """
    now = now or timezone.now()
    with transaction.atomic():
        # Låset gör att två samtidiga byten inte båda ser "ett kvar".
        license = License.objects.select_for_update().get(id=license.id)
        licensing.assert_trial_license(license)
        new_base = licensing.assert_county_available(str(base or license.base_county))
        old_base_rows, old_extras = _active_counties(license, now)
        old_base = license.base_county
        if extras is None:
            new_extras = sorted(old_extras - {new_base})
        else:
            new_extras = sorted(
                {licensing.assert_county_available(str(c)) for c in extras} - {new_base}
            )
        if len(new_extras) > len(old_extras):
            raise licensing.LicensingError(
                "trial_extra_county",
                "Under provet kan du byta län men inte lägga till fler. "
                "Fler län ordnar en säljare hos TaxiTips.",
            )
        old_all = old_base_rows | old_extras | {old_base}
        unchanged = new_base == old_base and set(new_extras) == old_extras
        counts = new_base != old_base or bool(set(new_extras) - old_all)
        if unchanged:
            return {
                "base": new_base, "extras": new_extras, "counted": False,
                "countyChanges": summary_for(license.id, now=now),
            }
        if counts:
            assert_can_change(license, now=now)
        licensing.set_trial_counties(license, base=new_base, extras=new_extras, now=now)
        if counts:
            _record(
                license, from_county=old_base, to_county=new_base, via=VIA_TRIAL,
                actor_user_id=actor_user_id, now=now,
            )
    return {
        "base": new_base, "extras": new_extras, "counted": counts,
        "countyChanges": summary_for(license.id, now=now),
    }


# ---------------------------------------------------------------------------
# Betald bil: baslänsbyte via beställning
# ---------------------------------------------------------------------------


def plan_changes(company_id, base_county_changes, *, lock: bool = False) -> list[tuple[License, str]]:
    """
    Raderna i `baseCountyChanges` som är riktiga byten: till ett annat län än
    baslänet och än det som redan är schemalagt. Samma byte beställt igen, eller
    tillbaka till nuvarande baslän, är inget nytt hopp.
    """
    items = [i for i in (base_county_changes or []) if i.get("licenseId") and i.get("county")]
    if not items:
        return []
    ids = {str(i["licenseId"]) for i in items}
    qs = License.objects.filter(id__in=ids, company_id=company_id)
    if lock:
        qs = qs.select_for_update()
    licenses = {str(lic.id): lic for lic in qs}
    out = []
    for item in items:
        lic = licenses.get(str(item["licenseId"]))
        county = str(item["county"])
        if lic is None or county in (lic.base_county, lic.scheduled_base_county):
            continue
        out.append((lic, county))
    return out


def assert_plan_allowed(changes: list[tuple[License, str]], *, now=None) -> None:
    per_license: dict[str, list] = {}
    for lic, _county in changes:
        per_license.setdefault(str(lic.id), []).append(lic)
    for rows in per_license.values():
        assert_can_change(rows[0], count=len(rows), now=now)


def record_plan(changes: list[tuple[License, str]], *, order, actor_user_id=None, now=None) -> int:
    """Bokför bytena på beställningen. En dubbelklick (samma order) räknas en gång."""
    now = now or timezone.now()
    if not changes or CountyChange.objects.filter(order_id=order.id).exists():
        return 0
    for lic, county in changes:
        _record(
            lic, from_county=lic.base_county, to_county=county, via=VIA_ORDER,
            actor_user_id=actor_user_id, order_id=order.id, now=now,
        )
    return len(changes)


# ---------------------------------------------------------------------------
# Personalen
# ---------------------------------------------------------------------------


@transaction.atomic
def grant_extra_change(license: License, *, actor_user_id, note: str = "", now=None) -> dict:
    """Personal ger bilen ett extra länbyte den här kalendermånaden."""
    now = now or timezone.now()
    row = CountyChangeGrant.objects.create(
        id=uuid.uuid4(), license_id=license.id, company_id=license.company_id,
        month_key=month_key(now), granted_by=actor_user_id, note=(note or "")[:300],
        created_at=now,
    )
    return {"grantId": str(row.id), "countyChanges": summary_for(license.id, now=now)}
