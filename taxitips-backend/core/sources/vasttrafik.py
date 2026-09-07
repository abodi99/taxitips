"""
Västtrafik (Göteborg) trafiksituationer -> den delade normaliserade alert-formen.

Port av worker/src/vasttrafik.js. Göteborg (~1,7 miljoner i regionen) är
Sveriges andra stad och ett hårt hål i produkten: Trafiklab har statisk data
för Västtrafik men ingen realtid, så operatörens egen portal är enda vägen
till levande störningar där.

Till skillnad från SL kräver detta autentisering: OAuth2 client-credentials
mot ext-api.vasttrafik.se, och applikationen måste vara PRENUMERERAD på varje
API separat i utvecklarportalen. Ett giltigt nyckelpar som saknar
prenumeration mintar ändå en token -- den ger bara 403 på varje anrop, med
`scope: default`. Det är tecknet på en saknad prenumeration, inte en trasig
hemlighet -- se authed_get.
"""

from __future__ import annotations

import base64
import math
import time
from datetime import datetime, timedelta, timezone as dt_timezone

import requests

TOKEN_URL = "https://ext-api.vasttrafik.se/token"
SITUATIONS_URL = "https://ext-api.vasttrafik.se/ts/v1/traffic-situations"
# includeGeometry=true krävs: utan den kommer varje hållplatsområde tillbaka
# med geometry: null (verifierat mot live-registret -- 0 av 11 181 bär en
# koordinat utan flaggan, alla 11 181 gör det med den).
STOPAREAS_URL = "https://ext-api.vasttrafik.se/geo/v3/StopAreas?includeGeometry=true"


def sweref99_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """
    Västtrafik publicerar koordinater i SWEREF99TM (EPSG:3006), Sveriges
    nationella projicerade rikssystem -- t.ex. Brunnsparken är
    POINT (319346 6400119), meter från en falsk origo, INTE grader.

    Portad som den handskrivna inversa transversella Mercator-formeln,
    rad för rad -- inte utbytt mot pyproj. Formeln är redan bevisad mot
    268/268 verkliga referenspunkter i Node; ett nytt bibliotek här skulle
    byta en riskfri 1:1-port mot ett overifierat beroende, för exakt den
    sortens känslig-att-få-fel matematik där en koordinatbugg i Göteborg
    tyst skulle placera en förare på fel gathörn. Verifierad mot
    Brunnsparken i core/test_vasttrafik.py.
    """
    axis = 6378137.0  # GRS80 storaxel
    flat = 1 / 298.257222101  # GRS80 flattening
    k0, fe, lambda_zero = 0.9996, 500000.0, math.radians(15.0)

    e2 = flat * (2 - flat)
    n = flat / (2 - flat)
    a_roof = (axis / (1 + n)) * (1 + (n * n) / 4 + (n**4) / 64)

    delta1 = n / 2 - (2 * n * n) / 3 + (37 * n**3) / 96 - (n**4) / 360
    delta2 = (n * n) / 48 + (n**3) / 15 - (437 * n**4) / 1440
    delta3 = (17 * n**3) / 480 - (37 * n**4) / 840
    delta4 = (4397 * n**4) / 161280

    a_star = e2
    b_star = (5 * e2**2 - e2**3) / 6
    c_star = (104 * e2**3 - 45 * e2**4) / 120
    d_star = (1237 * e2**4) / 1260

    xi = northing / (k0 * a_roof)
    eta = (easting - fe) / (k0 * a_roof)

    xi_prim = (
        xi
        - delta1 * math.sin(2 * xi) * math.cosh(2 * eta)
        - delta2 * math.sin(4 * xi) * math.cosh(4 * eta)
        - delta3 * math.sin(6 * xi) * math.cosh(6 * eta)
        - delta4 * math.sin(8 * xi) * math.cosh(8 * eta)
    )
    eta_prim = (
        eta
        - delta1 * math.cos(2 * xi) * math.sinh(2 * eta)
        - delta2 * math.cos(4 * xi) * math.sinh(4 * eta)
        - delta3 * math.cos(6 * xi) * math.sinh(6 * eta)
        - delta4 * math.cos(8 * xi) * math.sinh(8 * eta)
    )

    phi_star = math.asin(math.sin(xi_prim) / math.cosh(eta_prim))
    delta_lambda = math.atan(math.sinh(eta_prim) / math.cos(xi_prim))
    s = math.sin(phi_star)
    phi = phi_star + s * math.cos(phi_star) * (
        a_star + b_star * s**2 + c_star * s**4 + d_star * s**6
    )

    return math.degrees(phi), math.degrees(lambda_zero + delta_lambda)


