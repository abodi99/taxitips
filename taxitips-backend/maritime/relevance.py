"""
Färjeankomsterna för taxiföraren -- slutprodukten på sidan /farjor.

Principen: visa så mycket som möjligt och låt föraren avgöra. Bara det som inte är en känd
ankomst tas bort, och varje borttagning redovisas (`funnel`):

- dubbletter (samma tur två gånger i tidtabellen, eller ett AIS-fartyg som är samma ankomst som
  en tidtabellstur),
- utanför tidsfönstret (hämtningen är över, eller ankomsten är mer än WINDOW_AHEAD bort),
- stora fartyg vid kaj som AIS inte sett komma in: de kan lika gärna vara på väg ut.

Allt annat visas, med en sort (`kind`, se KINDS) och kännetecken (`traits`): vägfärja, rundtur,
pendelbåt, öbåt, stor färja, pendelfärja; ingen bilväg vid bryggan, buss eller spårvagn i båda
ändar, sen enligt AIS. Sorten säger varför en ankomst oftare eller mer sällan ger körningar, men
föraren väljer själv vad som ska synas.

Varje ankomst får förväntad tid (AIS när färjan är kopplad, annars tidtabellen), hämtningsfönster
och var föraren ska stå. AIS skiljer inte färja från kryssningsfartyg, och var ett fartyg utan
tidtabell kommer ifrån står inte i AIS: det sägs rakt ut i stället för att gissas. Antal
passagerare finns inte i någon källa och påstås aldrig; fartygets längd är det enda storleksmåttet.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict

from core.geo import haversine_km
from maritime.ports import PORTS, by_key

WINDOW_AHEAD = dt.timedelta(hours=3)
MIN_CROSSING_KM = 3.0
# Båt mellan två platser med buss eller spårvagn, kortare än så: pendelbåt i stan.
COMMUTER_KM = 8.0
# En AIS-färja utan tidtabellstur är samma ankomst som en tidtabellstur inom så här långt och länge.
SAME_ARRIVAL_KM = 3.0
SAME_ARRIVAL = dt.timedelta(minutes=30)
BIG_M = 100
BIG_AGENCIES = frozenset({"Destination Gotland"})
ROAD_FERRY_AGENCIES = frozenset({"Trafikverket"})
# Pendelfärjor: går hela dagen, med gående resenärer. Motparten enligt hamnregistret (ports.py,
# Trafikanalys: "den turtäta linjen Helsingborg–Helsingör").
PENDULUM_FROM = {"helsingborg": "Helsingør"}
# Hur fort en färja på väg in antas gå när vi räknar hur långt före ankomsten AIS ser den.
REACH_KNOTS = 18
# Stora färjor: folk går av med bagage en stund efter att färjan lagt till. Övriga: direkt.
PICKUP = {"big": (dt.timedelta(minutes=10), dt.timedelta(minutes=45)),
          "small": (dt.timedelta(minutes=0), dt.timedelta(minutes=15))}
LATE_MINUTES = 5
EXAMPLES = 8

# Det enda som tas bort: sådant som inte är en känd ankomst.
RULES = {
    "duplicate": "Samma ankomst två gånger: dubbla turer i tidtabellen, eller samma färja i både tidtabell och AIS",
    "outside_window": "Utanför tidsfönstret: hämtningen är över eller ankomsten är mer än 3 timmar bort",
    "berthed_unknown": "Ligger vid kaj utan sedd ankomst: kan vara på väg ut, inte in",
}

# Sorterna, i den ordning sidan visar dem: namn och varför de oftare eller mer sällan ger körningar.
KINDS = {
    "big": ("Stor färja", "Gotlandsfärjorna och passagerarfartyg på minst 100 m. Många kliver av, ofta med bagage och utan bil."),
    "pendulum": ("Pendelfärja", "Helsingborg–Helsingør hela dagen: en jämn ström av gående, färre per ankomst."),
    "island": ("Öbåt", "Båtar från öar och längre skärgårdsturer: resenärerna behöver ta sig vidare från hamnen."),
    "commuter": ("Pendelbåt", f"Kortare än {MIN_CROSSING_KM:g} km, eller under {COMMUTER_KM:g} km med buss eller spårvagn"
                              " i båda ändar. Många åker kollektivt vidare, men inte alla."),
    "loop": ("Rundtur", "Samma brygga som start och mål, ofta turister som kliver av där de klev på."),
    "road": ("Vägfärja", "Trafikverkets bilfärjor. De flesta kör egen bil av, men gående resenärer finns."),
}

TRAITS = {
    "no_road": "Ingen buss, spårvagn eller tåg inom 600 m från bryggan: troligen bilfri ö, kolla att taxin når fram",
    "transit_both": "Buss eller spårvagn vid båda bryggorna",
    "late": "Sen enligt AIS",
}

NOT_ARRIVING = "Ankommer inte inom fönstret (från 45 minuter sedan till 3 timmar framåt), så den visas inte än"


def agency_label(agency: str) -> str:
    """GTFS Sverige 3 har rederier vars namn bara är ett nummer ("114")."""
    return f"rederi utan namn i tidtabellen (nr {agency})" if agency.isdigit() else agency


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value else None


def _clock(value: dt.datetime) -> str:
    from django.utils import timezone

    return timezone.localtime(value).strftime("%H:%M")


def _timetable_candidates(now: dt.datetime) -> list[dict]:
    """Turer vars sista anlöp (ankomsten) ligger i fönstret, med första anlöpet som ursprung."""
    from maritime.models import FerryTimetableCall

    lasts = list(FerryTimetableCall.objects.filter(
        departure_at__isnull=True,
        arrival_at__gte=now - PICKUP["big"][1],
        arrival_at__lte=now + WINDOW_AHEAD,
    ))
    if not lasts:
        return []
    firsts: dict[tuple, object] = {}
    for call in FerryTimetableCall.objects.filter(
        trip_id__in={c.trip_id for c in lasts}, service_date__in={c.service_date for c in lasts}, arrival_at__isnull=True,
    ):
        firsts[(call.service_date, call.trip_id)] = call
    out = []
    for last in lasts:
        first = firsts.get((last.service_date, last.trip_id))
        if first is not None:
            out.append({"key": f"{last.service_date}:{last.trip_id}", "first": first, "last": last})
    return out


def _dist(km: float | None) -> str:
    if km is None:
        return "okänt avstånd"
    if km < 1:
        return f"{max(10, round(km * 100) * 10)} m"
    return f"{km:.1f} km".replace(".", ",")


def _num(value) -> str:
    return "okänd" if value is None else f"{value:.1f}".replace(".", ",")


def _examples(rows: list[dict]) -> list[dict]:
    """De vanligaste borttagna turerna, en rad per sträcka med antal."""
    counts = Counter(row["title"] for row in rows)
    detail = {}
    for row in rows:
        detail.setdefault(row["title"], row["detail"])
    return [{"title": title, "detail": detail[title], "count": n} for title, n in counts.most_common(EXAMPLES)]


def _pickup(kind: str) -> tuple[dt.timedelta, dt.timedelta]:
    return PICKUP["big"] if kind == "big" else PICKUP["small"]


def _window(kind: str, expected: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    start, end = _pickup(kind)
    return expected + start, expected + end


def _kind(first, last, crossing: float, vessel: dict | None) -> tuple[str, str]:
    """Turens sort och en mening om varför, för föraren."""
    length = (vessel or {}).get("lengthM") or 0
    if first.agency in ROAD_FERRY_AGENCIES:
        return "road", f"Vägfärja ({first.agency}): de flesta kör egen bil av, men gående resenärer finns"
    if first.stop_id == last.stop_id or first.stop_name == last.stop_name:
        return "loop", f"Rundtur: {first.stop_name} är både start och mål, resenärerna kliver av där de klev på"
    if first.agency in BIG_AGENCIES or length >= BIG_M:
        return "big", f"Stor färja{f' ({length} m)' if length else ''}: många kliver av, ofta utan bil"
    if crossing < MIN_CROSSING_KM or (first.stop_has_road and last.stop_has_road and crossing < COMMUTER_KM):
        return "commuter", f"Pendelbåt, {_dist(crossing)} fågelvägen: många går eller åker kollektivt vidare, men inte alla"
    if not first.stop_has_road:
        return "island", f"Öbåt från {first.stop_name}, utan buss eller bilväg: resenärerna behöver ta sig vidare härifrån"
    return "island", f"Båtresa på {_dist(crossing)} fågelvägen: resenärerna behöver ta sig vidare från hamnen"


def _reach(port) -> tuple[float, int]:
    """Hur långt ut AIS ser ett fartyg på väg in (inseglingsområdets bortersta kant), och ungefär hur
    många minuter före ankomsten det är i REACH_KNOTS."""
    south, west, north, east = port.approach_bounds
    km = max(haversine_km(port.lat, port.lon, lat, lon)
             for lat, lon in ((south, port.lon), (north, port.lon), (port.lat, west), (port.lat, east)))
    return km, round(km * port.route_factor / (REACH_KNOTS * 1.852) * 60)


def _ports(now: dt.datetime, items: list[dict], ships: list[dict]) -> list[dict]:
    """Varje AIS-hamn, även när inget är på väg in: vad som händer där och varför listan är tom."""
    from maritime.models import FerryArrival

    last: dict[str, object] = {}
    by_ship: dict[int, object] = {}
    for arrival in FerryArrival.objects.filter(
        triggered_at__gte=now - dt.timedelta(days=2), length_m__gte=BIG_M, port_name__in=[p.name for p in PORTS],
    ).order_by("-triggered_at"):
        last.setdefault(arrival.port_name, arrival)
        by_ship.setdefault(arrival.mmsi, arrival)
    out = []
    for port in PORTS:
        # Bara stora fartyg och pendelfärjan: öbåtar till en brygga i närheten (Strömkajen vid
        # Stadsgården) hör inte till färjeterminalen.
        here = [i for i in items if i["kind"] in ("big", "pendulum")
                and haversine_km(i["terminal"]["lat"], i["terminal"]["lon"], port.lat, port.lon) <= SAME_ARRIVAL_KM]
        near = [s for s in ships if s.get("terminal") == port.key and (s.get("lengthM") or 0) >= BIG_M]
        reach_km, reach_min = _reach(port)
        notes = []
        for ship in near:
            if any((i.get("vessel") or {}).get("name") == ship["name"] for i in here):
                continue
            arrived = by_ship.get(ship["mmsi"])
            if ship["status"] == "berthed" and arrived is not None and arrived.port_name == port.name:
                window = _pickup("pendulum" if port.key in PENDULUM_FROM else "big")
                notes.append(f"{ship['name']} lade till {_clock(arrived.triggered_at)}; hämtningen var"
                             f" {_clock(arrived.triggered_at + window[0])}–{_clock(arrived.triggered_at + window[1])}"
                             " och är över.")
            elif ship["status"] == "berthed":
                notes.append(f"{ship['name']} ligger vid kaj, men AIS har inte sett den komma in: den kan lika gärna"
                             " vara på väg ut.")
            elif ship["status"] in ("approaching", "docking"):
                notes.append(f"{ship['name']} är på väg in men utanför tidsfönstret eller utan beräknad ankomst.")
            elif ship["status"] == "in_port":
                notes.append(f"{ship['name']} är i hamnen men inte vid terminalen.")
            else:
                notes.append(f"{ship['name']} är i området men inte på väg in mot terminalen.")
        seen = last.get(port.name)
        if seen is not None:
            notes.append(f"Senaste stora ankomst: {seen.ship_name} {_clock(seen.triggered_at)}"
                         + ("" if timezone_date(seen.triggered_at) == timezone_date(now) else " (i går eller tidigare)")
                         + ".")
        else:
            notes.append("AIS-lyssnaren har inte registrerat någon stor ankomst här de senaste två dygnen.")
        if not here and port.key in PENDULUM_FROM:
            notes.append(f"Pendelfärjan till {PENDULUM_FROM[port.key]} går hela dagen. Nästa ankomst syns här när AIS ser"
                         f" färjan på väg in, ungefär {reach_min} min före.")
        out.append({
            "key": port.key,
            "name": port.name,
            "lat": port.lat,
            "lon": port.lon,
            "arrivals": [i["id"] for i in here],
            "next": ({"at": here[0]["expectedAt"], "headline": here[0]["headline"]} if here else None),
            "pendulum": port.key in PENDULUM_FROM,
            "notes": notes,
            "reachKm": round(reach_km),
            "reachMinutes": reach_min,
            "note": port.note,
        })
    return out


def timezone_date(value: dt.datetime) -> dt.date:
    from django.utils import timezone

    return timezone.localtime(value).date()


def build(now: dt.datetime, voyages: dict, ships: list[dict] | None = None) -> dict:
    """Ankomsterna för taxiföraren, och vad varje regel tog bort."""
    from maritime.models import FerryArrival

    trips_by_key = {trip["key"]: trip for trip in voyages.get("trips", [])}
    removed: dict[str, list] = defaultdict(list)
    items: list[dict] = []

    seen: set[tuple] = set()

    # Beslut per tur (tidtabellens nyckel, eller "ais:<mmsi>"): med, eller vilken regel som tog bort den.
    decisions: dict[str, dict] = {}

    def drop(rule: str, title: str, detail: str = "", key: str | None = None) -> None:
        removed[rule].append({"title": title, "detail": detail})
        if key:
            decisions[key] = {"kept": False, "rule": rule, "label": RULES[rule], "detail": detail}

    # 1. Tidtabellens ankomster (GTFS Sverige 3), med AIS när turen är kopplad.
    for cand in _timetable_candidates(now):
        first, last = cand["first"], cand["last"]
        title = f"{first.stop_name} → {last.stop_name}"
        crossing = haversine_km(first.lat, first.lon, last.lat, last.lon)
        same = (last.stop_name, first.stop_name, last.arrival_at)
        if same in seen:
            drop("duplicate", title, f"samma ankomst {_clock(last.arrival_at)} finns redan", key=cand["key"])
            continue
        seen.add(same)
        trip = trips_by_key.get(cand["key"])
        vessel = (trip or {}).get("vessel") if trip and trip.get("status") == "matched" else None
        kind, kind_note = _kind(first, last, crossing, vessel)
        planned = last.arrival_at
        if vessel and trip.get("aisEta"):
            expected = dt.datetime.fromisoformat(trip["aisEta"])
            basis = f"AIS: {trip['etaBasis']}"
        else:
            expected = planned
            basis = "framme enligt AIS, tid enligt tidtabellen" if vessel else "tidtabell (ingen AIS-position)"
        pickup_from, pickup_until = _window(kind, expected)
        if pickup_until < now or expected > now + WINDOW_AHEAD:
            drop("outside_window", title, f"ankomst {_clock(expected)}", key=cand["key"])
            continue
        delay = trip.get("delayMinutes") if vessel else None
        traits = []
        if not last.stop_has_road:
            traits.append("no_road")
        if first.stop_has_road and last.stop_has_road:
            traits.append("transit_both")
        if delay is not None and delay > LATE_MINUTES:
            traits.append("late")
        why = [kind_note]
        if "no_road" in traits:
            why.append(f"Ingen buss, spårvagn eller tåg inom 600 m från {last.stop_name}: troligen bilfri ö, kolla att taxin når fram")
        if "late" in traits:
            why.append(f"Sen enligt AIS: +{delay} min, hämtningen flyttas lika mycket")
        why.append(f"Hämtning {_clock(pickup_from)}–{_clock(pickup_until)} vid {last.stop_name}")
        calc = [f"Planerad ankomst {_clock(planned)} enligt tidtabellen (GTFS Sverige 3)."]
        if vessel:
            calc.append(f"AIS-fartyget {vessel['name']} ligger {_dist(trip['matchKm'])} från där tidtabellen säger att färjan ska vara.")
            if trip.get("aisEta"):
                calc.append(f"{trip['etaBasis'].capitalize()}: {_dist(trip.get('remainingKm'))} kvar → {_clock(expected)}"
                            f" ({'+' if (delay or 0) >= 0 else ''}{delay} min mot planerad).")
            else:
                calc.append("Ligger redan vid kaj efter planerad tid; när den lade till vet vi inte.")
        else:
            calc.append("Ingen AIS-position kopplad: tiden är tidtabellens.")
        calc.append(f"Hämtningsfönster: ankomst + {int(_pickup(kind)[0].total_seconds() // 60)}–"
                    f"{int(_pickup(kind)[1].total_seconds() // 60)} min.")
        items.append({
            "id": f"tt:{cand['key']}",
            "source": "tidtabell + AIS" if vessel else "tidtabell",
            "kind": kind,
            "kindLabel": KINDS[kind][0],
            "traits": traits,
            "terminal": {"name": last.stop_name, "lat": last.lat, "lon": last.lon},
            "from": first.stop_name,
            "headline": f"Från {first.stop_name} till {last.stop_name}",
            "direction": f"Kommer in till {last.stop_name}; avgick från {first.stop_name} {_clock(first.departure_at)}"
                         if first.departure_at else f"Kommer in till {last.stop_name}",
            "international": False,
            "agency": agency_label(first.agency),
            "route": first.route_name,
            "vessel": vessel,
            "plannedAt": _iso(planned),
            "plannedDeparture": _iso(first.departure_at),
            "expectedAt": _iso(expected),
            "expectedBasis": basis,
            "delayMinutes": delay,
            "arrived": expected <= now,
            "pickupFrom": _iso(pickup_from),
            "pickupUntil": _iso(pickup_until),
            "why": why,
            "calc": calc,
            "crossingKm": round(crossing, 1),
            "origin": {"name": first.stop_name, "lat": first.lat, "lon": first.lon},
            "remainingKm": trip.get("remainingKm") if vessel else None,
            "matchKm": trip.get("matchKm") if vessel else None,
            "aisDestination": "",
        })

    # 2. Stora färjor som AIS ser men som inte finns i tidtabellen (utrikesfärjorna).
    arrivals = {
        a.mmsi: a for a in FerryArrival.objects.filter(
            triggered_at__gte=now - dt.timedelta(hours=6), length_m__gte=BIG_M,
        )
    }
    for ship in voyages.get("aisOnly", []):
        ais_key = f"ais:{ship['mmsi']}"
        port = by_key(ship["terminal"])
        title = f"{ship['name']} → {ship['terminalName']}"
        origin = PENDULUM_FROM.get(port.key, "")
        kind = "pendulum" if origin else "big"
        if ship["status"] == "berthed":
            seen = arrivals.get(ship["mmsi"])
            if seen is None or seen.port_name != port.name:
                drop("berthed_unknown", title, port.name, key=ais_key)
                continue
            if seen.triggered_at + _pickup(kind)[1] < now:
                drop("outside_window", title, f"anlände {_clock(seen.triggered_at)}", key=ais_key)
                continue
            expected, basis = seen.triggered_at, f"AIS: anlände {_clock(seen.triggered_at)}"
        else:
            if not ship.get("eta"):
                drop("outside_window", title, "ingen beräknad ankomst", key=ais_key)
                continue
            expected = dt.datetime.fromisoformat(ship["eta"])
            basis = "AIS: sträcka till terminalen × farledsfaktor / fart"
        pickup_from, pickup_until = _window(kind, expected)
        if pickup_until < now or expected > now + WINDOW_AHEAD:
            drop("outside_window", title, f"ankomst {_clock(expected)}", key=ais_key)
            continue
        twin = next((
            i for i in items
            if i["kind"] == "big" and not i["international"]
            and haversine_km(i["terminal"]["lat"], i["terminal"]["lon"], port.lat, port.lon) <= SAME_ARRIVAL_KM
            and abs(dt.datetime.fromisoformat(i["expectedAt"]) - expected) <= SAME_ARRIVAL
        ), None)
        if twin is not None:
            drop("duplicate", title, f"samma som {twin['headline']} {_clock(dt.datetime.fromisoformat(twin['expectedAt']))}", key=ais_key)
            continue
        heading_in = ship["status"] != "berthed"
        if origin:
            why_first = (f"Pendelfärjan {port.city}–{origin} går hela dagen: en jämn ström av gående resenärer vid"
                         f" {port.name}, men färre per ankomst än med en stor färja")
            where_from = (f"Linjen {port.city}–{origin} finns inte i svensk tidtabell: bara AIS. Att den kommer från"
                          f" {origin} står i hamnregistret (Trafikanalys), inte i AIS.")
        else:
            why_first = f"Passagerarfartyg på {ship['lengthM']} m till {port.name}: många kliver av, ofta utan bil"
            where_from = ("Finns inte i den svenska tidtabellen (GTFS Sverige 3 saknar utrikesfärjor och kryssningsfartyg):"
                          " bara AIS. AIS säger passagerarfartyg, inte om det är en färja eller ett kryssningsfartyg.")
        items.append({
            "id": f"ais:{ship['mmsi']}",
            "source": "AIS",
            "kind": kind,
            "kindLabel": "Pendelfärja" if origin else "Stort passagerarfartyg",
            "traits": [],
            "terminal": {"name": port.name, "lat": port.lat, "lon": port.lon},
            "from": origin,
            "headline": (f"Till {port.name} från {origin}" if origin
                         else f"Till {port.name}, ursprung okänt (utrikesfärja eller kryssning)"),
            "direction": (f"På väg in mot {port.name}: {_dist(ship['distanceKm'])} kvar och kursen pekar mot terminalen"
                          if heading_in else f"Lade till i {port.name} {_clock(expected)} (AIS såg den komma in)"),
            "international": True,
            "agency": "",
            "route": "",
            "vessel": {
                "name": ship["name"], "lengthM": ship["lengthM"], "lat": ship["lat"], "lon": ship["lon"],
                "knots": ship["knots"], "course": ship["course"], "ageSeconds": ship["ageSeconds"],
            },
            "plannedAt": None,
            "plannedDeparture": None,
            "expectedAt": _iso(expected),
            "expectedBasis": basis,
            "delayMinutes": None,
            "arrived": expected <= now,
            "pickupFrom": _iso(pickup_from),
            "pickupUntil": _iso(pickup_until),
            "why": [
                why_first,
                f"Hämtning {_clock(pickup_from)}–{_clock(pickup_until)} vid terminalen",
            ],
            "calc": [
                where_from,
                (f"{_dist(ship['distanceKm'])} till terminalen i {_num(ship['knots'])} knop, farledsfaktor {_num(port.route_factor)}."
                 if ship["status"] != "berthed" else "AIS såg färjan sakta in och lägga till i hamnen."),
                "Riktningen syns i AIS: den räknas bara om kursen pekar in mot terminalen, eller om AIS såg den"
                " sakta in och lägga till.",
            ],
            "crossingKm": None,
            "origin": None,
            "remainingKm": ship["distanceKm"] if heading_in else None,
            "matchKm": None,
            "portNote": port.note,
            "aisDestination": ship.get("destination") or "",
        })

    order = list(KINDS)
    items.sort(key=lambda item: (item["expectedAt"], order.index(item["kind"])))
    for item in items:
        key = item["id"].removeprefix("tt:")
        decisions[key] = {"kept": True, "rule": None, "label": f"Med, som {item['kindLabel'].lower()}",
                          "detail": item["id"]}
    # Pågående turer som aldrig var en ankomst i fönstret (t.ex. Gotlandsfärjan som just lagt ut).
    for trip in voyages.get("trips", []):
        decisions.setdefault(trip["key"], {
            "kept": False, "rule": "not_arriving",
            "label": NOT_ARRIVING,
            "detail": f"planerad ankomst {_clock(dt.datetime.fromisoformat(trip['plannedArrival']))}",
        })
    kept_ids = len(items)
    total_removed = sum(len(v) for v in removed.values())
    return {
        "items": items,
        "summary": {
            "arrivals": kept_ids,
            "kinds": dict(Counter(i["kind"] for i in items)),
            "noRoad": sum(1 for i in items if "no_road" in i["traits"]),
            "late": sum(1 for i in items if (i["delayMinutes"] or 0) > LATE_MINUTES),
            "removed": total_removed,
        },
        "decisions": decisions,
        "ports": _ports(now, items, ships or []),
        "kinds": [{"kind": k, "label": label, "explain": explain} for k, (label, explain) in KINDS.items()],
        "traits": TRAITS,
        "funnel": {
            "start": kept_ids + total_removed,
            "kept": kept_ids,
            "steps": [
                {"rule": rule, "label": label, "removed": len(removed.get(rule, [])),
                 "examples": _examples(removed.get(rule, []))}
                for rule, label in RULES.items()
            ],
        },
        "rules": {
            "windowHours": int(WINDOW_AHEAD.total_seconds() // 3600),
            "minCrossingKm": MIN_CROSSING_KM,
            "bigM": BIG_M,
            "pickupBig": [int(x.total_seconds() // 60) for x in PICKUP["big"]],
            "pickupSmall": [int(x.total_seconds() // 60) for x in PICKUP["small"]],
        },
    }
