"""
Färjornas tidtabell: bara färjelinjer, rätt trafikdagar, tider efter midnatt, och ersättning
i stället för dubbletter vid omkörning.
"""

from __future__ import annotations

import datetime as dt
import io
import os
import tempfile
import zipfile

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from maritime import approach, timetable
from maritime.models import FerryTimetableCall
from maritime.ports import by_key

DAY = dt.date(2026, 9, 19)  # lördag


def gtfs_zip(path: str) -> None:
    files = {
        "agency.txt": "agency_id,agency_name\nA,Ventrafiken\nB,Skånetrafiken\n",
        "routes.txt": "route_id,agency_id,route_short_name,route_long_name,route_type\n"
                      "R1,A,Båt,,1000\nR2,B,1,,700\n",
        "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
                        "S1,0,0,0,0,0,1,1,20260101,20261231\nS2,1,1,1,1,1,0,0,20260101,20261231\n",
        "calendar_dates.txt": "service_id,date,exception_type\nS2,20260919,1\nS1,20260920,2\n",
        "trips.txt": "route_id,service_id,trip_id\nR1,S1,T1\nR1,S2,T2\nR2,S1,BUS\n",
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\n"
                     "L,Landskrona Skeppsbron,55.8694,12.8303\nV,Ven Bäckviken,55.9112,12.7065\nX,Busshållplats,55.6,13.0\n",
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                          "T1,11:30:00,11:30:00,L,1\nT1,12:00:00,12:00:00,V,2\n"
                          "T2,24:40:00,24:40:00,V,1\nT2,25:10:00,25:10:00,L,2\n"
                          "BUS,11:00:00,11:00:00,X,1\nBUS,11:05:00,11:05:00,L,2\n",
    }
    with zipfile.ZipFile(path, "w") as archive:
        for name, body in files.items():
            archive.writestr(name, body)


class ReadTests(SimpleTestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "sweden.zip")
        gtfs_zip(self.path)

    def test_only_ferry_trips_on_their_days_with_times_past_midnight(self):
        calls = timetable.read_calls(self.path, [DAY])
        self.assertEqual({c["trip_id"] for c in calls}, {"T1", "T2"})  # bussen är ingen färja; T2 via undantag
        late = next(c for c in calls if c["trip_id"] == "T2" and c["stop_id"] == "L")
        self.assertEqual(late["arrival_at"].astimezone(timetable.TZ), dt.datetime(2026, 9, 20, 1, 10, tzinfo=timetable.TZ))
        self.assertIsNone(late["departure_at"])
        first = next(c for c in calls if c["trip_id"] == "T1" and c["stop_id"] == "L")
        self.assertEqual((first["arrival_at"], first["origin_name"], first["destination_name"]),
                         (None, "Landskrona Skeppsbron", "Ven Bäckviken"))

    def test_a_ferry_stop_without_bus_nearby_is_marked(self):
        calls = timetable.read_calls(self.path, [DAY])
        road = {c["stop_name"]: c["stop_has_road"] for c in calls}
        # Bussen stannar i Landskrona men inte på Ven.
        self.assertEqual(road, {"Landskrona Skeppsbron": True, "Ven Bäckviken": False})

    def test_a_removed_day_has_no_trips(self):
        self.assertEqual(timetable.read_calls(self.path, [DAY + dt.timedelta(days=1)]), [])


class ImportTests(TestCase):
    def test_running_twice_replaces_instead_of_duplicating(self):
        path = os.path.join(tempfile.mkdtemp(), "sweden.zip")
        gtfs_zip(path)
        out = io.StringIO()
        call_command("import_ferry_timetable", "--zip", path, "--days", "1", stdout=out)
        first = FerryTimetableCall.objects.count()
        call_command("import_ferry_timetable", "--zip", path, "--days", "1", stdout=out)
        self.assertEqual(FerryTimetableCall.objects.count(), first)

    def test_the_snapshot_lists_the_next_arrivals_per_stop(self):
        now = timezone.now()
        FerryTimetableCall.objects.create(
            service_date=now.date(), trip_id="T1", agency="Ventrafiken", route_name="Båt", stop_id="V",
            stop_name="Ven Bäckviken", lat=55.9112, lon=12.7065, sequence=2,
            arrival_at=now + dt.timedelta(minutes=20), departure_at=None,
            origin_name="Landskrona Skeppsbron", destination_name="Ven Bäckviken", imported_at=now,
        )
        data = approach.timetable(now)
        self.assertEqual([a["stop"] for a in data["arrivals"]], ["Ven Bäckviken"])
        self.assertEqual(data["arrivals"][0]["from"], "Landskrona Skeppsbron")
        (stop,) = data["stops"]
        self.assertEqual((stop["name"], stop["next"][0]["kind"]), ("Ven Bäckviken", "arrival"))

    def test_only_large_ferry_operators_are_paired_with_an_ais_terminal(self):
        now = timezone.now()
        common = dict(service_date=now.date(), trip_id="X", route_name="", sequence=2, departure_at=None,
                      destination_name="", imported_at=now, arrival_at=now + dt.timedelta(minutes=30))
        visby = by_key("visby")
        FerryTimetableCall.objects.create(agency="Destination Gotland", stop_id="VBY", stop_name="Visby hamnterminal",
                                          lat=visby.lat, lon=visby.lon, origin_name="Nynäshamn", **common)
        FerryTimetableCall.objects.create(agency="AB SL Kundtjänst", stop_id="SLU", stop_name="Slussen",
                                          lat=59.3195, lon=18.0720, origin_name="Nybroplan", **common)
        ports = {a["stop"]: a["port"] for a in approach.timetable(now)["arrivals"]}
        self.assertEqual(ports, {"Visby hamnterminal": "visby", "Slussen": None})
