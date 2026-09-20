"""
Körområden utan GPS: Sveriges 21 län och 290 kommuner, och vilka av dem ett tips hör till.

Föraren väljer län (SCB:s länskod) och kan förfina med kommuner (SCB:s kommunkod) i
stället för att dela sin position. Tipsets län och kommun räknas ur koordinaten mot
gränserna i core/data/se_counties.geojson och se_municipalities.geojson (SCB Digitala
gränser, CC0 -- se ops/geo/build_areas_scb.py). SCB kallar gränserna förenklade för
tematisk presentation; buffertarna nedan gör det robust.

`area_codes` på ett tips bär båda nivåerna i samma lista: länskoder (två siffror) för
länet och grannlän inom AREA_BUFFER_KM, kommunkoder (fyra siffror) för kommunen och
grannkommuner inom MUNICIPALITY_BUFFER_KM. Förarens körområde (device_area_codes) är
samma sorts lista, så matchningen är en snittmängd -- i Python och i SQL.

* AREA_BUFFER_KM: Arlanda ligger i Stockholms län några kilometer från Uppsala län,
  och en förare i Uppsala kör dit; länsgränsen är inte en linje någon kör efter.
* MUNICIPALITY_BUFFER_KM: samma sak mellan kommuner, men snävare -- den som valt en
  kommun har valt bort resten av länet.
* COAST_SNAP_KM: färjelägen och skärgård kan hamna strax utanför en förenklad kustlinje.

Marknadsnycklarna (sl, vt, skane, ...) är fortfarande källornas interna indelning.
MARKET_COUNTY översätter dem för tips utan koordinat och för äldre notisinställningar.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).parent / "data"
COUNTY_DATA = DATA / "se_counties.geojson"
MUNICIPALITY_DATA = DATA / "se_municipalities.geojson"

AREA_BUFFER_KM = 25.0
MUNICIPALITY_BUFFER_KM = 10.0
COAST_SNAP_KM = 15.0

# SCB:s länskoder, i SCB:s ordning.
COUNTIES: list[tuple[str, str]] = [
    ("01", "Stockholms län"),
    ("03", "Uppsala län"),
    ("04", "Södermanlands län"),
    ("05", "Östergötlands län"),
    ("06", "Jönköpings län"),
    ("07", "Kronobergs län"),
    ("08", "Kalmar län"),
    ("09", "Gotlands län"),
    ("10", "Blekinge län"),
    ("12", "Skåne län"),
    ("13", "Hallands län"),
    ("14", "Västra Götalands län"),
    ("17", "Värmlands län"),
    ("18", "Örebro län"),
    ("19", "Västmanlands län"),
    ("20", "Dalarnas län"),
    ("21", "Gävleborgs län"),
    ("22", "Västernorrlands län"),
    ("23", "Jämtlands län"),
    ("24", "Västerbottens län"),
    ("25", "Norrbottens län"),
]
COUNTY_NAMES = dict(COUNTIES)

# Källornas marknadsnycklar -> län. Samma operatörer som core/coverage.COUNTIES.
# "rail" och "trafikverket" saknas med avsikt: de är hela landet, och ett sådant tips
# placeras bara av sin koordinat.
MARKET_COUNTY: dict[str, str] = {
    "sl": "01", "ul": "03", "otraf": "05", "jlt": "06", "krono": "07",
    "klt": "08", "gotland": "09", "blekinge": "10", "skane": "12", "vt": "14",
    "varm": "17", "orebro": "18", "vastmanland": "19", "dt": "20", "xt": "21",
    "dintur": "22",
}


def _load(path: Path) -> list[tuple[str, dict, tuple[float, float, float, float], list]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    shapes = []
    for feature in data["features"]:
        polygons = feature["geometry"]["coordinates"]
        outer = [point for polygon in polygons for point in polygon[0]]
        bbox = (
            min(p[0] for p in outer), min(p[1] for p in outer),
            max(p[0] for p in outer), max(p[1] for p in outer),
        )
        shapes.append((feature["properties"]["code"], feature["properties"], bbox, polygons))
    return shapes


@lru_cache(maxsize=1)
def _counties() -> list:
    return _load(COUNTY_DATA)


@lru_cache(maxsize=1)
def _municipalities() -> list:
    return _load(MUNICIPALITY_DATA)


@lru_cache(maxsize=512)
def municipality_point(name: str) -> tuple[float, float] | None:
    """
    En punkt i kommunen med det namnet (lat, lon): medelpunkten av största delytans ytterkant,
    eller ramens mitt om den hamnar utanför. None när namnet inte är en kommun. Grov -- för att
    placera något i rätt kommun och län, inte på kartan ner till gatan.
    """
    wanted = (name or "").strip().lower()
    for _code, props, bbox, polygons in _municipalities():
        if props["name"].lower() != wanted:
            continue
        ring = max((polygon[0] for polygon in polygons), key=len)
        lon = sum(p[0] for p in ring) / len(ring)
        lat = sum(p[1] for p in ring) / len(ring)
        if not _contains(lon, lat, polygons):
            lon, lat = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        return round(lat, 5), round(lon, 5)
    return None


@lru_cache(maxsize=1)
def municipality_names() -> dict[str, str]:
    return {code: props["name"] for code, props, _bbox, _polygons in _municipalities()}


def _in_ring(lon: float, lat: float, ring: list) -> bool:
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if (yi > lat) != (yj > lat) and lon < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def _contains(lon: float, lat: float, polygons: list) -> bool:
    return any(
        _in_ring(lon, lat, polygon[0]) and not any(_in_ring(lon, lat, hole) for hole in polygon[1:])
        for polygon in polygons
    )


def _distance_km(lat: float, lon: float, polygons: list) -> float:
    """Kortaste avstånd till områdets kant. Plan approximation -- rätt på den här skalan."""
    kx = 111.32 * math.cos(math.radians(lat))
    ky = 110.57
    best = math.inf
    for polygon in polygons:
        for ring in polygon:
            for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
                ax, ay = (x1 - lon) * kx, (y1 - lat) * ky
                dx, dy = (x2 - x1) * kx, (y2 - y1) * ky
                length = dx * dx + dy * dy
                t = 0.0 if length == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / length))
                best = min(best, math.hypot(ax + t * dx, ay + t * dy))
    return best


def _near_bbox(lat: float, lon: float, bbox: tuple, km: float) -> bool:
    pad_lat = km / 110.57
    pad_lon = km / (111.32 * math.cos(math.radians(lat)))
    return bbox[0] - pad_lon <= lon <= bbox[2] + pad_lon and bbox[1] - pad_lat <= lat <= bbox[3] + pad_lat


def _nearby(lat: float, lon: float, shapes: list, buffer_km: float) -> tuple[str | None, set[str]]:
    """(området punkten ligger i, eller närmaste inom COAST_SNAP_KM; områden inom bufferten)."""
    inside = None
    distances: dict[str, float] = {}
    for code, _props, bbox, polygons in shapes:
        if not _near_bbox(lat, lon, bbox, max(buffer_km, COAST_SNAP_KM)):
            continue
        if inside is None and _contains(lon, lat, polygons):
            inside = code
            distances[code] = 0.0
            continue
        distances[code] = _distance_km(lat, lon, polygons)
    if inside is None and distances:
        nearest = min(distances, key=distances.get)
        if distances[nearest] <= COAST_SNAP_KM:
            inside = nearest
    nearby = {code for code, km in distances.items() if km <= buffer_km}
    if inside is not None:
        nearby.add(inside)
    return inside, nearby


@lru_cache(maxsize=50_000)
def _place_at(lat: float, lon: float) -> tuple[str | None, str | None, tuple[str, ...]]:
    municipality, near_municipalities = _nearby(lat, lon, _municipalities(), MUNICIPALITY_BUFFER_KM)
    county_inside, near_counties = _nearby(lat, lon, _counties(), AREA_BUFFER_KM)
    # Kommunens kod börjar med länets: länet följer kommunen, så att de två aldrig
    # hamnar på olika sidor om samma gräns.
    county = municipality[:2] if municipality else county_inside
    if county is None:
        return None, None, ()
    codes = near_counties | {county} | near_municipalities
    return county, municipality, tuple(sorted(codes))


def place_for(lat: float | None, lon: float | None, region: str | None = None) -> tuple[str | None, str | None, list[str]]:
    """
    (län, kommun, area_codes) för ett tips.

    Koordinaten avgör när den finns. Annars marknadsnyckeln, som bara ger länet; utan
    någon av dem går tipset inte att placera, och (None, None, []) är det ärliga svaret.
    """
    if lat is not None and lon is not None:
        # Avrundat till ungefär hundra meter: samma hållplats ger samma svar ur cachen
        # varje pollrunda, och gränserna är ändå förenklade.
        county, municipality, codes = _place_at(round(float(lat), 3), round(float(lon), 3))
        if county is not None:
            return county, municipality, list(codes)
    county = MARKET_COUNTY.get(str(region or ""))
    return (county, None, [county]) if county else (None, None, [])


def area_for(lat: float | None, lon: float | None, region: str | None = None) -> tuple[str | None, list[str]]:
    """(län, area_codes) -- se place_for."""
    county, _municipality, codes = place_for(lat, lon, region)
    return county, codes


def device_counties(prefs: dict | None) -> list[str]:
    """
    Förarens valda län. Sparade `counties` gäller; saknas de översätts äldre
    marknadsval (`regions`), så att en förare som valt "Skåne" före länen fortfarande
    har ett körområde. Tom lista = inget körområde valt.
    """
    prefs = prefs if isinstance(prefs, dict) else {}
    counties = prefs.get("counties")
    if isinstance(counties, list) and counties:
        return sorted({str(c) for c in counties if str(c) in COUNTY_NAMES})
    regions = prefs.get("regions") if isinstance(prefs.get("regions"), list) else []
    return sorted({MARKET_COUNTY[str(r)] for r in regions if str(r) in MARKET_COUNTY})


def device_municipalities(prefs: dict | None) -> list[str]:
    prefs = prefs if isinstance(prefs, dict) else {}
    chosen = prefs.get("municipalities") if isinstance(prefs.get("municipalities"), list) else []
    names = municipality_names()
    return sorted({str(m) for m in chosen if str(m) in names})


def device_area_codes(prefs: dict | None) -> list[str]:
    """
    Förarens körområde som koder att snitta mot tipsets area_codes.

    Valda kommuner ersätter sitt läns kod: den som valt Solna i Stockholms län har valt
    bort resten av länet. Ett län utan valda kommuner gäller i sin helhet. Tom lista =
    inget körområde.
    """
    municipalities = device_municipalities(prefs)
    refined = {code[:2] for code in municipalities}
    counties = [county for county in device_counties(prefs) if county not in refined]
    return sorted(set(counties) | set(municipalities))


def county_catalog() -> list[dict]:
    return [{"code": code, "name": name} for code, name in COUNTIES]


def municipality_catalog() -> dict[str, list[dict]]:
    """Kommunerna per län, i namnordning -- det appen visar under ett valt län."""
    by_county: dict[str, list[dict]] = {code: [] for code, _name in COUNTIES}
    for code, props, _bbox, _polygons in _municipalities():
        by_county.setdefault(code[:2], []).append({"code": code, "name": props["name"]})
    return {county: sorted(rows, key=lambda r: r["name"]) for county, rows in by_county.items()}
