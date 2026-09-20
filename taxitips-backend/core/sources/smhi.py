"""
SMHI:s punktprognos -- vädret som förstärkning av en redan relevant störning.

Port av worker/src/smhi.js. Trösklarna nedan är EXAKT Nodes tal; de är det
enda i den här modulen som får ändras medvetet, inte av misstag.

Två skillnader mot Node, båda avsiktliga:

1. **Punkterna är nationella.** Node har sju hårdkodade Skåne-punkter kvar
   sedan före den nationella utrullningen, vilket gör att ett Stockholmslarm
   får Hässleholms väder. Här härleds punkterna ur core/geo.py:s REGION_ANCHOR
   + CITY_COORDS, så varje marknad får sitt eget väder.
2. **haversine_km återanvänds** från core/geo.py i stället för en egen kopia.

Vädret skapar ALDRIG en signal av sig självt -- det höjer bara en störning som
redan är relevant. Bonusen appliceras i core/ingest.py, efter klassificeringen,
eftersom den behöver den tak-begränsade poängen och en koordinat.
"""

from __future__ import annotations

import logging

import requests

from core.geo import CITY_COORDS, REGION_ANCHOR, haversine_km
from core.market import configured_regions, is_national_scope
from core.time_limits import reraise_time_limit

log = logging.getLogger(__name__)

# Kategorin snow1g ersatte pmp3g 2026-03-31. Nyckelfri, en GET per punkt.
_URL = (
    "https://opendata-download-metfcst.smhi.se/api/category/snow1g/version/1"
    "/geotype/point/lon/{lon}/lat/{lat}/data.json"
)

# Trösklarna, ordagrant från smhi.js:114-121. Defaultvärdena är
# betydelsebärande: saknad temperatur betyder ALDRIG halka (99), allt annat
# saknat betyder 0. Byvind går före medelvind.
PRECIP_MM_H = 1.0
PRECIP_PROBABILITY_PCT = 40
WIND_MS = 12
THUNDER_PROBABILITY_PCT = 30
FREEZING_C = 0
FROZEN_PROBABILITY_PCT = 40

_PARAMS = {
    "air_temperature": "temperature_c",
    "wind_speed": "wind_speed_ms",
    "wind_speed_of_gust": "wind_gust_ms",
    "precipitation_amount_mean": "precipitation_mm_h",
    "probability_of_precipitation": "precipitation_probability_pct",
    "thunderstorm_probability": "thunderstorm_probability_pct",
    "probability_of_frozen_precipitation": "frozen_probability_pct",
    "symbol_code": "symbol_code",
}


def weather_points() -> list[dict]:
    """
    En punkt per marknad i scope. Nationellt scope ger alla 15; annars bara
    de konfigurerade regionerna -- ingen anledning att fråga SMHI om väder i
    län vi ändå inte hämtar störningar från.
    """
    regions = REGION_ANCHOR.keys() if is_national_scope() else configured_regions()
    points = []
    for region in regions:
        city = REGION_ANCHOR.get(region)
        coords = CITY_COORDS.get(city or "")
        if not coords:
            continue
        points.append({"point": city, "region": region, "lat": coords[0], "lon": coords[1]})
    return points


def fetch_point_forecast(lat: float, lon: float) -> dict | None:
    res = requests.get(
        _URL.format(lat=lat, lon=lon),
        headers={"Accept": "application/json"},
        timeout=15,
    )
    if not res.ok:
        raise RuntimeError(f"SMHI {res.status_code} för ({lat},{lon})")
    return res.json()


def summarize(raw: dict, point: dict) -> dict | None:
    """
    Bara timeSeries[0] -- den aktuella/närmaste timmen, som Node.

    OBS formen: snow1g lägger värdena i en PLATT `data`-dict och kallar
    tidsfältet `time`. Det är inte den äldre pmp3g-formen med en
    `parameters`-lista av {name, values: [...]}, som är den man hittar i de
    flesta exempel på nätet -- verifierat mot ett riktigt svar.
    """
    series = (raw or {}).get("timeSeries") or []
    if not series:
        return None
    entry = series[0]
    values = entry.get("data") or {}
    out = {
        "point": point["point"],
        "region": point["region"],
        "lat": point["lat"],
        "lon": point["lon"],
        "observed_at": entry.get("time"),
    }
    for smhi_name, our_name in _PARAMS.items():
        out[our_name] = values.get(smhi_name)
    return out