# Token-cachning speglar Node-workerns fcmPush.js-mönster: tokens gäller
# ~24h, så att minta en per anrop vore rent slöseri. OBS: den här cachen
# hjälper bara INOM en process -- varje `manage.py poll_vasttrafik`-körning
# är en ny process och mintar sin egen token. Accepterad begränsning,
# matchar kodbasens "ingen Celery, medvetet minimal"-hållning; blir
# värdefull den dag ett långlivat Django-processer finns.
_cached_token: str | None = None
_cached_token_expires_at: float = 0


def get_access_token(client_id: str, client_secret: str) -> str:
    global _cached_token, _cached_token_expires_at
    if _cached_token and time.time() < _cached_token_expires_at - 60:
        return _cached_token

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    res = requests.post(
        TOKEN_URL,
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
        data="grant_type=client_credentials",
        timeout=30,
    )
    if not res.ok:
        raise RuntimeError(f"vasttrafik token {res.status_code}: {res.text[:160]}")
    body = res.json()
    if not body.get("access_token"):
        raise RuntimeError("vasttrafik token: no access_token in response")
    _cached_token = body["access_token"]
    _cached_token_expires_at = time.time() + float(body.get("expires_in") or 3600)
    return _cached_token


def authed_get(url: str, client_id: str, client_secret: str) -> dict:
    token = get_access_token(client_id, client_secret)
    res = requests.get(
        url, headers={"Authorization": f"Bearer {token}", "Accept-Encoding": "gzip"}, timeout=30
    )
    if res.status_code == 403:
        # Skiljer "inte prenumererad" från "fel autentisering": en token
        # mintades redan ovan, så nyckelparet är giltigt -- applikationen är
        # bara inte prenumererad på det här API:t i utvecklarportalen. Att
        # säga det rakt ut sparar en omtestning av hemligheten.
        from urllib.parse import urlparse
        path = urlparse(url).path
        raise RuntimeError(
            f"vasttrafik 403 on {path} -- token minted OK, so the application "
            f"is likely not subscribed to this API. Subscribe it in "
            f"developer.vasttrafik.se (Störning v1 / Geografi v3) and retry."
        )
    if not res.ok:
        raise RuntimeError(f"vasttrafik {res.status_code}: {res.text[:160]}")
    return res.json()


# Västtrafik anger start/sluttid för själva situationen (startTime/endTime),
# en genuin förbättring över SL:s publiceringsfönster -- den beskriver
# störningen, inte meddelandet. Samma agerbarhetsregel gäller ändå: en
# månadslång planerad avstängning är ett faktum om kartan, inte ett
# taxitillfälle.
MAX_AGE = timedelta(hours=24)
MAX_WINDOW = timedelta(days=7)


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def is_actionable(situation: dict, now: datetime | None = None) -> bool:
    now = now or datetime.now(dt_timezone.utc)
    start = _parse(situation.get("startTime"))
    end = _parse(situation.get("endTime"))
    if start is None or end is None:
        return False
    # Måste ha PÅBÖRJATS. Västtrafik publicerar planerat spårarbete långt i
    # förväg -- mätt: 17 av 87 situationer, och 10 av de 19 som klarade
    # ålder/varaktighet-testet ensamt, hade inte börjat än (nattarbete
    # schemalagt upp till tre veckor ut).
    if start > now:
        return False
    if now - start > MAX_AGE:
        return False
    if end - start > MAX_WINDOW:
        return False
    return end > now


def normalize_severity(severity: str | None) -> str | None:
    """
    Västtrafiks `severity` är operatörens egen bedömning (dokumenterade
    värden: normal/high/veryHigh). Precis som SL:s importance_level bärs
    den vidare som bevis, mappas aldrig in i demand_score.
    """
    v = str(severity or "").lower()
    if v in ("veryhigh", "very_high"):
        return "veryHigh"
    if v == "high":
        return "high"
    if v == "normal":
        return "normal"
    if v == "slight":
        return "slight"
    return None


def mode_hint_from(lines: list[dict] | None) -> str | None:
    modes = {
        str(l.get("defaultTransportModeCode") or l.get("transportMode") or "").lower()
        for l in (lines or [])
    }
    modes.discard("")
    if not modes:
        return None
    if "tram" in modes:
        return "tram"
    if "train" in modes or "rail" in modes:
        return "train"
    if "bus" in modes:
        return "bus"
    if "ferry" in modes or "boat" in modes:
        return "boat"
    return None


