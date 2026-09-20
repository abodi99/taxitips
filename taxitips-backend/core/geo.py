"""
Trafikplatser / stationer där taxi-affär uppstår.

Port av worker/src/hubs.js, rad för rad. Ren data + funktioner, ingen I/O,
inga Django-beroenden -- samma skäl som i originalet: kartan och "nära mig"
behöver koordinater (WGS84) för hubbar och städer utan egen station.
"""

from __future__ import annotations

import math
import re

HUBS: list[dict] = [
    {
        "id": "malmo-c", "name": "Malmö C",
        "aliases": ["malmö c", "malmö central", "malmo c", "malmo central", "malmö centralstation"],
        "city": "Malmö", "lat": 55.6092, "lon": 13.0007, "radius_km": 1.2, "weight": 28,
    },
    {
        "id": "triangeln", "name": "Triangeln",
        "aliases": ["triangeln", "triangelns", "malmö triangeln"],
        "city": "Malmö", "lat": 55.5915, "lon": 13.0009, "radius_km": 0.9, "weight": 22,
    },
    {
        "id": "hyllie", "name": "Hyllie",
        "aliases": ["hyllie", "hyllie station", "malmö arena"],
        "city": "Malmö", "lat": 55.5627, "lon": 12.9756, "radius_km": 1.5, "weight": 26,
    },
    {
        "id": "lund-c", "name": "Lund C",
        "aliases": ["lund c", "lund central", "lund centralstation"],
        "city": "Lund", "lat": 55.7058, "lon": 13.187, "radius_km": 1.1, "weight": 26,
    },
    {
        "id": "helsingborg-c", "name": "Helsingborg C",
        "aliases": ["helsingborg c", "helsingborg central", "helsingborg centralstation", "knutpunkten"],
        "city": "Helsingborg", "lat": 56.0442, "lon": 12.6945, "radius_km": 1.2, "weight": 26,
    },
    {
        "id": "kristianstad-c", "name": "Kristianstad C",
        "aliases": ["kristianstad c", "kristianstad central", "kristianstad"],
        "city": "Kristianstad", "lat": 56.0294, "lon": 14.1567, "radius_km": 1.2, "weight": 20,
    },
    {
        "id": "hassleholm-c", "name": "Hässleholm C",
        "aliases": ["hässleholm c", "hässleholm central", "hässleholm", "hassleholm"],
        "city": "Hässleholm", "lat": 56.1578, "lon": 13.7664, "radius_km": 1.1, "weight": 20,
    },
    {
        "id": "landskrona", "name": "Landskrona",
        "aliases": ["landskrona", "landskrona station"],
        "city": "Landskrona", "lat": 55.8705, "lon": 12.8302, "radius_km": 1.2, "weight": 18,
    },
    {
        "id": "angelholm", "name": "Ängelholm",
        "aliases": ["ängelholm", "angelholm", "ängelholm station"],
        "city": "Ängelholm", "lat": 56.2465, "lon": 12.8634, "radius_km": 1.1, "weight": 16,
    },
    {
        "id": "ystad", "name": "Ystad",
        "aliases": ["ystad", "ystad station"],
        "city": "Ystad", "lat": 55.4295, "lon": 13.8204, "radius_km": 1.1, "weight": 16,
    },
    {
        "id": "trelleborg", "name": "Trelleborg",
        "aliases": ["trelleborg", "trelleborg central"],
        "city": "Trelleborg", "lat": 55.3752, "lon": 13.1569, "radius_km": 1.1, "weight": 16,
    },
    {
        "id": "eslov", "name": "Eslöv",
        "aliases": ["eslöv", "eslov"],
        "city": "Eslöv", "lat": 55.8392, "lon": 13.3039, "radius_km": 1.0, "weight": 14,
    },
    {
        "id": "cph-airport", "name": "Köpenhamns flygplats",
        "aliases": ["köpenhamns flygplats", "copenhagen airport", "cph airport", "kastrup", "cph"],
        "city": "Kastrup", "lat": 55.618, "lon": 12.656, "radius_km": 2.5, "weight": 24,
    },
]

