"""
Färjorna i appen och på pipeline-sidan.

`/api/ferries` är förarens vy, filtrerad till förarens område. `rows` är EN lista som
både kartan och listan i appen läser (ägarkrav 2026-10-09: allt kartan visar ska finnas
i listan). Den är unionen av

* ankomsterna (`maritime/relevance.py`: tidtabell + AIS, med hämtningsfönster), och
* de stora passagerarfärjorna som AIS ser på väg in, vid kaj eller lägga till
  (`maritime/approach.py`) men som inte redan är en ankomst ovan.

Före 2026-10-09 ritade kartan `ferries` (alla AIS-fartyg) och listan `arrivals` (bara
ankomsterna i tidsfönstret): sex färjor på kartan, en i listan. `ferries` och
`arrivals` skickas kvar för äldre appar.

En rad bär bara det föraren behöver: namn, storlek, kaj, väntad ankomst och var den
syns på kartan. Inga källnamn, MMSI, fart eller kurs i text (kursen följer med bara för
pilen på kartan). `/api/pipeline/ferries` är hela snapshoten, bara med DEBUG.
"""

from __future__ import annotations

import functools

from django.views.decorators.gzip import gzip_page
from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from core import areas
from core.api import _json, area_blocked, position_from, request_area
from core.entitlement import entitlement_for_request
from core.geo import haversine_km
from maritime import approach, tips
from maritime.ports import by_key

# Utan valt område: terminaler inom den här radien från förarens position.
RADIUS_KM = 150
# Läget delas mellan förare i så här många sekunder; appen frågar var 30:e.
SHARED_SECONDS = 15
CACHE_KEY = "maritime:approach-snapshot"
APP_STATUSES = frozenset({approach.APPROACHING, approach.DOCKING, approach.BERTHED})
ATTRIBUTION = (
    "Ankomster: GTFS Sverige 3 (Trafiklab) + AIS via AISStream.io. "
    "Passagerarantal saknas i källorna och påstås aldrig."
)


def ferries_live(request):
    """GET /api/pipeline/ferries -- stora passagerarfärjor i inseglingsområdena, se maritime/approach.py."""
    if not settings.DEBUG:
        return JsonResponse({"error": "not_found"}, status=404)
    return JsonResponse(approach.snapshot(timezone.now()), json_dumps_params={"ensure_ascii": False})


@functools.lru_cache(maxsize=64)
def _terminal_codes(key: str) -> frozenset[str]:
    port = by_key(key)
    return frozenset(areas.area_for(port.lat, port.lon, port.region or None)[1])


def _shared_snapshot() -> dict:
    snapshot = cache.get(CACHE_KEY)
    if snapshot is None:
        snapshot = approach.snapshot(timezone.now())
        cache.set(CACHE_KEY, snapshot, SHARED_SECONDS)
    return snapshot


def _terminal_key_for_arrival(item: dict, terminals: list[dict]) -> str | None:
    """Matchar relevance-radens terminal mot hamnregistret (namn eller koordinat)."""
    term = item.get("terminal") or {}
    name = (term.get("name") or "").casefold()
    lat, lon = term.get("lat"), term.get("lon")
    for t in terminals:
        if name and t["name"].casefold() == name:
            return t["key"]
        if lat is not None and lon is not None:
            if abs(t["lat"] - lat) < 0.02 and abs(t["lon"] - lon) < 0.02:
                return t["key"]
    return None


# Storleken i ord, efter fartygets längd -- samma band som tipsen (maritime/tips.py), så att
# samma färja inte heter olika i tipset och på kortet. Längden visas inte själv.
SIZE_LABELS = tuple((floor, label.capitalize()) for floor, _score, label in tips.SIZE_BANDS)
# Relevance-sorterna som inte är en storlek men säger vad det är för båt.
KIND_SIZE = {"pendulum": "Pendelfärja", "island": "Öbåt", "commuter": "Pendelbåt", "loop": "Rundtur",
             "road": "Vägfärja", "big": "Stor färja"}
ROW_STATUSES = (approach.APPROACHING, approach.DOCKING, approach.BERTHED)


def size_label(length_m, kind: str | None = None) -> str:
    for minimum, label in SIZE_LABELS:
        if length_m and length_m >= minimum:
            return label
    return KIND_SIZE.get(kind or "", "Färja")


def _ship_name(name: str | None) -> str:
    """Fartygets namn, aldrig ett MMSI-nummer i stället för ett namn."""
    name = (name or "").strip()
    return "" if not name or name.upper().startswith("MMSI") else name


def _minutes_until(iso: str | None, now) -> int | None:
    import datetime as dt

    if not iso:
        return None
    try:
        when = dt.datetime.fromisoformat(iso)
    except ValueError:
        return None
    return max(0, round((when - now).total_seconds() / 60))


