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


class FerryRowDecisionFieldTests(SimpleTestCase):
    """
    Ägarkrav 2026-10-11: kortet ska räcka för ett underbyggt beslut -- när, hur säkert, var,
    vilka som kliver av och vad mer som händer vid kajen. Bara ur befintlig data, aldrig
    passagerarantal, källnamn eller fart/kurs.
    """

    def setUp(self):
        self.now = timezone.now().replace(microsecond=0)
        self.terminals = {"nynashamn": {"key": "nynashamn", "name": "Nynäshamn", "lat": 58.90, "lon": 17.95}}

    def at(self, minutes):
        return (self.now + dt.timedelta(minutes=minutes)).isoformat()

    def arrival(self, ident="tt:1", minutes=25, vessel=None, delay=None, **extra):
        planned = self.at(minutes - (delay or 0))
        return {
            "id": ident, "kind": "big", "kindLabel": "Stor färja", "route": "Visby - Nynäshamn",
            "from": "Visby", "terminal": {"name": "Nynäshamns färjeterminal", "lat": 58.901, "lon": 17.951},
            "vessel": vessel, "plannedAt": planned, "plannedDeparture": self.at(minutes - 195),
            "expectedAt": self.at(minutes), "delayMinutes": delay, "arrived": False,
            "pickupFrom": self.at(minutes + 10), "pickupUntil": self.at(minutes + 45),
            "operator": "Destination Gotland", "international": False, "transitAtQuay": True,
            "agency": "Destination Gotland", "source": "tidtabell", "why": ["x"], "calc": ["AIS ..."],
            **extra,
        }

    def rows(self, arrivals, ships=()):
        return views.ferry_rows(list(ships), [("nynashamn", a) for a in arrivals], self.terminals, self.now)

    def test_timetable_only_is_not_confirmed_and_has_no_delay(self):
        (row,) = self.rows([self.arrival(delay=7)])
        self.assertFalse(row["confirmed"])
        # Utan kopplat fartyg vet vi inte om den är sen: okänt, inte "i tid".
        self.assertIsNone(row["delayMinutes"])
        self.assertEqual(row["scheduledAt"], self.at(18))
        self.assertEqual((row["kindLabel"], row["operator"], row["route"]),
                         ("Stor färja", "Destination Gotland", "Visby - Nynäshamn"))
        self.assertIn("bagage", row["kindDetail"])
        self.assertEqual((row["departedFrom"], row["international"]), ("Visby", False))
        self.assertEqual(row["departedAt"], self.at(25 - 195))
        self.assertIsNone(row["sameTerminalSoon"])

    def test_a_matched_vessel_is_confirmed_and_carries_its_delay(self):
        vessel = {"name": "VISBORG", "mmsi": 1, "lengthM": 200, "lat": 58.7, "lon": 18.1, "course": 330.0}
        (row,) = self.rows([self.arrival(vessel=vessel, delay=12)])
        self.assertTrue(row["confirmed"])
        self.assertEqual(row["delayMinutes"], 12)
        self.assertEqual(
            dt.datetime.fromisoformat(row["expectedAt"]) - dt.datetime.fromisoformat(row["scheduledAt"]),
            dt.timedelta(minutes=12),
        )

    def test_an_ais_ship_without_timetable_is_confirmed_with_unknowns_empty(self):
        ship = {"mmsi": 9, "name": "FINNPARTNER", "lengthM": 218, "lat": 58.8, "lon": 18.0, "course": 330.0,
                "knots": 18.0, "status": "approaching", "terminal": "nynashamn", "terminalName": "Nynäshamn",
                "eta": self.at(40), "etaMinutes": 40}
        (row,) = self.rows([], [ship])
        self.assertTrue(row["confirmed"])
        for unknown in ("scheduledAt", "delayMinutes", "operator", "route", "departedFrom", "departedAt",
                        "international", "terminalNote", "sameTerminalSoon"):
            self.assertIsNone(row[unknown], unknown)
        self.assertEqual(row["kindLabel"], "Stort passagerarfartyg")

    def test_other_ferries_to_the_same_quay_within_half_an_hour(self):
        rows = self.rows([
            self.arrival("tt:1", minutes=20),
            self.arrival("tt:2", minutes=35),
            self.arrival("tt:3", minutes=55),
            self.arrival("tt:4", minutes=120),
        ])
        soon = {r["id"]: r["sameTerminalSoon"] for r in rows}
        self.assertEqual(soon["tt:1"], {"count": 1, "nextAt": self.at(35)})
        self.assertEqual(soon["tt:2"], {"count": 2, "nextAt": self.at(20)})
        self.assertEqual(soon["tt:3"], {"count": 1, "nextAt": self.at(35)})
        self.assertIsNone(soon["tt:4"])

    def test_another_quay_in_the_same_port_does_not_count(self):
        other = self.arrival("tt:2", minutes=30, terminal={"name": "Annan brygga", "lat": 58.915, "lon": 17.951})
        rows = self.rows([self.arrival("tt:1", minutes=20), other])
        self.assertTrue(all(r["sameTerminalSoon"] is None for r in rows))

    def test_the_terminal_note_only_says_what_the_timetable_knows(self):
        with_transit, without, unknown = self.rows([
            self.arrival("tt:1", minutes=10),
            self.arrival("tt:2", minutes=60, transitAtQuay=False),
            self.arrival("tt:3", minutes=120, transitAtQuay=None),
        ])
        self.assertEqual(with_transit["terminalNote"], views.TRANSIT_NOTE)
        self.assertIn("kolla att taxin når fram", without["terminalNote"])
        self.assertIsNone(unknown["terminalNote"])

    def test_no_passenger_numbers_sources_or_technical_fields(self):
        import json
        import re

        vessel = {"name": "VISBORG", "mmsi": 1, "lengthM": 200, "lat": 58.7, "lon": 18.1, "course": 330.0}
        rows = self.rows([self.arrival(vessel=vessel, delay=3)])
        row = rows[0]
        for technical in ("mmsi", "knots", "lengthM", "source", "why", "calc", "agency", "passengers",
                          "expectedBasis", "portNote", "note"):
            self.assertNotIn(technical, row)
        text = " ".join(str(v) for v in row.values() if isinstance(v, str))
        self.assertNotRegex(text, re.compile(r"AIS|MMSI|GTFS|Trafiklab|Trafikanalys|knop|passager|miljoner", re.I))
        # Hamnregistrets anteckning bär passagerarsiffror och når aldrig föraren.
        self.assertNotIn("miljoner", json.dumps(rows, ensure_ascii=False))