# Städer utan specifik station -- centrum för karta.
CITY_COORDS: dict[str, tuple[float, float]] = {
    "Malmö": (55.605, 13.0038),
    "Lund": (55.7047, 13.191),
    "Helsingborg": (56.0465, 12.6945),
    "Kristianstad": (56.0294, 14.1567),
    "Hässleholm": (56.1589, 13.7664),
    "Landskrona": (55.8705, 12.8302),
    "Trelleborg": (55.3752, 13.1569),
    "Ystad": (55.4295, 13.8204),
    "Eslöv": (55.8392, 13.3039),
    "Höör": (55.9344, 13.5422),
    "Ängelholm": (56.2428, 12.8622),
    "Simrishamn": (55.5566, 14.3503),
    "Staffanstorp": (55.6425, 13.2075),
    "Svedala": (55.5075, 13.234),
    "Kävlinge": (55.792, 13.1102),
    "Lomma": (55.6726, 13.069),
    "Vellinge": (55.4636, 13.0197),
    "Markaryd": (56.4615, 13.5964),
    "Bromölla": (56.0754, 14.4695),
    "Höganäs": (56.1997, 12.557),
    "Halmstad": (56.6745, 12.857),
    "Karlskrona": (56.1612, 15.5869),
    "Växjö": (56.8777, 14.8091),
    "Älmhult": (56.5515, 14.1362),
    # National rollout. Trafiklab's alerts carry stop_ids we cannot resolve
    # (different id space -- see docs/data-sources.md), so a place name in
    # the free text is the ONLY way most alerts get a coordinate. City
    # centres, not stations: precise enough to tell a driver which town,
    # honest about not knowing which platform.
    "Stockholm": (59.3293, 18.0686),
    "Solna": (59.36, 18.0),
    "Södertälje": (59.1955, 17.6252),
    "Nacka": (59.3105, 18.1637),
    "Sundbyberg": (59.3612, 17.9713),
    "Täby": (59.4439, 18.0687),
    "Norrtälje": (59.7574, 18.7053),
    "Uppsala": (59.8586, 17.6389),
    "Enköping": (59.6358, 17.0776),
    "Göteborg": (57.7089, 11.9746),
    "Mölndal": (57.6554, 12.0134),
    "Kungsbacka": (57.4874, 12.0761),
    "Borås": (57.721, 12.9401),
    "Trollhättan": (58.2837, 12.2886),
    "Uddevalla": (58.3498, 11.9424),
    "Skövde": (58.3912, 13.8452),
    "Linköping": (58.4109, 15.6216),
    "Norrköping": (58.5877, 16.1924),
    "Motala": (58.5371, 15.0364),
    "Jönköping": (57.7826, 14.1618),
    "Nässjö": (57.6531, 14.6963),
    "Värnamo": (57.1866, 14.0416),
    "Kalmar": (56.6634, 16.3566),
    "Oskarshamn": (57.2646, 16.4487),
    "Västervik": (57.7577, 16.6373),
    "Nybro": (56.7444, 15.9083),
    "Karlstad": (59.3793, 13.5036),
    "Kristinehamn": (59.3097, 14.1073),
    "Arvika": (59.6547, 12.5911),
    "Örebro": (59.2741, 15.2066),
    "Karlskoga": (59.3266, 14.5241),
    "Västerås": (59.6099, 16.5448),
    "Köping": (59.5133, 15.9927),
    "Eskilstuna": (59.3717, 16.5098),
    "Nyköping": (58.7531, 17.0086),
    "Falun": (60.6065, 15.6355),
    "Borlänge": (60.4858, 15.4371),
    "Mora": (61.0055, 14.5378),
    "Gävle": (60.6749, 17.1413),
    "Sandviken": (60.6172, 16.7759),
    "Hudiksvall": (61.7288, 17.1058),
    "Sundsvall": (62.3908, 17.3069),
    "Härnösand": (62.6323, 17.9379),
    "Örnsköldsvik": (63.29, 18.7156),
    "Östersund": (63.1792, 14.6357),
    "Umeå": (63.8258, 20.263),
    "Skellefteå": (64.7507, 20.9528),
    "Luleå": (65.5848, 22.1547),
    "Piteå": (65.3172, 21.4794),
    "Kiruna": (67.8558, 20.2253),
    "Visby": (57.6348, 18.2948),
    "Karlshamn": (56.1706, 14.8626),
    "Varberg": (57.1057, 12.2508),
}

_CITY_COORDS_LOWER = {name.lower(): name for name in CITY_COORDS}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    to_rad = math.radians
    r = 6371
    d_lat = to_rad(lat2 - lat1)
    d_lon = to_rad(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(to_rad(lat1)) * math.cos(to_rad(lat2)) * math.sin(d_lon / 2) ** 2
    )
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_hubs_in_text(text: str | None) -> list[dict]:
    t = str(text or "").lower()
    return [hub for hub in HUBS if any(alias in t for alias in hub["aliases"])]


