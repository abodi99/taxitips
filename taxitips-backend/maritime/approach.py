"""
Färjor på väg in -- livebilden på pipeline-sidan (avsnitt 2c).

Läser fartygens senaste läge ur `ais_vessels`, som run_ais_stream skriver varje minut,
och svarar för varje stor passagerarfärja i ett inseglingsområde: är den på väg in, mot
vilken terminal, hur långt kvar, och när den är framme om den håller farten.

Reglerna, alla synliga på sidan:

* passagerarfartyg (AIS-typ 60-69) på minst MIN_LENGTH_M -- samma gräns som tipsen;
* läget högst FRESH gammalt;
* på väg in: minst MIN_KNOTS och kursen pekar mot terminalen, inom MAX_COURSE_OFF grader.
  Pekar den mot flera terminaler gäller den närmaste;
* vid kaj: i hamnrutan under BERTH_KNOTS; lägger till: i hamnrutan under MIN_KNOTS med
  kursen mot terminalen; i hamn: i hamnrutan under MIN_KNOTS åt annat håll;
* beräknad ankomst = sträcka × hamnens farledsfaktor / fart. Ingen blandning med AIS-ETA,
  som är handinmatad och gäller nästa destination; fartygets egen destination visas
  bredvid som fritext.

Positionerna är fartygens egna AIS-sändningar, inga personuppgifter.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import Counter

from core.geo import haversine_km
from maritime import ais, tips
from maritime.ports import PORTS, port_for

FRESH = dt.timedelta(minutes=15)
MIN_LENGTH_M = tips.MIN_TIP_LENGTH_M
MIN_KNOTS = ais.UNDERWAY_KNOTS
BERTH_KNOTS = 1.0
MAX_COURSE_OFF = 35.0
KNOT_KMH = 1.852

APPROACHING = "approaching"
DOCKING = "docking"
BERTHED = "berthed"
IN_PORT = "in_port"
AROUND = "around"
STATUS_LABEL = {
    APPROACHING: "på väg in", DOCKING: "lägger till", BERTHED: "vid kaj", IN_PORT: "i hamn", AROUND: "i området",
}
_ORDER = {DOCKING: 0, APPROACHING: 1, BERTHED: 2, IN_PORT: 3, AROUND: 4}


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Kompassriktningen från punkt 1 till punkt 2, 0-360 grader."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


def course_off(course: float, bearing: float) -> float:
    """Hur många grader kursen avviker från riktningen, 0-180."""
    return abs((course - bearing + 180) % 360 - 180)


def classify(vessel, now: dt.datetime) -> dict | None:
    """Ett fartyg (AisVessel eller motsvarande) -> en rad för kartan, eller None."""
    if not ais.is_passenger(vessel.ship_type) or not vessel.length_m or vessel.length_m < MIN_LENGTH_M:
        return None
    lat, lon = vessel.latitude, vessel.longitude
    if lat is None or lon is None or vessel.position_at is None or now - vessel.position_at > FRESH:
        return None
    areas = [port for port in PORTS if port.in_approach(lat, lon)]
    if not areas:
        return None

    speed, course = vessel.speed_knots, vessel.course
    in_port = port_for(lat, lon)
    status, port, off = AROUND, None, None
    if in_port is not None and (speed is None or speed < BERTH_KNOTS):
        status, port = BERTHED, in_port
    elif in_port is not None and speed < MIN_KNOTS:
        port = in_port
        off = course_off(course, bearing_deg(lat, lon, port.lat, port.lon)) if course is not None else None
        status = DOCKING if off is not None and off <= MAX_COURSE_OFF else IN_PORT
    elif speed is not None and speed >= MIN_KNOTS and course is not None:
        heading_in = []
        for candidate in areas:
            diff = course_off(course, bearing_deg(lat, lon, candidate.lat, candidate.lon))
            if diff <= MAX_COURSE_OFF:
                heading_in.append((haversine_km(lat, lon, candidate.lat, candidate.lon), diff, candidate))
        if heading_in:
            _, off, port = min(heading_in, key=lambda item: item[0])
            status = APPROACHING
    if port is None:
        port = in_port or min(areas, key=lambda p: haversine_km(lat, lon, p.lat, p.lon))

    distance = haversine_km(lat, lon, port.lat, port.lon)
    eta = None
    if status in (APPROACHING, DOCKING):
        eta = now + dt.timedelta(hours=distance * port.route_factor / (speed * KNOT_KMH))
    return {
        "mmsi": vessel.mmsi,
        "name": vessel.name or f"MMSI {vessel.mmsi}",
        "lengthM": vessel.length_m,
        "lat": lat,
        "lon": lon,
        "knots": speed,
        "course": course,
        "status": status,
        "statusLabel": STATUS_LABEL[status],
        "terminal": port.key,
        "terminalName": port.name,
        "distanceKm": round(distance, 1),
        "courseOff": round(off) if off is not None else None,
        "eta": eta.isoformat() if eta else None,
        "etaMinutes": round((eta - now).total_seconds() / 60) if eta else None,
        "destination": vessel.destination or "",
        "positionAt": vessel.position_at.isoformat(),
        "ageSeconds": round((now - vessel.position_at).total_seconds()),
    }


# Tidtabellen i livebilden: planerade anlöp från en kvart sedan till tre timmar fram.
TIMETABLE_BEHIND = dt.timedelta(minutes=15)
TIMETABLE_AHEAD = dt.timedelta(hours=3)
# Ett färjeläge i tidtabellen hör till en AIS-terminal inom så här många km -- men bara för
# rederier med färjor som AIS-bilden visar (minst MIN_LENGTH_M). SL:s pendelbåtar vid Slussen
# ligger en kilometer från Stadsgården och hade annars fått Viking Glory bredvid sig.
PORT_MATCH_KM = 1.5
LARGE_FERRY_AGENCIES = frozenset({"Destination Gotland"})
TIMETABLE_SOURCE = "GTFS Sverige 3 via Trafiklab: planerad tid, ingen realtid för färjorna"


def _nearest_port(lat: float, lon: float):
    best = min(PORTS, key=lambda p: haversine_km(lat, lon, p.lat, p.lon))
    return best if haversine_km(lat, lon, best.lat, best.lon) <= PORT_MATCH_KM else None


def timetable(now: dt.datetime) -> dict:
    """Planerade färjeanlöp per färjeläge, och nästa ankomster i tidsordning."""
    from django.db.models import Max, Q

    from maritime.models import FerryTimetableCall

    window = (now - TIMETABLE_BEHIND, now + TIMETABLE_AHEAD)
    calls = list(
        FerryTimetableCall.objects.filter(Q(arrival_at__range=window) | Q(departure_at__range=(now, window[1])))
    )
    stops: dict[str, dict] = {}
    arrivals = []
    for call in calls:
        port = _nearest_port(call.lat, call.lon) if call.agency in LARGE_FERRY_AGENCIES else None
        stop = stops.setdefault(call.stop_id, {
            "id": call.stop_id, "name": call.stop_name, "lat": call.lat, "lon": call.lon, "port": None, "next": [],
        })
        if port is not None:
            stop["port"] = port.key
        if call.arrival_at and window[0] <= call.arrival_at <= window[1]:
            stop["next"].append({"kind": "arrival", "at": call.arrival_at.isoformat(), "from": call.origin_name,
                                 "agency": call.agency, "route": call.route_name})
            arrivals.append({"at": call.arrival_at.isoformat(), "stop": call.stop_name, "from": call.origin_name,
                             "agency": call.agency, "route": call.route_name, "port": port.key if port else None,
                             "lat": call.lat, "lon": call.lon})
        if call.departure_at and now <= call.departure_at <= window[1]:
            stop["next"].append({"kind": "departure", "at": call.departure_at.isoformat(), "to": call.destination_name,
                                 "agency": call.agency, "route": call.route_name})
    for stop in stops.values():
        stop["next"].sort(key=lambda item: item["at"])
        stop["next"] = stop["next"][:6]
    arrivals.sort(key=lambda item: item["at"])
    # De stora färjorna (kopplade till en AIS-terminal) alltid med; av resten de närmaste.
    shown = sorted(
        [a for a in arrivals if a["port"]] + [a for a in arrivals if not a["port"]][:60],
        key=lambda item: item["at"],
    )
    imported = FerryTimetableCall.objects.aggregate(last=Max("imported_at"))["last"]
    return {
        "stops": sorted(stops.values(), key=lambda s: s["name"]),
        "arrivals": shown,
        "arrivalsTotal": len(arrivals),
        "importedAt": imported.isoformat() if imported else None,
        "source": TIMETABLE_SOURCE,
        "windowHours": int(TIMETABLE_AHEAD.total_seconds() // 3600),
    }


def _voyages(now: dt.datetime, ships: list[dict]) -> dict:
    from maritime import voyages

    return voyages.build(now, ships)


def _taxi(now: dt.datetime, voyage_block: dict, ships: list[dict]) -> dict:
    from maritime import relevance

    return relevance.build(now, voyage_block, ships)


def snapshot(now: dt.datetime | None = None) -> dict:
    """Allt kartan behöver: terminaler, färjor, regler och lyssnarens läge."""
    from django.utils import timezone

    from core.models import SourceStatus
    from maritime.models import AisVessel

    now = now or timezone.now()
    rows = AisVessel.objects.filter(
        latitude__isnull=False, position_at__gte=now - FRESH, ship_type__gte=60, ship_type__lte=69,
    )
    ships: list[dict] = []
    skipped: Counter = Counter()
    for vessel in rows:
        row = classify(vessel, now)
        if row is not None:
            ships.append(row)
        elif not vessel.length_m:
            skipped["unknownLength"] += 1
        elif vessel.length_m < MIN_LENGTH_M:
            skipped["short"] += 1
        else:
            skipped["outside"] += 1
    ships.sort(key=lambda s: (
        _ORDER[s["status"]], s["etaMinutes"] if s["etaMinutes"] is not None else 10**6, s["distanceKm"],
    ))
    approaching = Counter(s["terminal"] for s in ships if s["status"] in (APPROACHING, DOCKING))

    stream = SourceStatus.objects.filter(source="aisstream").first()
    return {
        "generatedAt": now.isoformat(),
        "config": {
            "freshMinutes": int(FRESH.total_seconds() // 60),
            "minLengthM": MIN_LENGTH_M,
            "minKnots": MIN_KNOTS,
            "berthKnots": BERTH_KNOTS,
            "maxCourseOff": MAX_COURSE_OFF,
        },
        "terminals": [
            {
                "key": port.key, "name": port.name, "lat": port.lat, "lon": port.lon,
                "box": port.bounding_box, "approach": port.approach_box, "tips": port.tips,
                "note": port.note, "routeFactor": port.route_factor, "approaching": approaching.get(port.key, 0),
            }
            for port in PORTS
        ],
        "ships": ships,
        "timetable": timetable(now),
        # Tidtabellens turer kopplade till AIS -- se maritime/voyages.py.
        "voyages": (voyage_block := _voyages(now, ships)),
        # Urvalet för taxiföraren -- se maritime/relevance.py.
        "taxi": _taxi(now, voyage_block, ships),
        "counts": dict(Counter(s["status"] for s in ships)),
        "skipped": dict(skipped),
        "stream": {
            "ok": stream.ok,
            "checkedAt": stream.checked_at.isoformat() if stream.checked_at else None,
            "connected": (stream.detail or {}).get("connected"),
        } if stream else None,
    }
