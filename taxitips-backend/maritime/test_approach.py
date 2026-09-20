"""
Färjor på väg in: rätt terminal, rätt riktning, ärlig ankomsttid -- och inget som inte är
en stor passagerarfärja med färskt läge.
"""

from __future__ import annotations

import asyncio
import datetime as dt
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase, override_settings

from core.geo import haversine_km
from maritime import approach
from maritime.management.commands.run_ais_stream import AisListener
from maritime.models import AisVessel, FerryArrival
from maritime.ports import PORTS, by_key

NOW = dt.datetime(2026, 9, 18, 12, 0, tzinfo=dt.timezone.utc)
# Mitt i sundet mellan Helsingör och Helsingborg.
SUNDET = (56.040, 12.650)


def ship(**overrides):
    fields = {
        "mmsi": 219000001, "name": "HAMLET", "ship_type": 60, "length_m": 111,
        "latitude": SUNDET[0], "longitude": SUNDET[1], "speed_knots": 12.0, "course": 90.0, "heading": 90,
        "position_at": NOW - dt.timedelta(minutes=1), "destination": "HELSINGBORG", "nav_status": 0,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


class GeometryTests(SimpleTestCase):
    def test_bearing_points_the_right_way(self):
        self.assertAlmostEqual(approach.bearing_deg(56.0, 12.6, 56.1, 12.6), 0.0, places=3)
        self.assertAlmostEqual(approach.bearing_deg(56.0, 12.6, 56.0, 12.7), 90.0, delta=0.1)
        self.assertEqual(approach.course_off(350, 10), 20)


class ClassifyTests(SimpleTestCase):
    def test_a_ferry_heading_for_helsingborg_is_approaching_with_an_eta(self):
        row = approach.classify(ship(), NOW)
        helsingborg = by_key("helsingborg")
        distance = haversine_km(*SUNDET, helsingborg.lat, helsingborg.lon)
        self.assertEqual((row["status"], row["terminal"]), (approach.APPROACHING, "helsingborg"))
        expected = distance * helsingborg.route_factor / (12.0 * approach.KNOT_KMH) * 60
        self.assertAlmostEqual(row["etaMinutes"], round(expected), delta=1)

    def test_heading_away_is_not_approaching(self):
        row = approach.classify(ship(course=270.0), NOW)
        self.assertEqual((row["status"], row["eta"]), (approach.AROUND, None))

    def test_at_berth_in_the_port_box(self):
        helsingborg = by_key("helsingborg")
        row = approach.classify(ship(latitude=helsingborg.lat, longitude=helsingborg.lon, speed_knots=0.2), NOW)
        self.assertEqual((row["status"], row["terminal"]), (approach.BERTHED, "helsingborg"))

    def test_slow_in_the_port_box_is_docking_toward_the_terminal_and_in_port_otherwise(self):
        helsingborg = by_key("helsingborg")
        near = dict(latitude=helsingborg.lat, longitude=helsingborg.lon - 0.012, speed_knots=3.0)
        docking = approach.classify(ship(course=90.0, **near), NOW)
        self.assertEqual((docking["status"], docking["terminal"]), (approach.DOCKING, "helsingborg"))
        self.assertIsNotNone(docking["eta"])
        leaving = approach.classify(ship(course=270.0, **near), NOW)
        self.assertEqual((leaving["status"], leaving["eta"]), (approach.IN_PORT, None))

    def test_only_fresh_large_passenger_ships_in_an_approach_area(self):
        for excluded in (
            ship(length_m=40), ship(length_m=None), ship(ship_type=70),
            ship(position_at=NOW - dt.timedelta(minutes=16)), ship(latitude=58.0, longitude=20.5),
        ):
            self.assertIsNone(approach.classify(excluded, NOW))

    def test_the_nearest_terminal_wins_when_the_course_points_at_two(self):
        # Västerut genom skärgården: kursen pekar mot både Stadsgården och Värtahamnen.
        row = approach.classify(ship(latitude=59.330, longitude=18.300, course=268.0), NOW)
        self.assertEqual(row["status"], approach.APPROACHING)
        self.assertIn(row["terminal"], ("stadsgarden", "vartahamnen"))
        other = "vartahamnen" if row["terminal"] == "stadsgarden" else "stadsgarden"
        self.assertLessEqual(
            row["distanceKm"], haversine_km(59.330, 18.300, by_key(other).lat, by_key(other).lon),
        )


class SnapshotTests(TestCase):
    def test_the_snapshot_lists_terminals_ships_and_what_was_left_out(self):
        AisVessel.objects.create(mmsi=219000001, name="HAMLET", ship_type=60, length_m=111, latitude=SUNDET[0],
                                 longitude=SUNDET[1], speed_knots=12.0, course=90.0, position_at=NOW - dt.timedelta(minutes=2))
        AisVessel.objects.create(mmsi=265000002, name="VENTRAFIKEN", ship_type=60, length_m=45, latitude=SUNDET[0],
                                 longitude=SUNDET[1], speed_knots=9.0, course=90.0, position_at=NOW - dt.timedelta(minutes=2))
        data = approach.snapshot(NOW)
        self.assertEqual([s["name"] for s in data["ships"]], ["HAMLET"])
        self.assertEqual(data["skipped"], {"short": 1})
        self.assertEqual(len(data["terminals"]), len(PORTS))
        self.assertEqual(next(t for t in data["terminals"] if t["key"] == "helsingborg")["approaching"], 1)

    def test_the_endpoint_exists_only_with_debug(self):
        self.assertEqual(self.client.get("/api/pipeline/ferries").status_code, 404)
        with override_settings(DEBUG=True):
            res = self.client.get("/api/pipeline/ferries")
        self.assertEqual(res.status_code, 200)
        self.assertIn("terminals", res.json())


class MapOnlyPortTests(SimpleTestCase):
    def test_an_arrival_at_a_map_only_port_writes_no_tip(self):
        listener = AisListener("test-key", dry_run=False)
        ferry = FerryArrival(mmsi=219000001, ship_name="HAMLET", ship_type=60, length_m=111,
                             port_name=by_key("helsingborg").name, speed_knots=3.0)
        asyncio.run(listener.on_arrival(ferry, "slowing_in_port", NOW))
        self.assertEqual(listener.decisions[0]["verdict"], "bara karta")
        self.assertEqual(listener.totals["tips_written"], 0)