def resolve_place_coords(name: str | None) -> dict | None:
    if not name:
        return None
    key = str(name).strip()
    lower = key.lower()

    for hub in HUBS:
        if hub["name"].lower() == lower or lower in hub["aliases"] or hub["city"].lower() == lower:
            return {
                "name": hub["name"], "lat": hub["lat"], "lon": hub["lon"],
                "hub_id": hub["id"], "is_hub": True,
                "city": hub["city"], "radius_km": hub["radius_km"],
            }

    city_name = key if key in CITY_COORDS else _CITY_COORDS_LOWER.get(lower)
    if city_name:
        lat, lon = CITY_COORDS[city_name]
        return {
            "name": key, "lat": lat, "lon": lon, "hub_id": None,
            "is_hub": False, "city": key, "radius_km": 3,
        }
    return None


_ROAD_NUMBER_RE = re.compile(r"^E\d", re.IGNORECASE)
_VAG_RE = re.compile(r"^väg\s", re.IGNORECASE)
_RV_RE = re.compile(r"^rv\s?\d", re.IGNORECASE)


def enrich_place_stats(place_stats: list[dict] | None = None) -> list[dict]:
    """Kartan ska visa orter/stationer -- inte vägnr som E4 / Väg 123."""
    out = []
    for p in place_stats or []:
        name = str(p.get("name") or "")
        if _ROAD_NUMBER_RE.match(name) or _VAG_RE.match(name) or _RV_RE.match(name):
            continue
        geo = resolve_place_coords(p.get("name"))
        out.append({
            **p,
            "lat": geo["lat"] if geo else None,
            "lon": geo["lon"] if geo else None,
            "is_hub": bool(geo and geo["is_hub"]),
            "hub_id": geo["hub_id"] if geo else None,
            "radius_km": geo["radius_km"] if geo else 3,
        })
    return out


# Which existing CITY_COORDS entry anchors an alert whose region we know
# but whose text names no resolvable place at all. Not new coordinates --
# just naming which city already in this file stands in for each region
# code, the same list Node uses for TRAFIKLAB_OPERATORS/national rollout.
REGION_ANCHOR: dict[str, str] = {
    "skane": "Malmö", "sl": "Stockholm", "vt": "Göteborg", "ul": "Uppsala",
    "otraf": "Linköping", "klt": "Kalmar", "varm": "Karlstad", "dt": "Falun",
    "xt": "Gävle", "vastmanland": "Västerås", "krono": "Växjö", "jlt": "Jönköping",
    "orebro": "Örebro", "blekinge": "Karlskrona", "gotland": "Visby",
}

# Orter man kan välja under notisinställningarna, per län. Ankarpunkten
# från REGION_ANCHOR ingår alltid; övriga är städer som faktiskt förekommer
# i CITY_COORDS / HUBS för det länet. Push-filtret (core/notify.py) matchar
# dem som delsträng mot opportunity.places -- tom lista = hela länet.
REGION_CITIES: dict[str, list[str]] = {
    "skane": [
        "Malmö", "Lund", "Helsingborg", "Kristianstad", "Hässleholm",
        "Landskrona", "Trelleborg", "Ystad", "Ängelholm", "Höör", "Eslöv",
        "Kävlinge", "Staffanstorp", "Svedala", "Vellinge", "Lomma",
        "Simrishamn", "Höganäs", "Bromölla",
    ],
    "sl": [
        "Stockholm", "Solna", "Södertälje", "Nacka", "Sundbyberg", "Täby",
        "Norrtälje",
    ],
    "vt": [
        "Göteborg", "Mölndal", "Kungsbacka", "Borås", "Trollhättan",
        "Uddevalla", "Skövde",
    ],
    "ul": ["Uppsala", "Enköping"],
    "otraf": ["Linköping", "Norrköping", "Motala"],
    "jlt": ["Jönköping", "Nässjö"],
    "krono": ["Växjö", "Älmhult", "Markaryd"],
    # Ronneby för flygplatsens skull: utan orten i listan filtrerade
    # ortsvalet i notisinställningarna tyst bort varje flygtips från
    # Ronneby Airport för alla Blekingeförare.
    "blekinge": ["Karlskrona", "Ronneby"],
    "klt": ["Kalmar"],
    "varm": ["Karlstad"],
    "dt": ["Falun"],
    "xt": ["Gävle"],
    "vastmanland": ["Västerås"],
    "orebro": ["Örebro"],
    "gotland": ["Visby"],
}

