"""
Trafiklab GTFS-Realtime ServiceAlerts -- inställda/försenade turer, tåg/buss.

Port av worker/src/trafiklab.js. Använder `gtfs-realtime-bindings` (Python-
paketet, samma genererade .proto-schema som npm-paketet Node-workern redan
använder) i stället för en handskriven decoder.

Till skillnad från RailAlert (en dataclass -- TrafikverketRail är en enda,
strukturellt rik källa) returnerar den här modulen plain dicts. Det speglar
Node-originalets egna otypade objektlitteraler bättre: alert-formen är
medvetet löst (SL lägger senare till ett `sl`-fält, `mode_hint` sätts bara av
källor som SL publicerar det för) och delas av flera framtida källor --
en dataclass skulle tvinga fram ett gemensamt schema för fält som bara vissa
källor har.

Mätt mot live-data (se docs/data-sources.md): `cause`/`effect` tillför inget
den svenska texten inte redan bär -- kvar här för formparitet/felsökning,
används inte i klassificeringen.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone as dt_timezone

import requests
from django.conf import settings
from google.transit import gtfs_realtime_pb2 as pb

CAUSE = {
    1: "Okänd orsak", 2: "Övrigt", 3: "Tekniskt fel", 4: "Strejk",
    5: "Demonstration", 6: "Olycka", 7: "Semester", 8: "Väder",
    9: "Underhåll", 10: "Byggarbete", 11: "Polisinsats",
    12: "Medicinsk nödsituation",
}

EFFECT = {
    1: "Ingen service", 2: "Minskad service", 3: "Stora förseningar",
    4: "Förseningar", 5: "Omledning", 6: "Ytterligare avgångar",
    7: "Modifierad service", 8: "Annat", 9: "Okänd effekt",
    10: "Stoppad avgång", 11: "Inställd avgång",
}

_PLACE_PATTERNS = [
    re.compile(
        r"\b(Malmö|Lund|Helsingborg|Kristianstad|Hässleholm|Landskrona|Halmstad|"
        r"Karlskrona|Växjö|Älmhult|Ystad|Trelleborg|Ängelholm|Eslöv|Kävlinge|"
        r"Bromölla|Hyllie|Markaryd|Höganäs|Vellinge)\b", re.IGNORECASE,
    ),
    re.compile(r"\b(Halmstad|Falkenberg|Varberg|Laholm|Kungsbacka|Hyltebruk)\b", re.IGNORECASE),
    re.compile(r"\b(Karlskrona|Karlshamn|Ronneby|Sölvesborg|Olofström)\b", re.IGNORECASE),
    re.compile(
        r"\b(Växjö|Ljungby|Älmhult|Alvesta|Markaryd|Värnamo|Nässjö|Jönköping|Eksjö)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(Pågatåg|Öresundståg|Krösatåg|Kustpilen|Pendeln|Citybuss|Regionbuss)\b", re.IGNORECASE),
    # National rollout: with 15 operators polled instead of one, an alert
    # from Umeå or Örebro carried no recognisable place name at all and so
    # reached the map with lat/lon = null. Lookaround instead of \b here --
    # ported byte-for-byte from the JS version even though Python's \b is
    # already Unicode-aware (unlike JS's ASCII-only \b), since this is the
    # pattern actually tested against real Ängelholm/Örebro-style cases.
    re.compile(
        r"(?<![a-zà-öø-ÿ0-9])(Stockholm|Solna|Södertälje|Nacka|Sundbyberg|Täby|"
        r"Norrtälje|Uppsala|Enköping|Göteborg|Mölndal|Borås|Trollhättan|Uddevalla|"
        r"Skövde|Linköping|Norrköping|Motala|Kalmar|Oskarshamn|Västervik|Nybro|"
        r"Karlstad|Kristinehamn|Arvika|Örebro|Karlskoga|Västerås|Köping|Eskilstuna|"
        r"Nyköping|Falun|Borlänge|Mora|Gävle|Sandviken|Hudiksvall|Sundsvall|"
        r"Härnösand|Örnsköldsvik|Östersund|Umeå|Skellefteå|Luleå|Piteå|Kiruna|Visby)"
        r"(?![a-zà-öø-ÿ0-9])", re.IGNORECASE,
    ),
]


def pick_translation(translated) -> str:
    if not translated or not translated.translation:
        return ""
    items = translated.translation
    sv = next((t for t in items if str(t.language or "").lower().startswith("sv")), None)
    return (sv or items[0]).text


def extract_areas(header: str, description: str, entities) -> dict:
    areas: list[str] = []
    routes: list[str] = []
    stops: list[str] = []

    def add(collection: list[str], value: str) -> None:
        if value not in collection:
            collection.append(value)

    for entity in entities or []:
        if entity.route_id:
            add(routes, str(entity.route_id))
        if entity.stop_id:
            add(stops, str(entity.stop_id))
        # agency_id är tomt i hela det svenska flödet (0 av 538 mätt
        # 2026-09-08). Behållet därför att GTFS-RT-specen har fältet och
        # andra operatörer fyller det -- men det bidrar med noll här.
        if entity.agency_id:
            add(areas, f"Operatör {entity.agency_id}")
        if entity.trip and entity.trip.route_id:
            add(routes, str(entity.trip.route_id))

    text = f"{header}\n{description}"
    for pattern in _PLACE_PATTERNS:
        for match in pattern.finditer(text):
            add(areas, match.group(0))

    if routes:
        add(areas, f"Linjer: {', '.join(routes[:8])}")
    if stops:
        add(areas, f"Hållplatser: {', '.join(stops[:6])}")

    return {"areas": areas, "routes": routes, "stops": stops}


def parse_feed(buffer: bytes) -> list[dict]:
    feed = pb.FeedMessage()
    feed.ParseFromString(buffer)

    alerts = []
    for entity in feed.entity:
        if not entity.HasField("alert"):
            continue
        alert = entity.alert
        header = pick_translation(alert.header_text) or "Störning"
        description = pick_translation(alert.description_text)
        # Även url är genomgående tom i det svenska flödet (0 av 538).
        url = pick_translation(alert.url)
        shaped = extract_areas(header, description, alert.informed_entity)

        # Real datetimes, not epoch-ms ints: repository.py writes these
        # straight into timestamptz columns via raw SQL/psycopg, which has
        # no implicit int-to-timestamp cast (unlike a JS driver, which
        # would silently coerce a number). RailAlert follows the same
        # convention for the same reason.
        active_from = None
        active_to = None
        if alert.active_period:
            period = alert.active_period[0]
            if period.start:
                active_from = datetime.fromtimestamp(period.start, tz=dt_timezone.utc)
            if period.end:
                active_to = datetime.fromtimestamp(period.end, tz=dt_timezone.utc)

        alerts.append({
            "id": entity.id or f"alert-{header[:40]}-{active_from or 'na'}",
            "header": header,
            "description": description,
            # Mätt: effect är UNKNOWN_EFFECT på i praktiken alla larm, och
            # cause tillför inget texten inte redan bär -- se
            # docs/data-sources.md. Byggs ändå för formparitet/felsökning.
            "cause": CAUSE.get(alert.cause, "Okänd orsak"),
            "effect": EFFECT.get(alert.effect, "Okänd effekt"),
            "areas": shaped["areas"], "routes": shaped["routes"], "stops": shaped["stops"],
            "url": url or None,
            "active_from": active_from,
            "active_to": active_to,
        })
    return alerts


def mock_alerts() -> list[dict]:
    now = datetime.now(dt_timezone.utc)
    return [
        {
            "id": "mock-pagatag-lund-malmo",
            "header": "Inställda avgångar Pågatåg Lund–Malmö",
            "description": (
                "På grund av signalproblem är flera Pågatåg mellan Lund C och "
                "Malmö C inställda. Ersättningsbussar sätts in. Räkna med "
                "längre restider under eftermiddagen."
            ),
            "cause": "Tekniskt fel", "effect": "Inställd avgång",
            "areas": ["Lund", "Malmö", "Pågatåg", "Linjer: PA"],
            "routes": ["PA"], "stops": ["82000", "80000"],
            "url": "https://www.skanetrafiken.se/",
            "active_from": now - timedelta(minutes=30),
            "active_to": now + timedelta(hours=3),
        },
        {
            "id": "mock-buss-helsingborg",
            "header": "Trafikstörning stadsbuss Helsingborg",
            "description": (
                "Linje 1 och 2 påverkas av vägarbete i centrum. Bussarna kör "
                "alternativ sträckning via Hälsovägen."
            ),
            "cause": "Byggarbete", "effect": "Omledning",
            "areas": ["Helsingborg", "Linjer: 1, 2"],
            "routes": ["1", "2"], "stops": [],
            "url": None,
            "active_from": now - timedelta(hours=2),
            "active_to": now + timedelta(hours=6),
        },
    ]


def configured_operators() -> list[str]:
    """TRAFIKLAB_OPERATORS=skane,blekinge,krono,jlt,halland"""
    raw = str(getattr(settings, "TRAFIKLAB_OPERATORS", "skane") or "skane")
    seen: list[str] = []
    for s in raw.split(","):
        op = s.strip().lower()
        if op and op not in seen:
            seen.append(op)
    return seen


def fetch_operator_alerts(api_key: str, operator: str) -> list[dict]:
    url = (
        f"https://opendata.samtrafiken.se/gtfs-rt-sweden/{operator}/"
        f"ServiceAlertsSweden.pb?key={api_key}"
    )
    res = requests.get(
        url, headers={"Accept": "application/x-protobuf", "Accept-Encoding": "gzip"}, timeout=30
    )
    if not res.ok:
        raise RuntimeError(f"{operator} {res.status_code}: {res.text[:160]}")

    alerts = parse_feed(res.content)
    for a in alerts:
        a["id"] = f"{operator}:{a['id']}"
        a["region"] = operator
        a["source"] = "trafiklab"
    return alerts


def fetch_trafiklab_alerts(api_key: str) -> dict:
    if not api_key or api_key == "mock":
        return {"alerts": mock_alerts(), "source": "mock", "operators": ["mock"]}

    merged: list[dict] = []
    ok: list[str] = []
    errors: list[dict] = []

    for operator in configured_operators():
        try:
            merged.extend(fetch_operator_alerts(api_key, operator))
            ok.append(operator)
        except Exception as err:  # noqa: BLE001 -- one bad operator must not kill the batch
            errors.append({"operator": operator, "error": str(err)})

    if not ok:
        raise RuntimeError(" | ".join(e["error"] for e in errors) or "Inga regioner svarade")

    return {
        "alerts": merged, "source": "trafiklab", "operators": ok,
        "errors": errors or None,
    }
