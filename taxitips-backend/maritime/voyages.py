"""
Färjeturer i tidtabellen kopplade till AIS: var färjan är, planerad ankomst, beräknad
ankomst och avvikelse. Visas på pipeline-vyns sida /farjor.

Tidtabellen (GTFS Sverige 3, maritime/timetable.py) säger vilka turer som pågår och när de
ska vara framme, men inte var färjan är: Trafiklab har ingen realtid för färjorna. AIS säger
var fartygen är, men inte vilken tur de kör. Kopplingen görs per tur:

1. Tidtabellen ger turens förväntade position just nu: rak linje mellan senaste och nästa
   hamn, i proportion till tiden.
2. Kandidater är passagerarfartyg (AIS-typ 60-69, eller okänd typ med klass A-transponder,
   som små linjefärjor ofta har) med position högst MAX_AGE gammal:
   * före avgång: vid avgångshamnen (inom BERTH_KM);
   * på väg: inom max(MIN_TOLERANCE_KM, TOLERANCE_SHARE av sträckan) från förväntad
     position, och om fartyget rör sig ska kursen peka mot nästa hamn (inom COURSE_TOL);
   * framme enligt tidtabellen: vid ankomsthamnen.
3. Närmast först: ett fartyg per tur och en tur per fartyg.

AIS-beräknad ankomst: kvarvarande sträcka (till nästa hamn och sedan hamn för hamn) ×
ROUTE_FACTOR / farten, plus tidtabellens uppehåll i hamnarna däremellan. Ligger färjan kvar
i avgångshamnen efter avgångstiden räknas resten av turen från nu. Avvikelse = beräknad
minus planerad ankomst.

Kopplingen är en slutsats, inte en identitet: tidtabellen anger inget fartyg. Varje rad bär
avståndet mellan förväntad och faktisk position, så att en tveksam koppling syns. Turer vars
förväntade position ligger utanför AIS-prenumerationens områden kan inte kopplas alls.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict

from core.geo import haversine_km
from maritime.ports import PORTS

MAX_AGE = dt.timedelta(minutes=10)
DEPART_SOON = dt.timedelta(minutes=15)
ARRIVED_KEEP = dt.timedelta(minutes=10)
BERTH_KM = 0.6
# Stora färjor lägger till vid en terminal; tidtabellens hållplats ("Oskarshamn station") kan
# ligga en bit bort.
BIG_BERTH_KM = 1.5
BIG_AGENCIES = frozenset({"Destination Gotland"})
# Skärgårdsbåtarna är under 70 m; ett längre fartyg (kryssare, utrikesfärja) är aldrig en sådan tur.
BIG_VESSEL_M = 100
MIN_TOLERANCE_KM = 2.0
TOLERANCE_SHARE = 0.35
COURSE_TOL = 50.0
MOVING_KNOTS = 3.0
STILL_KNOTS = 1.0
ROUTE_FACTOR = 1.15
KNOT_KMH = 1.852
LATE_MINUTES = 5

BEFORE, ENROUTE, ARRIVED = "before", "enroute", "arrived"


def _bearing(lat1, lon1, lat2, lon2):
    from maritime.approach import bearing_deg

    return bearing_deg(lat1, lon1, lat2, lon2)


def _course_off(course, bearing):
    from maritime.approach import course_off

    return course_off(course, bearing)


def _km(a, b) -> float:
    return haversine_km(a[0], a[1], b[0], b[1])


def _point(call) -> tuple[float, float]:
    return call.lat, call.lon


def _in_coverage(lat: float, lon: float) -> bool:
    return any(port.in_approach(lat, lon) for port in PORTS)


def usable_vessel(vessel) -> bool:
    return (vessel.ship_type is not None and 60 <= vessel.ship_type <= 69) or (
        vessel.ship_type is None and vessel.ais_class == "A"
    )


def schedule_state(calls: list, now: dt.datetime) -> dict:
    """Var turen ska vara enligt tidtabellen: fas, nästa hamn och förväntad position."""
    first, last = calls[0], calls[-1]
    if now <= first.departure_at:
        return {"phase": BEFORE, "next": 1, "expected": _point(first), "legKm": _km(_point(first), _point(calls[1]))}
    if now >= last.arrival_at:
        return {"phase": ARRIVED, "next": len(calls) - 1, "expected": _point(last), "legKm": 0.0}
    for i in range(len(calls) - 1):
        a, b = calls[i], calls[i + 1]
        leaves = a.departure_at or a.arrival_at
        arrives = b.arrival_at or b.departure_at
        if leaves <= now <= arrives:
            span = max((arrives - leaves).total_seconds(), 1.0)
            share = (now - leaves).total_seconds() / span
            expected = (a.lat + (b.lat - a.lat) * share, a.lon + (b.lon - a.lon) * share)
            return {"phase": ENROUTE, "next": i + 1, "expected": expected, "legKm": _km(_point(a), _point(b))}
        if b.arrival_at and b.departure_at and b.arrival_at <= now <= b.departure_at:
            # Uppehåll i en mellanhamn.
            return {"phase": ENROUTE, "next": i + 2, "expected": _point(b), "legKm": _km(_point(b), _point(calls[i + 2]))}
    return {"phase": ENROUTE, "next": len(calls) - 1, "expected": _point(last), "legKm": 0.0}


def _remaining(calls: list, next_index: int, position: tuple[float, float]) -> tuple[float, dt.timedelta]:
    """Sträcka kvar (km) från position via nästa hamn till slutet, och uppehållen däremellan."""
    km = _km(position, _point(calls[next_index]))
    dwell = dt.timedelta()
    for j in range(next_index, len(calls) - 1):
        km += _km(_point(calls[j]), _point(calls[j + 1]))
        if calls[j].arrival_at and calls[j].departure_at:
            dwell += calls[j].departure_at - calls[j].arrival_at
    return km, dwell


def _berth_km(calls: list) -> float:
    return BIG_BERTH_KM if calls[0].agency in BIG_AGENCIES else BERTH_KM


def _candidate_km(trip: dict, vessel) -> float | None:
    """Avstånd för kopplingen, eller None om fartyget inte kan vara turens."""
    calls, state = trip["calls"], trip["state"]
    if calls[0].agency not in BIG_AGENCIES and (vessel.length_m or 0) >= BIG_VESSEL_M:
        return None
    here = (vessel.latitude, vessel.longitude)
    berth = _berth_km(calls)
    if state["phase"] == BEFORE:
        km = _km(here, _point(calls[0]))
        return km if km <= berth else None
    if state["phase"] == ARRIVED:
        km = _km(here, _point(calls[-1]))
        return km if km <= berth else None
    km = _km(here, state["expected"])
    if km > max(MIN_TOLERANCE_KM, TOLERANCE_SHARE * state["legKm"]):
        return None
    if vessel.speed_knots is not None and vessel.speed_knots >= MOVING_KNOTS:
        target = _point(calls[state["next"]])
        if vessel.course is None or _course_off(vessel.course, _bearing(*here, *target)) > COURSE_TOL:
            return None
    return km


def ais_eta(trip: dict, vessel, now: dt.datetime) -> tuple[dt.datetime | None, str]:
    """
    AIS-beräknad ankomst till slutdestinationen, och hur den räknades. None när färjan redan
    ligger vid kaj efter planerad tid: när den lade till vet vi inte, och en avvikelse räknad
    från nu hade växt varje minut.
    """
    calls = trip["calls"]
    first, last = calls[0], calls[-1]
    here = (vessel.latitude, vessel.longitude)
    speed = vessel.speed_knots
    still = speed is None or speed < STILL_KNOTS
    # En rundtur börjar och slutar i samma hamn: före avgång ligger den i avgångshamnen.
    berth = _berth_km(calls)
    if still and _km(here, _point(last)) <= berth and trip["state"]["phase"] != BEFORE:
        return (now, "framme före planerad tid") if now < last.arrival_at else (None, "framme")
    if (speed is None or speed < MOVING_KNOTS) and _km(here, _point(first)) <= berth:
        start = max(now, first.departure_at)
        return start + (last.arrival_at - first.departure_at), "ligger kvar i avgångshamnen"
    if speed is not None and speed >= STILL_KNOTS:
        km, dwell = _remaining(calls, trip["state"]["next"], here)
        basis = "sträcka och fart" if speed >= MOVING_KNOTS else "lägger till, sträcka och låg fart"
        return now + dt.timedelta(hours=km * ROUTE_FACTOR / (speed * KNOT_KMH)) + dwell, basis
    # Långsam ute på turen, t.ex. i en mellanhamn: tidtabellens resterande tid från nästa avgång.
    nxt = calls[trip["state"]["next"]]
    leaves = nxt.departure_at or nxt.arrival_at
    return max(now, leaves) + (last.arrival_at - leaves), "uppehåll, tidtabellens resterande tid"


def active_trips(now: dt.datetime) -> list[dict]:
    from django.utils import timezone

    from maritime.models import FerryTimetableCall

    today = timezone.localtime(now).date()
    groups: dict[tuple, list] = defaultdict(list)
    for call in FerryTimetableCall.objects.filter(service_date__in=[today - dt.timedelta(days=1), today]).order_by(
        "service_date", "trip_id", "sequence",
    ):
        groups[(call.service_date, call.trip_id)].append(call)
    trips = []
    for (day, trip_id), calls in groups.items():
        if len(calls) < 2 or calls[0].departure_at is None or calls[-1].arrival_at is None:
            continue
        if calls[0].departure_at > now + DEPART_SOON or calls[-1].arrival_at < now - ARRIVED_KEEP:
            continue
        trips.append({"key": f"{day}:{trip_id}", "calls": calls, "state": schedule_state(calls, now)})
    return trips


def build(now: dt.datetime, approach_ships: list[dict] | None = None) -> dict:
    """Turerna som pågår enligt tidtabellen, med AIS-koppling, och stora färjor utan tidtabell."""
    from maritime.models import AisVessel

    trips = active_trips(now)
    vessels = [v for v in AisVessel.objects.filter(latitude__isnull=False, position_at__gte=now - MAX_AGE) if usable_vessel(v)]

    pairs = []
    for index, trip in enumerate(trips):
        for vessel in vessels:
            km = _candidate_km(trip, vessel)
            if km is not None:
                pairs.append((km, index, vessel))
    pairs.sort(key=lambda item: item[0])
    matched: dict[int, tuple[float, object]] = {}
    taken: set[int] = set()
    for km, index, vessel in pairs:
        if index in matched or vessel.mmsi in taken:
            continue
        matched[index] = (km, vessel)
        taken.add(vessel.mmsi)

    rows = []
    for index, trip in enumerate(trips):
        calls, state = trip["calls"], trip["state"]
        first, last = calls[0], calls[-1]
        row = {
            "key": trip["key"],
            "agency": first.agency,
            "route": first.route_name,
            "from": first.stop_name,
            "to": last.stop_name,
            "toLat": last.lat,
            "toLon": last.lon,
            "stops": len(calls),
            "plannedDeparture": first.departure_at.isoformat(),
            "plannedArrival": last.arrival_at.isoformat(),
            "phase": state["phase"],
            "expected": {"lat": state["expected"][0], "lon": state["expected"][1]},
            "inCoverage": _in_coverage(*state["expected"]),
            "vessel": None,
        }
        if index in matched:
            km, vessel = matched[index]
            eta, basis = ais_eta(trip, vessel, now)
            remaining, _ = _remaining(calls, state["next"], (vessel.latitude, vessel.longitude))
            row.update({
                "status": "matched",
                "vessel": {
                    "name": vessel.name or f"MMSI {vessel.mmsi}", "mmsi": vessel.mmsi, "lengthM": vessel.length_m,
                    "lat": vessel.latitude, "lon": vessel.longitude, "knots": vessel.speed_knots,
                    "course": vessel.course, "ageSeconds": round((now - vessel.position_at).total_seconds()),
                },
                "matchKm": round(km, 2),
                "remainingKm": round(remaining * ROUTE_FACTOR, 1),
                "aisEta": eta.isoformat() if eta else None,
                "etaBasis": basis,
                "delayMinutes": round((eta - last.arrival_at).total_seconds() / 60) if eta else None,
            })
        else:
            row["status"] = "no_match" if row["inCoverage"] else "no_coverage"
        rows.append(row)
    rows.sort(key=lambda r: r["plannedArrival"])

    ais_only = [
        s for s in (approach_ships or [])
        if s["mmsi"] not in taken and s["status"] in ("approaching", "docking", "berthed")
    ]
    delays = [r["delayMinutes"] for r in rows if r["status"] == "matched" and r["delayMinutes"] is not None]
    return {
        "trips": rows,
        "aisOnly": ais_only,
        "summary": {
            "trips": len(rows),
            **Counter(r["status"] for r in rows),
            "late": sum(1 for d in delays if d > LATE_MINUTES),
            "early": sum(1 for d in delays if d < -LATE_MINUTES),
            "aisOnly": len(ais_only),
        },
        "rules": {
            "maxAgeMinutes": int(MAX_AGE.total_seconds() // 60),
            "berthKm": BERTH_KM,
            "minToleranceKm": MIN_TOLERANCE_KM,
            "toleranceShare": TOLERANCE_SHARE,
            "courseTol": COURSE_TOL,
            "routeFactor": ROUTE_FACTOR,
            "lateMinutes": LATE_MINUTES,
        },
    }