# Stop-name gazetteer (tier 3): loaded once per process from the StopArea
# table (core.models), keyed lowercase -> {lat, lon}. Held in memory because
# resolve_coords runs per alert (hundreds per cycle) and the register
# changes on a daily cadence at most -- mirrors poller.js's
# stopNameGazetteer singleton.
_gazetteer_cache: dict[str, dict] | None = None


def _load_gazetteer() -> dict[str, dict]:
    global _gazetteer_cache
    if _gazetteer_cache is not None:
        return _gazetteer_cache

    from core.models import StopArea  # deferred: keeps this module importable pre-Django-setup

    gaz: dict[str, dict] = {}
    try:
        for name, lat, lon in StopArea.objects.values_list("name", "lat", "lon"):
            if not name or len(name) < 5:
                continue
            key = name.lower()
            if key not in gaz:
                gaz[key] = {"lat": lat, "lon": lon}
    except Exception:
        pass  # ingestion infrastructure missing/unmigrated -- degrade, don't crash
    _gazetteer_cache = gaz
    return gaz


def resolve_coords(alert: dict, taxi: dict) -> tuple[float | None, float | None, str]:
    """
    Port of poller.js's resolveCoords, extended with two more tiers.
    Returns (lat, lon, precision) so callers can be honest about how a
    point was placed -- "exact"/"place"/"gazetteer" are all real, named
    locations; "region" is a city-centre stand-in for "somewhere in this
    market", never a fabricated street-level coordinate; "none" is no
    coordinate at all.
    """
    lat = alert.get("lat", taxi.get("lat"))
    lon = alert.get("lon", taxi.get("lon"))
    if lat is not None and lon is not None:
        return lat, lon, "exact"

    place_names = [*(taxi.get("hubs") or []), *(taxi.get("places") or []), *(alert.get("places") or [])]
    for name in place_names:
        geo = resolve_place_coords(name)
        if geo:
            return geo["lat"], geo["lon"], "place"

    # Tier 3: individual stop names ("Elektravägen", "Hässelby strand")
    # that no city/hub list can ever cover. Longest match wins so
    # "Hässelby strand" beats "Hässelby"; names <5 chars are excluded at
    # load time since short ones match inside unrelated words.
    gaz = _load_gazetteer()
    if gaz:
        text = f"{alert.get('header') or ''} {alert.get('description') or ''}".lower()
        best_name = None
        for name, coord in gaz.items():
            if name in text and (best_name is None or len(name) > len(best_name)):
                best_name, best_coord = name, coord
        if best_name:
            return best_coord["lat"], best_coord["lon"], "gazetteer"

    # Tier 4 (not in Node): a known region with no resolvable place still
    # gets a city-centre pin, so real volume is visible on the map instead
    # of silently vanishing. Callers must label this in `reasons` --
    # this function only reports the precision, it doesn't decide how the
    # UI presents it.
    region = str(alert.get("region") or "").lower()
    anchor_city = REGION_ANCHOR.get(region)
    if anchor_city:
        geo = resolve_place_coords(anchor_city)
        if geo:
            return geo["lat"], geo["lon"], "region"

    return None, None, "none"


def distance_to_place_km(lat: float | None, lon: float | None, place_name: str | None) -> float | None:
    geo = resolve_place_coords(place_name)
    if not geo or lat is None or lon is None:
        return None
    return haversine_km(lat, lon, geo["lat"], geo["lon"])


def filter_places_by_distance(
    place_stats: list[dict], lat: float | None = None, lon: float | None = None, max_km: float = 25
) -> list[dict]:
    if lat is None or lon is None:
        return place_stats

    def with_distance(p: dict) -> dict:
        if p.get("lat") is not None:
            d = haversine_km(lat, lon, p["lat"], p["lon"])
        else:
            d = distance_to_place_km(lat, lon, p.get("name"))
        return {**p, "distance_km": None if d is None else round(d, 1)}

    out = [with_distance(p) for p in place_stats]
    out = [p for p in out if p["distance_km"] is None or p["distance_km"] <= max_km]
    out.sort(key=lambda p: p["distance_km"] if p["distance_km"] is not None else 999)
    return out
