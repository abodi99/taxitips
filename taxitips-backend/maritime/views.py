"""
Färjorna i appen och på pipeline-sidan.

`/api/ferries` är förarens vy: samma urval som pipeline-sidans `/farjor`
(`maritime/relevance.py`) — tidtabell + AIS, sorter och hämtningsfönster —
filtrerat till förarens område. AIS-fartygen i `ferries` finns kvar för
kartans live-nålar. `/api/pipeline/ferries` är hela snapshoten, bara med DEBUG.
"""

from __future__ import annotations

import functools

from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from core import areas
from core.api import _json, position_from, request_area
from core.entitlement import entitlement_for_request
from core.geo import haversine_km
from maritime import approach
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


@require_GET
def ferries(request):
    """
    GET /api/ferries  (X-Device-Token eller Bearer-JWT, position i X-TT-Position)

    `arrivals` = relevance.build (samma som /farjor). `ferries` = AIS-skepp för kartan.
    Terminalerna i förarens län och kommuner, annars inom RADIUS_KM från positionen.
    Utan både område och position: tom lista och `needsArea`, som i tipsflödet.
    """
    ent = entitlement_for_request(request)
    if not ent.ok:
        return _json(request, {
            "ferries": [], "arrivals": [], "terminals": [],
            "entitled": False, "reason": ent.reason,
        })

    lat, lon = position_from(request)
    counties, municipalities = request_area(request, lat, lon)
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
            "ferries": [], "arrivals": [], "terminals": [],
            "entitled": True, "needsArea": True,
        })

    ships = [s for s in snapshot["ships"] if s["terminal"] in keep and s["status"] in APP_STATUSES]
    terminals = [
        {key: t[key] for key in ("key", "name", "lat", "lon", "tips", "approaching")}
        for t in snapshot["terminals"] if t["key"] in keep
    ]
    taxi = snapshot.get("taxi") or {}
    arrivals = []
    for item in taxi.get("items") or []:
        key = _terminal_key_for_arrival(item, snapshot["terminals"])
        if key is not None and key in keep:
            arrivals.append(item)

    return _json(request, {
        "ferries": ships,
        "arrivals": arrivals,
        "terminals": terminals,
        "entitled": True,
        "updatedAt": snapshot["generatedAt"],
        "stream": snapshot["stream"],
        "attribution": ATTRIBUTION,
        "kinds": taxi.get("kinds") or [],
    })
