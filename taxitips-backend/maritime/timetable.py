"""
Färjornas tidtabell ur GTFS Sverige 3 statisk: planerade anlöp per färjeläge.

Uppmätt 2026-09-19 (docs/data-sources.md): 74 färjelinjer (`route_type` 1000) och 1 574
turer en lördag -- Waxholmsbolaget, Västtrafik, SL, Trafikverkets vägfärjor, Destination
Gotland, Ven, Ivö, Visingsö, Gräsö m.fl. Utlandsfärjorna finns inte. Ingen av färjorna har
realtid hos Trafiklab, så tiderna här är planerade; var färjan faktiskt är kommer från AIS.

Filen är 650 MB och får hämtas 50 gånger i månaden per nyckel (Bronze), delat mellan alla
miljöer. Därför: läs en redan hämtad fil (`--zip`), och hämta högst en gång per
MIN_DOWNLOAD_GAP. Läses direkt ur zip, utan att packas upp; bara färjeturernas anlöp sparas.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import zipfile
from collections import defaultdict
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Europe/Stockholm")
URL = "https://opendata.samtrafiken.se/gtfs-sweden/sweden.zip"
SOURCE = "gtfs_sweden3_ferries"
MIN_DOWNLOAD_GAP = dt.timedelta(hours=20)
# GTFS: 4 = färja; utökade typer 1000-1099 = sjötrafik, 1200 = färjetrafik.
FERRY_ROUTE_TYPES = frozenset({"4", "1200"} | {str(t) for t in range(1000, 1100)})
# Ett färjeläge med buss, spårvagn eller tåg inom så här många km nås med bil. Nacka strands
# busshållplats ligger 470 m från bryggan.
ROAD_KM = 0.6
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def _rows(archive: zipfile.ZipFile, name: str):
    with archive.open(name) as handle:
        yield from csv.DictReader(io.TextIOWrapper(handle, encoding="utf-8-sig"))


def _seconds(value: str) -> int | None:
    """GTFS-tid, som kan passera midnatt: "25:10:00" är 01:10 nästa dygn."""
    try:
        hours, minutes, seconds = (int(part) for part in value.split(":"))
    except (AttributeError, ValueError):
        return None
    return hours * 3600 + minutes * 60 + seconds


def active_services(archive: zipfile.ZipFile, day: dt.date) -> set[str]:
    ymd = day.strftime("%Y%m%d")
    weekday = WEEKDAYS[day.weekday()]
    active = set()
    if "calendar.txt" in archive.namelist():
        for row in _rows(archive, "calendar.txt"):
            if row["start_date"] <= ymd <= row["end_date"] and row.get(weekday) == "1":
                active.add(row["service_id"])
    if "calendar_dates.txt" in archive.namelist():
        for row in _rows(archive, "calendar_dates.txt"):
            if row["date"] == ymd:
                if row["exception_type"] == "1":
                    active.add(row["service_id"])
                else:
                    active.discard(row["service_id"])
    return active


def _near_land(lat: float, lon: float, grid: dict) -> bool:
    """Någon hållplats med buss, spårvagn eller tåg inom ROAD_KM? Rutnät på 0,01 grader."""
    from core.geo import haversine_km

    cell = (int(lat * 100), int(lon * 100))
    for dlat in (-1, 0, 1):
        for dlon in (-1, 0, 1):
            for other in grid.get((cell[0] + dlat, cell[1] + dlon), ()):
                if haversine_km(lat, lon, other[0], other[1]) <= ROAD_KM:
                    return True
    return False


def read_calls(path: str, days: list[dt.date]) -> list[dict]:
    """Färjeturernas anlöp de givna trafikdagarna, en rad per tur och färjeläge."""
    archive = zipfile.ZipFile(path)
    agencies = {row["agency_id"]: row["agency_name"] for row in _rows(archive, "agency.txt")}
    all_routes = {row["route_id"]: row for row in _rows(archive, "routes.txt")}
    routes = {rid: row for rid, row in all_routes.items() if row["route_type"] in FERRY_ROUTE_TYPES}
    services = {day: active_services(archive, day) for day in days}
    wanted_services = set().union(*services.values()) if services else set()
    trips = {}
    land_trips = set()
    for row in _rows(archive, "trips.txt"):
        if row["route_id"] in routes:
            if row["service_id"] in wanted_services:
                trips[row["trip_id"]] = row
        else:
            land_trips.add(row["trip_id"])
    times: dict[str, list[dict]] = defaultdict(list)
    # Hållplatser som trafikeras av något annat än färjor (buss, spårvagn, tåg): där går bilväg.
    land_stops: set[str] = set()
    for row in _rows(archive, "stop_times.txt"):
        if row["trip_id"] in trips:
            times[row["trip_id"]].append(row)
        elif row["trip_id"] in land_trips:
            land_stops.add(row["stop_id"])
    stop_ids = {row["stop_id"] for calls in times.values() for row in calls}
    stops = {}
    land_grid: dict[tuple[int, int], list[tuple[float, float]]] = defaultdict(list)
    for row in _rows(archive, "stops.txt"):
        if row["stop_id"] in stop_ids:
            stops[row["stop_id"]] = row
        if row["stop_id"] in land_stops:
            lat, lon = float(row["stop_lat"]), float(row["stop_lon"])
            land_grid[(int(lat * 100), int(lon * 100))].append((lat, lon))
    has_road = {stop_id: _near_land(float(s["stop_lat"]), float(s["stop_lon"]), land_grid) for stop_id, s in stops.items()}

    calls: list[dict] = []
    for trip_id, rows in times.items():
        rows.sort(key=lambda r: int(r["stop_sequence"]))
        trip = trips[trip_id]
        route = routes[trip["route_id"]]
        origin = stops.get(rows[0]["stop_id"], {}).get("stop_name", "")
        destination = stops.get(rows[-1]["stop_id"], {}).get("stop_name", "")
        for day in days:
            if trip["service_id"] not in services[day]:
                continue
            midnight = dt.datetime.combine(day, dt.time.min, tzinfo=TZ)
            for index, row in enumerate(rows):
                stop = stops.get(row["stop_id"])
                if stop is None:
                    continue
                arrival = _seconds(row["arrival_time"]) if index > 0 else None
                departure = _seconds(row["departure_time"]) if index < len(rows) - 1 else None
                calls.append({
                    "service_date": day,
                    "trip_id": trip_id,
                    "agency": agencies.get(route["agency_id"], route["agency_id"])[:100],
                    "route_name": (route.get("route_short_name") or route.get("route_long_name") or "")[:100],
                    "stop_id": row["stop_id"],
                    "stop_name": stop["stop_name"][:120],
                    "lat": float(stop["stop_lat"]),
                    "lon": float(stop["stop_lon"]),
                    "sequence": int(row["stop_sequence"]),
                    "arrival_at": midnight + dt.timedelta(seconds=arrival) if arrival is not None else None,
                    "departure_at": midnight + dt.timedelta(seconds=departure) if departure is not None else None,
                    "origin_name": origin[:120],
                    "destination_name": destination[:120],
                    "stop_has_road": has_road.get(row["stop_id"], True),
                })
    return calls


def replace_calls(calls: list[dict], days: list[dt.date], now: dt.datetime) -> int:
    """Ersätt de importerade dagarnas anlöp. Härlett från filen, så inget går förlorat."""
    from django.db import transaction

    from maritime.models import FerryTimetableCall

    with transaction.atomic():
        FerryTimetableCall.objects.filter(service_date__in=days).delete()
        FerryTimetableCall.objects.bulk_create(
            [FerryTimetableCall(imported_at=now, **call) for call in calls], batch_size=2000,
        )
    return len(calls)