def ferry_rows(ships: list[dict], arrivals: list[tuple[str, dict]], terminals: dict[str, dict], now) -> list[dict]:
    """
    En rad per färja, för både kartan och listan. `arrivals` är (terminalnyckel, ankomst)
    ur relevance.build; `ships` är AIS-fartygen för samma terminaler.
    """
    by_mmsi = {s["mmsi"]: s for s in ships}
    used: set = set()
    rows: list[dict] = []
    for key, item in arrivals:
        vessel = item.get("vessel") or {}
        mmsi = vessel.get("mmsi")
        if mmsi is None and str(item.get("id", "")).startswith("ais:"):
            try:
                mmsi = int(str(item["id"]).removeprefix("ais:"))
            except ValueError:
                mmsi = None
        ship = by_mmsi.get(mmsi)
        if ship is not None:
            used.add(mmsi)
        term = item.get("terminal") or {}
        port = terminals.get(key) or {}
        port_lat = term.get("lat", port.get("lat"))
        port_lon = term.get("lon", port.get("lon"))
        lat = (ship or vessel).get("lat")
        lon = (ship or vessel).get("lon")
        arrived = bool(item.get("arrived"))
        status = (ship or {}).get("status") or (approach.BERTHED if arrived else approach.APPROACHING)
        name = (_ship_name((ship or {}).get("name")) or _ship_name(vessel.get("name"))
                or (item.get("route") or "").strip() or "Färja")
        rows.append({
            "id": item.get("id"),
            "name": name,
            "sizeLabel": size_label(vessel.get("lengthM") or (ship or {}).get("lengthM"), item.get("kind")),
            "from": item.get("from") or "",
            "terminal": key,
            "portName": term.get("name") or port.get("name") or "",
            "portLat": port_lat,
            "portLon": port_lon,
            # Fartyget där det är; utan AIS-position står raden vid kajen.
            "lat": lat if lat is not None else port_lat,
            "lon": lon if lon is not None else port_lon,
            "live": lat is not None and lon is not None,
            "course": (ship or vessel).get("course") if lat is not None else None,
            "status": status,
            "arrived": arrived or status == approach.BERTHED,
            "expectedAt": item.get("expectedAt"),
            "etaMinutes": None if arrived else _minutes_until(item.get("expectedAt"), now),
            "pickupFrom": item.get("pickupFrom"),
            "pickupUntil": item.get("pickupUntil"),
        })
    for ship in ships:
        if ship["mmsi"] in used or ship["status"] not in ROW_STATUSES:
            continue
        port = terminals.get(ship["terminal"]) or {}
        berthed = ship["status"] == approach.BERTHED
        rows.append({
            "id": f"ais:{ship['mmsi']}",
            "name": _ship_name(ship.get("name")) or "Färja",
            "sizeLabel": size_label(ship.get("lengthM")),
            "from": "",
            "terminal": ship["terminal"],
            "portName": ship.get("terminalName") or port.get("name") or "",
            "portLat": port.get("lat"),
            "portLon": port.get("lon"),
            "lat": ship["lat"],
            "lon": ship["lon"],
            "live": True,
            "course": ship.get("course"),
            "status": ship["status"],
            "arrived": berthed,
            "expectedAt": None if berthed else ship.get("eta"),
            "etaMinutes": None if berthed else ship.get("etaMinutes"),
            "pickupFrom": None,
            "pickupUntil": None,
        })
    order = {approach.DOCKING: 0, approach.APPROACHING: 1, approach.BERTHED: 2}
    rows.sort(key=lambda r: (
        r["arrived"], r["expectedAt"] or "9999", order.get(r["status"], 3), r["name"],
    ))
    return rows


@require_GET
@gzip_page
def ferries(request):
    """
    GET /api/ferries  (X-Device-Token eller Bearer-JWT, position i X-TT-Position)

    `rows` = färjorna för kartan OCH listan. `arrivals` och `ferries` för äldre appar.
    Terminalerna i förarens län och kommuner, annars inom RADIUS_KM från positionen.
    Utan både område och position: tom lista och `needsArea`, som i tipsflödet.
    """
    ent = entitlement_for_request(request)
    if not ent.ok:
        return _json(request, {
            "rows": [], "ferries": [], "arrivals": [], "terminals": [],
            "entitled": False, "reason": ent.reason,
        })

    from fleet import features

    plan = features.of(ent)
    if not plan.allows("ferry"):
        return _json(request, {
            "rows": [], "ferries": [], "arrivals": [], "terminals": [],
            "entitled": False, "reason": features.LOCKED_REASON,
            "message": plan.locked_message, "plan": plan.plan,
        })

    lat, lon = position_from(request)
    counties, municipalities = request_area(request, lat, lon, ent)
    if area_blocked(ent, counties, municipalities):
        return _json(request, {
            "rows": [], "ferries": [], "arrivals": [], "terminals": [],
            "entitled": False, "reason": "no_entitled_county",
        })
    chosen = set(areas.device_area_codes({"counties": counties, "municipalities": municipalities}))
    snapshot = _shared_snapshot()
    if chosen:
        keep = {t["key"] for t in snapshot["terminals"] if _terminal_codes(t["key"]) & chosen}
    elif lat is not None and lon is not None:
        keep = {
            t["key"] for t in snapshot["terminals"]
            if haversine_km(lat, lon, t["lat"], t["lon"]) <= RADIUS_KM
        }
    else:
        return _json(request, {
            "rows": [], "ferries": [], "arrivals": [], "terminals": [],
            "entitled": True, "needsArea": True,
        })

    ships = [s for s in snapshot["ships"] if s["terminal"] in keep and s["status"] in APP_STATUSES]
    terminals = [
        {key: t[key] for key in ("key", "name", "lat", "lon", "tips", "approaching")}
        for t in snapshot["terminals"] if t["key"] in keep
    ]
    taxi = snapshot.get("taxi") or {}
    keyed = []
    for item in taxi.get("items") or []:
        key = _terminal_key_for_arrival(item, snapshot["terminals"])
        if key is not None and key in keep:
            keyed.append((key, item))
    arrivals = [item for _key, item in keyed]
    by_key_terminal = {t["key"]: t for t in snapshot["terminals"] if t["key"] in keep}
    now = timezone.now()

    return _json(request, {
        # Kartan och listan: samma rader (se modulens docstring).
        "rows": ferry_rows(ships, keyed, by_key_terminal, now),
        "ferries": ships,
        "arrivals": arrivals,
        "terminals": terminals,
        "entitled": True,
        "updatedAt": snapshot["generatedAt"],
        "stream": snapshot["stream"],
        "attribution": ATTRIBUTION,
        "kinds": taxi.get("kinds") or [],
    })