def fetch_region_weather() -> list[dict]:
    """En punkt i taget, fel per punkt loggas och hoppas över -- aldrig fatalt."""
    out = []
    for point in weather_points():
        try:
            raw = fetch_point_forecast(point["lat"], point["lon"])
            summary = summarize(raw, point)
            if summary:
                out.append(summary)
        except Exception as exc:
            reraise_time_limit(exc)
            log.warning("smhi: %s misslyckades: %s", point["point"], exc)
    return out


# Prognosen har timupplösning, och fyra pollare delar inte cykel i Celery som
# de gjorde i Nodes enda loop. Utan cache hade varje 90-sekunderscykel gett
# fyra rundor à 15 punkter -- 60 anrop för data som inte hunnit ändras. Samma
# mönster som geo.py:s gazetteer-cache och Nodes 1h-cachade hållplatsindex.
CACHE_TTL_SECONDS = 30 * 60
_cache: list[dict] = []
_cached_at = 0.0


def cached_region_weather() -> list[dict]:
    global _cache, _cached_at
    import time

    if _cache and (time.monotonic() - _cached_at) < CACHE_TTL_SECONDS:
        return _cache

    # Vädret hämtas inte av ett eget poll-kommando utan inifrån de andra --
    # men det gör det inte mindre viktigt att veta om SMHI slutat svara.
    # Utan raden stod källan som "okänd" i pipelinevyn för att ingen någonsin
    # skrivit ett utfall för den. Se core/health.py.
    from core.health import polling

    with polling("smhi") as status:
        fetched = fetch_region_weather()
        status.events = len(fetched or [])
        if not fetched:
            status.note = "SMHI svarade utan data — förra rundans väder behålls"
        # Behåll förra rundan om SMHI är nere -- gammalt väder är bättre än
        # inget, och bonusen är ändå bara en förstärkning.
        if fetched:
            _cache = fetched
            _cached_at = time.monotonic()
    return _cache


def nearest_weather(lat: float | None, lon: float | None, region_weather: list[dict]) -> dict | None:
    if lat is None or lon is None or not region_weather:
        return None
    return min(region_weather, key=lambda w: haversine_km(lat, lon, w["lat"], w["lon"]))


def _heavy_precipitation(w: dict) -> bool:
    return (w.get("precipitation_mm_h") or 0) >= PRECIP_MM_H and (
        w.get("precipitation_probability_pct") or 0
    ) >= PRECIP_PROBABILITY_PCT


def _high_wind(w: dict) -> bool:
    gust = w.get("wind_gust_ms")
    speed = gust if gust is not None else w.get("wind_speed_ms")
    return (speed or 0) >= WIND_MS


def _thunder(w: dict) -> bool:
    return (w.get("thunderstorm_probability_pct") or 0) >= THUNDER_PROBABILITY_PCT


def _freezing(w: dict) -> bool:
    temp = w.get("temperature_c")
    # Saknad temperatur = 99, dvs aldrig halka. Samma default som Node.
    temp = 99 if temp is None else temp
    return temp <= FREEZING_C and (w.get("frozen_probability_pct") or 0) >= FROZEN_PROBABILITY_PCT


def is_adverse_weather(weather: dict | None) -> bool:
    if not weather:
        return False
    return (
        _heavy_precipitation(weather)
        or _high_wind(weather)
        or _thunder(weather)
        or _freezing(weather)
    )


def describe_weather(weather: dict | None) -> str | None:
    """Samma svenska vokabulär som Node: motiveringen syns för föraren."""
    if not weather:
        return None
    bits = []
    if _heavy_precipitation(weather):
        bits.append(
            "snöfall"
            if (weather.get("frozen_probability_pct") or 0) >= FROZEN_PROBABILITY_PCT
            else "regn"
        )
    if _high_wind(weather):
        bits.append("hård vind")
    if _thunder(weather):
        bits.append("åska")
    if _freezing(weather):
        bits.append("halka/kyla")
    return ", ".join(bits) or None
