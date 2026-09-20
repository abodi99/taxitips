"""
AISStream-meddelanden: tolkning och ankomstlogik, utan nätverk och databas.

Allt här är rena funktioner så att testerna kan köra riktiga meddelanden
utan en WebSocket. Kommandot run_ais_stream.py äger anslutningen och
skrivningarna.

Sex av AISStreams 25 meddelandetyper beskriver fartyg (se MESSAGE_TYPES).
Klass A är större fartyg med fast AIS-plikt; klass B mindre fartyg och
fritidsbåtar. Mätt 2026-09-12 i hamnrutorna: 80 klass A-fartyg och 42 klass
B-fartyg på två minuter -- en tredjedel av trafiken sänder bara klass B.

Saker i datan som inte står i AISStreams dokumentation (docs/data-sources.md):

1. Positionen i MetaData heter `latitude`/`longitude` med gemener.
2. Positionsmeddelanden bär ingen fartygstyp, utom ExtendedClassB. Typen
   kommer i ShipStaticData (klass A) eller StaticDataReport del B (klass B),
   ungefär var sjätte minut. Den måste därför minnas per MMSI.
3. StaticDataReport kommer i två delar: del A bär BARA namnet, med ReportB
   ogiltig och nollad. Tolkas den som statisk data nollas fartygets typ.
4. ETA är handinmatad och ofta skräp: Hour=24/Minute=60 och nollor betyder
   "saknas", och ETA har inget år.
5. ShipType 60-69 är "passagerarfartyg" i AIS-mening, vilket i Stockholms
   inre hamn mest betyder 25-metersbåtar. Längdgränsen står i maritime/tips.py.
"""

from __future__ import annotations

import datetime as dt
import re
from collections import deque
from dataclasses import dataclass

from maritime.ports import PORTS, port_for

UTC = dt.timezone.utc

PASSENGER_TYPES = range(60, 70)

# Meddelandetyperna som beskriver fartyg. Resten av de 25 -- fyrar,
# basstationer, räddningsflyg, binär- och kanaldata -- har ingen
# fartygsidentitet att följa. Se maritime/explain.py:s MESSAGE_TYPE_DOCS.
POSITION_TYPES = (
    "PositionReport",                # klass A
    "StandardClassBPositionReport",  # klass B
    "ExtendedClassBPositionReport",  # klass B, med namn, typ och storlek
    "LongRangeAisBroadcastMessage",  # klass A via satellit, grov och gles
)
STATIC_TYPES = (
    "ShipStaticData",    # klass A
    "StaticDataReport",  # klass B, i två delar
)
MESSAGE_TYPES = POSITION_TYPES + STATIC_TYPES
AIS_CLASS = {
    "PositionReport": "A",
    "LongRangeAisBroadcastMessage": "A",
    "ShipStaticData": "A",
    "StandardClassBPositionReport": "B",
    "ExtendedClassBPositionReport": "B",
    "StaticDataReport": "B",
}

# AIS:s "saknas"-värden.
SOG_NOT_AVAILABLE = 102.3
COG_NOT_AVAILABLE = 360.0
HEADING_NOT_AVAILABLE = 511
NAV_AT_ANCHOR = 1
NAV_MOORED = 5

# Under SLOW räknas fartyget som att det lägger till. Över UNDERWAY är det i
# fart. Glappet mellan dem är avsiktligt: ett fartyg som ligger och flyter på
# exakt fem knop ska inte slå av och på ankomsten varje meddelande.
SLOW_KNOTS = 5.0
UNDERWAY_KNOTS = 6.0

# Hur länge ett fartyg kan vara tyst innan nästa meddelande räknas som ett nytt
# anlöp. AISStream skickar bara inifrån hamnrutorna, så en färja som gått
# vidare syns aldrig lämna -- den slutar bara höras.
REARM_GAP = dt.timedelta(hours=3)
# En färja som manövrerar vid kaj direkt efter ankomsten ska inte räknas som
# avgång. Först efter så här lång tid får fart över UNDERWAY spärra upp igen.
REARM_AFTER_TRIGGER = dt.timedelta(minutes=20)

ETA_MAX_DISTANCE = dt.timedelta(days=7)
ETA_TRIGGER_AHEAD = dt.timedelta(minutes=60)
ETA_TRIGGER_BEHIND = dt.timedelta(minutes=10)

