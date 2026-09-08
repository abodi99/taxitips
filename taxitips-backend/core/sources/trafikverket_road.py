"""
Trafikverkets öppna API -- Situation (väginformation).

Port av worker/src/trafikverket.js. Sista källan som saknades i Django:
tåg, buss, tunnelbana, spårvagn och väder hämtades redan här, medan vägen
låg kvar i Node. `core/taxi_relevance.py` och `core/text_scoring.py` hade
båda en gren som kastade `NotImplementedError` med kommentaren "no road
source in Django" -- det är den grenen den här modulen fyller.

Vad väghändelser INTE är: en taxisignal. En olycka eller kö försenar dem
som redan sitter i bil; ingen lämnar sin bil mitt i en kö och tar taxi.
Poängen kapas därför lågt över hela linjen (max 15) i score_road_alert --
det här är sammanhang för en förare som redan är på väg, inte ett skäl att
köra någonstans. Anledningen att ändå hämta det är att en förare vill veta
om vägen dit är avstängd.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

import requests
from django.conf import settings

log = logging.getLogger(__name__)

TRAFIKVERKET_URL = "https://api.trafikinfo.trafikverket.se/v2/data.json"

# SCB:s länskoder, som är det Deviation.CountyNo använder. Alla 21 -- en
# tidigare version hade bara de sex sydligaste, vilket tyst kapade
# vägtäckningen oavsett vad konfigurationen bad om.
COUNTY: dict[str, str] = {
    "stockholm": "1", "uppsala": "3", "sodermanland": "4", "ostergotland": "5",
    "jonkoping": "6", "kronoberg": "7", "kalmar": "8", "gotland": "9",
    "blekinge": "10", "skane": "12", "halland": "13", "vastragotaland": "14",
    "varmland": "17", "orebro": "18", "vastmanland": "19", "dalarna": "20",
    "gavleborg": "21", "vasternorrland": "22", "jamtland": "23",
    "vasterbotten": "24", "norrbotten": "25",
}


def configured_counties() -> list[str]:
    """TRAFIKVERKET_COUNTIES=all|skane,stockholm,... -> länskoder."""
    configured = str(getattr(settings, "TRAFIKVERKET_COUNTIES", "skane") or "skane")
    names = (
        list(COUNTY)
        if configured.strip().lower() == "all"
        else [n.strip().lower() for n in configured.split(",")]
    )
    seen: list[str] = []
    for name in names:
        code = COUNTY.get(name)
        if code and code not in seen:
            seen.append(code)
    return seen


def level_for_deviation(dev: dict) -> str:
    """
    Hur allvarlig väghändelsen ser ut i källans egna etiketter.

    `MessageCode` läses numera också. `MessageType` har bara tre möjliga
    värden och kallar en helt avstängd väg "Vägarbete"; koden är den som
    säger "Vägen avstängd". Mätt före ändringen: 25 av 33 avvikelser med
    MessageCode "Vägen avstängd" klassades `low`. Se
    docs/api-field-inventory.md, förslag 3.
    """
    icon = str(dev.get("IconId") or "")
    t = " ".join(
        str(dev.get(k) or "") for k in ("MessageType", "MessageCode", "IconId")
    ).lower()
    sev = f"{dev.get('SeverityText') or ''} {dev.get('SeverityCode') or ''}".lower()
    # roadClosed är källans egen, entydiga flagga för en stängd väg och
    # behöver ingen textmatchning alls.
    if icon == "roadClosed":
        return "high"
    if "olycka" in t or "avstäng" in t or "avstang" in t or "mycket" in sev:
        return "high"
    if any(k in t for k in ("kö", "ko", "hinder", "arbete")):
        return "medium"
    return "low"


_KNOWN_PLACES_RE = re.compile(
    r"\b(Malmö|Lund|Helsingborg|Kristianstad|Hässleholm|Landskrona|Halmstad|"
    r"Karlskrona|Växjö|Älmhult|Ystad|Trelleborg|Ängelholm|Eslöv|Kävlinge|"
    r"Bromölla|Hyllie|Markaryd|Höganäs|Vellinge|Stockholm|Göteborg|Uppsala|"
    r"Örebro|Linköping|Norrköping|Jönköping|Västerås|Umeå|Luleå|Sundsvall|"
    r"Gävle|Falun|Karlstad|Visby)\b",
    re.IGNORECASE,
)


def places_from_deviation(dev: dict) -> list[str]:
    blob = " ".join(
        str(dev.get(k) or "")
        for k in ("LocationDescriptor", "Message", "RoadNumber", "CountyNo")
    )
    places: list[str] = []
    for name in _KNOWN_PLACES_RE.findall(blob):
        if not any(p.lower() == name.lower() for p in places):
            places.append(name)
    # Vägnumret bara om ingen ort hittades -- annars drunknar kartan i E4.
    if not places and dev.get("RoadNumber"):
        places.append(str(dev["RoadNumber"]))
    return places


def _to_lat_lon(pair: str) -> tuple[float, float] | None:
    parts = pair.strip().split()
    if len(parts) < 2:
        return None
    try:
        lon, lat = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    # WGS84 WKT är "lon lat". Läses den lat-först hamnar E6 i Indiska
    # oceanen -- samma fälla som stationskoordinaterna i core/geo.py.
    return lat, lon


def parse_wgs84_geometry(geometry: dict | None) -> dict | None:
    """WKT (LINESTRING/POINT) -> {lat, lon, path} med mittpunkten som pin."""
    if not geometry:
        return None
    wkt = (
        (geometry.get("Line") or {}).get("WGS84")
        or (geometry.get("Point") or {}).get("WGS84")
        or geometry.get("WGS84")
    )
    if not isinstance(wkt, str):
        return None

    path: list[tuple[float, float]] = []
    if wkt.upper().startswith("LINESTRING"):
        inner = re.sub(r"^LINESTRING\s*\(", "", wkt, flags=re.IGNORECASE).rstrip(") ")
        path = [p for p in (_to_lat_lon(seg) for seg in inner.split(",")) if p]
    elif wkt.upper().startswith("POINT"):
        m = re.match(r"POINT\s*\(\s*([-\d.]+)\s+([-\d.]+)\s*\)", wkt, re.IGNORECASE)
        if m:
            path = [(float(m.group(2)), float(m.group(1)))]
    if not path:
        return None

    # Långa sträckor glesas ut för kartans skull -- 60 punkter räcker för
    # att se var vägen går.
    if len(path) > 80:
        step = -(-len(path) // 60)
        path = [p for i, p in enumerate(path) if i % step == 0 or i == len(path) - 1]

    mid = path[len(path) // 2]
    return {"lat": mid[0], "lon": mid[1], "path": [list(p) for p in path]}


def _parse_time(value: str | None):
    """
    ISO-8601 från Trafikverket -> datetime. Strängen skrevs tidigare rakt
    igenom, vilket fungerade ända fram till första jämförelsen mot en
    datetime -- Postgres tolkade den åt oss och dolde att fältet hade fel
    typ i Python.
    """
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def normalize_situation(situation: dict) -> list[dict]:
    """Situation -> larm i samma form som SL/Västtrafik/Trafiklab levererar."""
    deviations = situation.get("Deviation") or []
    if isinstance(deviations, dict):
        deviations = [deviations]

    out = []
    for i, dev in enumerate(deviations):
        header = dev.get("Header") or dev.get("MessageType") or "Väghändelse"
        description = " · ".join(
            part
            for part in (
                dev.get("Message"),
                dev.get("LocationDescriptor"),
                f"Väg {dev['RoadNumber']}" if dev.get("RoadNumber") else None,
            )
            if part
        )
        places = places_from_deviation(dev)
        geometry = parse_wgs84_geometry(dev.get("Geometry"))
        out.append({
            "id": f"tv:{situation.get('Id') or 'sit'}:{dev.get('Id') or i}",
            "header": header,
            "description": description,
            # MessageCode före MessageType: typen har bara tre värden och
            # kallar en helt avstängd väg "Vägarbete", medan koden säger
            # "Vägen avstängd". `cause` är det score_road_alert läser för
            # att avgöra om det är en avstängning, en olycka eller ett
            # vägarbete -- utan koden såg de två första ut som det tredje.
            "cause": str(dev.get("MessageCode") or dev.get("MessageType") or "Situation"),
            "message_type": str(dev.get("MessageType") or ""),
            "effect": dev.get("SeverityText") or "Vägpåverkan",
            "areas": places,
            "routes": [str(dev["RoadNumber"])] if dev.get("RoadNumber") else [],
            "stops": [],
            "url": None,
            # Avvikelsens EGEN starttid, inte situationens publiceringstid.
            # PublicationTime sätts om varje gång Trafikverket republicerar
            # posten, så ett vägarbete från 2024 såg nyskapat ut vid varje
            # pollcykel -- mätt medianfel 862 timmar. StartTime är ifylld på
            # 100% av avvikelserna. Se docs/api-field-inventory.md, förslag 1.
            "active_from": _parse_time(dev.get("StartTime"))
            or _parse_time(situation.get("PublicationTime")),
            # Källans eget slut, när det finns (99% ifyllt). Det är ofta
            # planeringsfönstret snarare än störningens längd -- exempel ur
            # verklig data: EndTime 2029-10-31 för ett vägarbete. poll_road
            # kapar därför mot ett eget tak.
            "active_to": _parse_time(dev.get("EndTime")),
            "source_kind": "road",
            # "trafikverket", inte NULL: feed_for gör coalesce(region,
            # "skane") för tips UTAN koordinat, så en väghändelse vars
            # geometri saknas hade tyst blivit ett skånskt tips oavsett var
            # i landet den ligger. Mätt: 4 av 543 saknar geometri. Med den
            # här nyckeln matchar de ingen förarmarknad alls, vilket är
            # rätt svar -- utan koordinat går det inte att säga att vägen
            # är relevant för någon.
            "region": "trafikverket",
            "mode_hint": "road",
            "geometry": geometry,
            "lat": (geometry or {}).get("lat"),
            "lon": (geometry or {}).get("lon"),
            "severity_hint": level_for_deviation(dev),
        })
    return out


def fetch_road_situations(api_key: str, counties: list[str] | None = None) -> dict:
    """
    Hämtar Situation för de konfigurerade länen.

    Länsfiltret är ett OR, så `limit` kapar HELA landet, inte per län --
    och vilka rader som överlever är odefinierat. Vid limit=100 över 21 län
    gav det färre nationella larm än Skåne ensamt (mätt: 127 mot 176).
    Taket skalar därför med antalet län.
    """
    counties = counties or configured_counties()
    if not counties:
        counties = [COUNTY["skane"]]
    limit = min(100 * len(counties), 2000)
    county_filter = "".join(
        f'<EQ name="Deviation.CountyNo" value="{c}" />' for c in counties
    )
    body = (
        "<REQUEST>"
        f'<LOGIN authenticationkey="{api_key}" />'
        f'<QUERY objecttype="Situation" namespace="road.trafficinfo" '
        f'schemaversion="1.6" limit="{limit}">'
        f"<FILTER><OR>{county_filter}</OR></FILTER>"
        "</QUERY></REQUEST>"
    )

    res = requests.post(
        TRAFIKVERKET_URL,
        data=body.encode("utf-8"),
        headers={"Content-Type": "text/xml", "Accept": "application/json"},
        timeout=30,
    )
    payload = res.json() if res.content else {}
    block = ((payload.get("RESPONSE") or {}).get("RESULT") or [{}])[0]
    if not res.ok or block.get("ERROR"):
        message = (block.get("ERROR") or {}).get("MESSAGE") or str(payload)[:200]
        raise RuntimeError(f"Trafikverket {res.status_code}: {message}")

    situations = block.get("Situation") or []
    if isinstance(situations, dict):
        situations = [situations]

    alerts: list[dict] = []
    for sit in situations:
        alerts.extend(normalize_situation(sit))
    return {"alerts": alerts, "counties": counties, "situations": len(situations)}