def normalize_situation(situation: dict, stop_area_index: dict | None) -> dict | None:
    stop_points = situation.get("affectedStopPoints") or []
    # Tåg/expressbuss-situationer bär INGA affectedLines -- linjen sitter
    # under affectedJourneys[].line istället (verifierat: varje "Öresundståg
    # NNNN är inställt"-situation har affectedLines: [] och en ifylld
    # affectedJourneys). Missar man det faller inställda tåg -- den enskilt
    # mest värdefulla tipstypen -- till mode "unknown" och därmed
    # severity_tier "ignore".
    journeys = situation.get("affectedJourneys") or []
    lines = situation.get("affectedLines") or [j.get("line") for j in journeys if j.get("line")]

    areas = list(dict.fromkeys(
        [s.get("stopAreaName") or s.get("name") for s in stop_points if s.get("stopAreaName") or s.get("name")]
        + [s.get("municipalityName") for s in stop_points if s.get("municipalityName")]
    ))
    routes = list(dict.fromkeys(
        str(l.get("designation") or l.get("name")) for l in lines if l.get("designation") or l.get("name")
    ))
    stops = list(dict.fromkeys(
        str(s.get("stopAreaGid") or s.get("gid")) for s in stop_points if s.get("stopAreaGid") or s.get("gid")
    ))

    # Hållplatspunkterna i situations-flödet bär INGA koordinater -- bara en
    # stopAreaGid, som slås upp mot geo-registret (mätt: 268/268 av
    # refererade gid:n löser). Registrets egna koordinater är SWEREF99TM och
    # projiceras till WGS84 när indexet byggs.
    lat = None
    lon = None
    for sp in stop_points:
        hit = (stop_area_index or {}).get(str(sp.get("stopAreaGid"))) or (stop_area_index or {}).get(str(sp.get("gid")))
        if hit:
            lat, lon = hit["lat"], hit["lon"]
            break

    start = _parse(situation.get("startTime"))
    end = _parse(situation.get("endTime"))

    # affectedJourneys ger, när den finns (~11% av situationer, mätt live),
    # den drabbade turens egna schemalagda avgångstid och riktning -- t.ex.
    # "830, Munkedal → Uddevalla". Det är INTE "nästa avgång" (det kräver en
    # hel tidtabell att jämföra mot, som varken den här källan eller
    # Trafiklab exponerar -- se core/sources/trafikverket_rail.py:s
    # next_departure_minutes, den enda källan med det), bara vilken tur och
    # åt vilket håll det gällde.
    first_journey = journeys[0] if journeys else None
    journey_line = (first_journey or {}).get("line") or {}
    route_label = str(journey_line.get("designation") or "") or (routes[0] if routes else "")
    direction = None
    if journey_line.get("directions"):
        direction = journey_line["directions"][0].get("name")
    journey_departure_at = _parse((first_journey or {}).get("departureDateTime"))

    return {
        "id": f"vt:{situation.get('situationNumber')}",
        "header": situation.get("title") or "Störning",
        "description": situation.get("description") or "",
        "cause": None,
        "effect": None,
        "areas": areas, "routes": routes, "stops": stops,
        "route_label": route_label or None,
        "direction": direction,
        "journey_departure_at": journey_departure_at,
        "url": None,
        "active_from": start or datetime.now(dt_timezone.utc),
        "active_to": end,
        "source": "vt",
        "region": "vt",
        "lat": lat, "lon": lon,
        "mode_hint": mode_hint_from(lines),
        "vt": {"severity": normalize_severity(situation.get("severity"))},
    }


def build_stop_area_index(rows: list[dict] | None) -> dict[str, dict]:
    """gid -> {lat, lon, name} för Göteborgs hållplatsregister."""
    return {str(r["gid"]): r for r in (rows or [])}


def fetch_vasttrafik_stop_areas(client_id: str, client_secret: str) -> list[dict]:
    body = authed_get(STOPAREAS_URL, client_id, client_secret)
    areas = body.get("stopAreas") if isinstance(body, dict) else (body if isinstance(body, list) else [])

    seen: set[str] = set()
    rows = []
    for a in areas or []:
        gid = a.get("gid")
        if not gid or str(gid) in seen:
            continue
        geometry = a.get("geometry") or {}
        if geometry.get("eastingCoordinate") is None or geometry.get("northingCoordinate") is None:
            continue
        seen.add(str(gid))
        lat, lon = sweref99_to_wgs84(
            float(geometry["eastingCoordinate"]), float(geometry["northingCoordinate"])
        )
        rows.append({"gid": str(gid), "operator": "vt", "name": a.get("name"), "lat": lat, "lon": lon})
    return rows


def fetch_vasttrafik_situations(
    client_id: str | None, client_secret: str | None,
    stop_area_index: dict | None = None, now: datetime | None = None,
) -> dict:
    if not client_id or not client_secret:
        return {"alerts": [], "source": "vt", "skipped": "no credentials"}

    now = now or datetime.now(dt_timezone.utc)
    body = authed_get(SITUATIONS_URL, client_id, client_secret)
    all_situations = body if isinstance(body, list) else (body.get("results") or [])

    alerts = []
    for situation in all_situations:
        if not is_actionable(situation, now):
            continue
        alert = normalize_situation(situation, stop_area_index)
        if alert:
            alerts.append(alert)

    return {"alerts": alerts, "source": "vt", "received": len(all_situations), "actionable": len(alerts)}