# Positioner som sparas för ett fartyg vars typ ännu inte hörts.
PENDING_POSITIONS = 10
PENDING_WINDOW = dt.timedelta(minutes=30)

REASON_SLOWING = "slowing_in_port"
REASON_ETA = "eta_soon"

_TIME_UTC = re.compile(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?")


@dataclass
class AisUpdate:
    kind: str  # "position" | "static"
    mmsi: int
    name: str
    timestamp: dt.datetime
    message_type: str = ""
    ais_class: str = ""
    lat: float | None = None
    lon: float | None = None
    sog: float | None = None
    cog: float | None = None
    heading: int | None = None
    nav_status: int | None = None
    # has_static: meddelandet bär typ och storlek. has_voyage: det bär resans
    # destination och ETA (bara ShipStaticData). Utan flaggorna skulle
    # StaticDataReport del A, som bara har namnet, nolla fartygets typ.
    has_static: bool = False
    has_voyage: bool = False
    ship_type: int | None = None
    length_m: int | None = None
    width_m: int | None = None
    call_sign: str = ""
    imo: int | None = None
    draught_m: float | None = None
    destination: str = ""
    eta: dt.datetime | None = None


def subscription_boxes() -> list[list[list[float]]]:
    """
    Inseglingsområdena, en gång var. De rymmer hamnrutorna, så en färja syns på väg in;
    ankomsten avgörs ändå i hamnrutan (port_for). Stockholms två terminaler delar område.
    """
    boxes: list[list[list[float]]] = []
    for port in PORTS:
        if port.approach_box not in boxes:
            boxes.append(port.approach_box)
    return boxes


def subscription(api_key: str) -> dict:
    """Prenumerationen. Måste skickas inom tre sekunder efter anslutning."""
    return {
        "APIKey": api_key,
        "BoundingBoxes": subscription_boxes(),
        "FilterMessageTypes": list(MESSAGE_TYPES),
    }


def is_passenger(ship_type: int | None) -> bool:
    return ship_type is not None and ship_type in PASSENGER_TYPES


def parse_time_utc(value, fallback: dt.datetime) -> dt.datetime:
    """`2026-09-12 19:25:20.575040512 +0000 UTC` -- Go:s time.String(), nanosekunder."""
    m = _TIME_UTC.match(str(value or ""))
    if not m:
        return fallback
    day, clock, fraction = m.groups()
    parsed = dt.datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=UTC)
    return parsed.replace(microsecond=int(((fraction or "") + "000000")[:6]))


def parse_sog(value) -> float | None:
    try:
        sog = float(value)
    except (TypeError, ValueError):
        return None
    if sog < 0 or sog >= SOG_NOT_AVAILABLE - 0.05:
        return None
    return sog


def parse_cog(value) -> float | None:
    try:
        cog = float(value)
    except (TypeError, ValueError):
        return None
    return cog if 0 <= cog < COG_NOT_AVAILABLE else None


def parse_heading(value) -> int | None:
    try:
        heading = int(value)
    except (TypeError, ValueError):
        return None
    return heading if 0 <= heading < 360 else None


