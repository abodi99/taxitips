"""
/api/ferries: bara för behöriga, bara terminaler i förarens område, och aldrig hela landet
utan område eller position.
"""

from __future__ import annotations

import datetime as dt

from django.core.cache import cache
from django.test import SimpleTestCase
from django.utils import timezone

from core.test_api import DEVICE_TOKEN, ApiTestCase
from maritime.models import AisVessel
from maritime import views
from maritime.ports import by_key


class FerriesApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        now = timezone.now()
        helsingborg, stromstad = by_key("helsingborg"), by_key("stromstad")
        AisVessel.objects.create(mmsi=219622000, name="HAMLET", ship_type=60, length_m=106,
                                 latitude=56.040, longitude=12.650, speed_knots=12.0, course=85.0,
                                 position_at=now - dt.timedelta(minutes=1))
        AisVessel.objects.create(mmsi=259000001, name="COLOR HYBRID", ship_type=60, length_m=160,
                                 latitude=stromstad.lat, longitude=stromstad.lon, speed_knots=0.0,
                                 position_at=now - dt.timedelta(minutes=1))
        # Ett fartyg som är i området men på väg någon annanstans visas inte i appen.
        AisVessel.objects.create(mmsi=219000999, name="PASSERAR", ship_type=60, length_m=150,
                                 latitude=56.000, longitude=12.600, speed_knots=15.0, course=180.0,
                                 position_at=now - dt.timedelta(minutes=1))
        self.helsingborg = helsingborg

    def get(self, params=None, **headers):
        return self.client.get("/api/ferries", params or {}, headers={"x-device-token": DEVICE_TOKEN, **headers}).json()

    def test_a_county_choice_keeps_its_terminals_only(self):
        body = self.get({"counties": "12"})
        self.assertEqual([f["name"] for f in body["ferries"]], ["HAMLET"])
        self.assertEqual(body["ferries"][0]["status"], "approaching")
        self.assertIn("helsingborg", {t["key"] for t in body["terminals"]})
        self.assertNotIn("stromstad", {t["key"] for t in body["terminals"]})
        self.assertIn("AISStream", body["attribution"])
        self.assertIn("arrivals", body)
        self.assertIsInstance(body["arrivals"], list)

    def test_a_position_uses_the_radius_instead(self):
        body = self.get(**{"x-tt-position": "58.94,11.17"})
        self.assertEqual([(f["name"], f["status"]) for f in body["ferries"]], [("COLOR HYBRID", "berthed")])

    def test_no_area_and_no_position_is_not_the_whole_country(self):
        body = self.get()
        self.assertEqual((body["ferries"], body.get("arrivals"), body.get("needsArea")), ([], [], True))

    def test_without_access_nothing_is_shown(self):
        body = self.client.get("/api/ferries", {"counties": "12"}).json()
        self.assertEqual((body["ferries"], body["entitled"]), ([], False))


class FerryRowsParityTests(ApiTestCase):
    """Ägarkrav 2026-10-09: allt kartan visar ska finnas i listan -- en lista, `rows`, för båda."""

    def setUp(self):
        super().setUp()
        cache.clear()
        now = timezone.now()
        self.port = by_key("stadsgarden")
        # Sex stora färjor vid samma terminal: två vid kaj, fyra på väg in.
        for n in range(6):
            AisVessel.objects.create(
                mmsi=265000000 + n, name=f"FARJA {n}", ship_type=60, length_m=120 + n * 30,
                latitude=self.port.lat, longitude=self.port.lon, speed_knots=0.0,
                position_at=now - dt.timedelta(minutes=1),
            )

    def get(self):
        return self.client.get(
            "/api/ferries", headers={"x-device-token": DEVICE_TOKEN, "x-tt-position": f"{self.port.lat},{self.port.lon}"},
        ).json()

    def test_every_ferry_on_the_map_is_a_row(self):
        body = self.get()
        ships = {f"ais:{s['mmsi']}" for s in body["ferries"]}
        self.assertEqual(len(ships), 6)
        self.assertEqual({r["id"] for r in body["rows"]}, ships)

    def test_a_row_carries_only_what_a_driver_needs(self):
        body = self.get()
        row = body["rows"][0]
        for technical in ("mmsi", "knots", "lengthM", "destination", "expectedBasis", "source", "why", "calc",
                          "ageSeconds", "courseOff", "agency"):
            self.assertNotIn(technical, row)
        self.assertEqual(row["portName"], self.port.name)
        self.assertIn(row["sizeLabel"], ("Stor färja", "Medelstor färja", "Mindre färja"))
        self.assertTrue(row["arrived"])


class FerryRowsUnitTests(SimpleTestCase):
    def setUp(self):
        self.now = timezone.now()
        self.terminals = {"nynashamn": {"key": "nynashamn", "name": "Nynäshamn", "lat": 58.90, "lon": 17.95}}

    def ship(self, mmsi, status="approaching", **extra):
        return {"mmsi": mmsi, "name": f"SHIP {mmsi}", "lengthM": 196, "lat": 58.8, "lon": 18.0, "course": 330.0,
                "knots": 18.0, "status": status, "terminal": "nynashamn", "terminalName": "Nynäshamn",
                "eta": (self.now + dt.timedelta(minutes=25)).isoformat(), "etaMinutes": 25, **extra}

    def test_a_ship_that_is_an_arrival_is_one_row_and_the_rest_are_kept(self):
        arrival = {
            "id": "tt:2026-10-09:T1", "kind": "big", "route": "Visby - Nynäshamn", "from": "Visby",
            "terminal": {"name": "Nynäshamn Färjeterminal", "lat": 58.901, "lon": 17.951},
            "vessel": {"name": "VISBORG", "mmsi": 1, "lengthM": 200, "lat": 58.8, "lon": 18.0, "course": 330.0},
            "expectedAt": (self.now + dt.timedelta(minutes=20)).isoformat(), "arrived": False,
            "pickupFrom": None, "pickupUntil": None,
        }
        rows = views.ferry_rows([self.ship(1), self.ship(2, "berthed")], [("nynashamn", arrival)], self.terminals, self.now)
        self.assertEqual([r["id"] for r in rows], ["tt:2026-10-09:T1", "ais:2"])
        first = rows[0]
        self.assertEqual((first["name"], first["from"], first["portName"]), ("SHIP 1", "Visby", "Nynäshamn Färjeterminal"))
        self.assertEqual(first["sizeLabel"], "Stor färja")
        self.assertTrue(first["live"])
        self.assertIn(first["etaMinutes"], (19, 20))
        self.assertTrue(rows[1]["arrived"])

    def test_a_timetable_arrival_without_position_stands_at_the_quay(self):
        arrival = {
            "id": "tt:x", "kind": "island", "route": "", "from": "Utö", "vessel": None,
            "terminal": {"name": "Nynäshamn", "lat": 58.90, "lon": 17.95},
            "expectedAt": (self.now + dt.timedelta(minutes=40)).isoformat(), "arrived": False,
        }
        row = views.ferry_rows([], [("nynashamn", arrival)], self.terminals, self.now)[0]
        self.assertEqual((row["lat"], row["lon"], row["live"]), (58.90, 17.95, False))
        self.assertEqual((row["name"], row["sizeLabel"]), ("Färja", "Öbåt"))

    def test_an_mmsi_is_never_a_name(self):
        rows = views.ferry_rows([self.ship(3, name="MMSI 3")], [], self.terminals, self.now)
        self.assertEqual(rows[0]["name"], "Färja")