def parse_eta(eta, now: dt.datetime) -> dt.datetime | None:
    """
    AIS-ETA (Month/Day/Hour/Minute, UTC, inget år) som datetime, eller None.

    None för AIS:s "saknas"-värden och för allt längre bort än en vecka --
    en ETA från juni är inte en ankomst i september, den är en besättning
    som aldrig uppdaterat fältet.
    """
    if not isinstance(eta, dict):
        return None
    try:
        month, day, hour, minute = (int(eta.get(k, 0)) for k in ("Month", "Day", "Hour", "Minute"))
    except (TypeError, ValueError):
        return None
    if not (1 <= month <= 12 and 1 <= day <= 31 and 0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    best = None
    for year in (now.year - 1, now.year, now.year + 1):
        try:
            candidate = dt.datetime(year, month, day, hour, minute, tzinfo=UTC)
        except ValueError:  # 30 februari
            continue
        if best is None or abs(candidate - now) < abs(best - now):
            best = candidate
    if best is None or abs(best - now) > ETA_MAX_DISTANCE:
        return None
    return best


def dimensions(dimension) -> tuple[int | None, int | None]:
    """(längd, bredd) = (A+B, C+D): avståndet från antennen för/akter och babord/styrbord."""
    if not isinstance(dimension, dict):
        return None, None
    try:
        length = int(dimension.get("A") or 0) + int(dimension.get("B") or 0)
        width = int(dimension.get("C") or 0) + int(dimension.get("D") or 0)
    except (TypeError, ValueError):
        return None, None
    return (length or None), (width or None)


def ship_length(dimension) -> int | None:
    return dimensions(dimension)[0]


def _ship_type(value) -> int | None:
    # Typ 0 är AIS:s "saknas", inte en fartygstyp.
    try:
        code = int(value)
    except (TypeError, ValueError):
        return None
    return code if code > 0 else None


def _positive_int(value) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _positive_float(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _clean_text(value) -> str:
    # AIS fyller textfält med '@' och blanksteg; "-" betyder "ingen destination".
    text = str(value or "").replace("@", " ").strip()
    return "" if text in {"-", "."} else text


def parse_message(msg, now: dt.datetime) -> AisUpdate | None:
    """Ett AISStream-meddelande som AisUpdate, eller None om det inte går att använda."""
    if not isinstance(msg, dict):
        return None
    mtype = msg.get("MessageType")
    if mtype not in MESSAGE_TYPES:
        return None
    meta = msg.get("MetaData") or {}
    body = (msg.get("Message") or {}).get(mtype) or {}
    if body.get("Valid") is False:
        return None
    try:
        mmsi = int(meta.get("MMSI") or body.get("UserID"))
    except (TypeError, ValueError):
        return None
    if not 100_000_000 <= mmsi <= 999_999_999:
        return None

    base = {
        "mmsi": mmsi,
        "name": _clean_text(meta.get("ShipName")),
        "timestamp": parse_time_utc(meta.get("time_utc"), now),
        "message_type": mtype,
        "ais_class": AIS_CLASS[mtype],
    }

    if mtype in POSITION_TYPES:
        lat = body.get("Latitude", meta.get("latitude", meta.get("Latitude")))
        lon = body.get("Longitude", meta.get("longitude", meta.get("Longitude")))
        # 91/181 är AIS:s "position saknas".
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        update = AisUpdate(
            kind="position", **base,
            lat=float(lat), lon=float(lon),
            sog=parse_sog(body.get("Sog")),
            cog=parse_cog(body.get("Cog")),
            heading=parse_heading(body.get("TrueHeading")),
            # Bara klass A och långdistans sänder navigationsstatus.
            nav_status=body.get("NavigationalStatus"),
        )
        if mtype == "ExtendedClassBPositionReport":
            update.has_static = True
            update.ship_type = _ship_type(body.get("Type"))
            update.length_m, update.width_m = dimensions(body.get("Dimension"))
            update.name = _clean_text(body.get("Name")) or update.name
        return update

    if mtype == "ShipStaticData":
        length, width = dimensions(body.get("Dimension"))
        return AisUpdate(
            kind="static",
            **{**base, "name": _clean_text(body.get("Name")) or base["name"]},
            has_static=True, has_voyage=True,
            ship_type=_ship_type(body.get("Type")),
            length_m=length, width_m=width,
            call_sign=_clean_text(body.get("CallSign")),
            imo=_positive_int(body.get("ImoNumber")),
            draught_m=_positive_float(body.get("MaximumStaticDraught")),
            destination=_clean_text(body.get("Destination")),
            eta=parse_eta(body.get("Eta"), now),
        )

    # StaticDataReport. PartNumber false = del A (namn), true = del B (typ, storlek).
    if not body.get("PartNumber"):
        part = body.get("ReportA") or {}
        if part.get("Valid") is False:
            return None
        return AisUpdate(kind="static", **{**base, "name": _clean_text(part.get("Name")) or base["name"]})
    part = body.get("ReportB") or {}
    if part.get("Valid") is False:
        return None
    length, width = dimensions(part.get("Dimension"))
    return AisUpdate(
        kind="static", **base,
        has_static=True,
        ship_type=_ship_type(part.get("ShipType")),
        length_m=length, width_m=width,
        call_sign=_clean_text(part.get("CallSign")),
    )


# -- fartygets tillstånd --------------------------------------------------------
#
# Funktionerna nedan tar en maritime.models.FerryArrival (eller något med samma
# attribut) och ändrar den på plats. Kommandot sparar; testerna gör det inte.


def static_fields(update: AisUpdate) -> dict:
    """Fälten meddelandet faktiskt bär, för aupdate_or_create. Aldrig tomma över kända."""
    fields = {}
    if update.name:
        fields["ship_name"] = update.name[:100]
    if update.has_static:
        fields["ship_type"] = update.ship_type
        if update.length_m:
            fields["length_m"] = update.length_m
    if update.has_voyage:
        fields["destination"] = update.destination[:40]
        fields["eta"] = update.eta
    return fields


def apply_static(vessel, update: AisUpdate) -> None:
    for field, value in static_fields(update).items():
        setattr(vessel, field, value)


def apply_position(vessel, update: AisUpdate) -> bool:
    """Uppdatera läget. False om meddelandet är äldre än det vi redan har."""
    if vessel.timestamp and update.timestamp < vessel.timestamp - dt.timedelta(minutes=1):
        return False

    # Tyst länge: det här är ett nytt anlöp, inte fortsättningen på det förra.
    if vessel.timestamp and update.timestamp - vessel.timestamp >= REARM_GAP:
        vessel.was_underway = False
        vessel.is_processed = False

    port = port_for(update.lat, update.lon)
    vessel.port_name = port.name if port else ""
    vessel.latitude = update.lat
    vessel.longitude = update.lon
    vessel.speed_knots = update.sog
    vessel.nav_status = update.nav_status
    vessel.timestamp = update.timestamp
    if update.name and not vessel.ship_name:
        vessel.ship_name = update.name[:100]

    if update.sog is not None and update.sog >= UNDERWAY_KNOTS:
        vessel.was_underway = True
        # I fart igen en bra stund efter ankomsten: färjan har avgått, och
        # nästa gång den saktar in är en ny ankomst.
        if (
            vessel.is_processed
            and vessel.triggered_at
            and update.timestamp - vessel.triggered_at >= REARM_AFTER_TRIGGER
        ):
            vessel.is_processed = False
    return True


def arrival_reason(vessel, now: dt.datetime) -> str | None:
    """
    Lägger fartyget till just nu? REASON_SLOWING, REASON_ETA eller None.

    Saktar in: under 5 knop inne i en hamnruta, EFTER att ha setts i fart i
    samma anlöp. Utan det villkoret är varje färja som redan ligger vid kaj
    när tjänsten startar en "ankomst" -- och varje omstart skriver om dem.

    ETA: bara för ett fartyg som är i fart inne i rutan. En färja vid kaj i
    Nynäshamn bär ETA:n till Visby, inte till Nynäshamn; AIS-ETA:n gäller
    fartygets NÄSTA destination, som vi inte kan tolka från fritexten.
    """
    if vessel.is_processed or not is_passenger(vessel.ship_type) or not vessel.port_name:
        return None
    if vessel.speed_knots is not None and vessel.speed_knots < SLOW_KNOTS and vessel.was_underway:
        return REASON_SLOWING
    if (
        vessel.eta
        and vessel.was_underway
        and vessel.speed_knots is not None
        and vessel.speed_knots >= UNDERWAY_KNOTS
        and vessel.nav_status not in (NAV_AT_ANCHOR, NAV_MOORED)
        and -ETA_TRIGGER_BEHIND <= vessel.eta - now <= ETA_TRIGGER_AHEAD
    ):
        return REASON_ETA
    return None


def evaluate(vessel, now: dt.datetime) -> str | None:
    """Ankomstbeslutet, och spärren mot att ta det två gånger för samma anlöp."""
    reason = arrival_reason(vessel, now)
    if reason:
        vessel.is_processed = True
        vessel.triggered_at = now
    return reason


def buffer_position(buffer: deque | None, update: AisUpdate) -> deque:
    """
    Positioner för ett fartyg vars typ ännu inte hörts, i den ordning de kom.

    ShipStaticData kommer ungefär var sjätte minut. Tidigare sparades bara den senaste
    positionen under väntan, och en färja som saktade in innan typen hördes sågs först
    vid kaj -- aldrig i fart, alltså aldrig som ankomst. Så gav de stora färjorna noll
    ankomster 2026-09-13. Bufferten behåller de senaste positionerna inom en halvtimme,
    så att de kan spelas upp när typen kommer.
    """
    buffer = buffer if buffer is not None else deque(maxlen=PENDING_POSITIONS)
    buffer.append(update)
    newest = max(u.timestamp for u in buffer)
    while buffer and buffer[0].timestamp < newest - PENDING_WINDOW:
        buffer.popleft()
    return buffer
