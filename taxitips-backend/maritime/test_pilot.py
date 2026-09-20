"""
AIS-piloten: närmar sig fartyget terminalen, när ligger det vid kaj, och när går folk iland?

Tre saker får aldrig hända: en avgång blir ett tips, kajtiden blir en blandning av två
källor som ingen kan förklara, eller iland-fönstret smälter ihop med kajtiden.
"""

from __future__ import annotations

import datetime as dt
import json

from django.test import SimpleTestCase, TestCase

from core.models import Opportunity
from maritime import ais, pilot
from maritime.models import FerryCall
from maritime.register import BY_MMSI, REGISTER, TERMINALS

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 9, 14, 9, 0, tzinfo=UTC)
DROTTEN = 265871000
VISBY = TERMINALS["visby"]


def fix(minutes: float, lat: float, lon: float, sog: float | None) -> ais.AisUpdate:
    return ais.AisUpdate(
        kind="position", mmsi=DROTTEN, name="DROTTEN", timestamp=NOW + dt.timedelta(minutes=minutes),
        lat=lat, lon=lon, sog=sog,
    )


def track(points, *, destination: str = "", ais_eta=None) -> pilot.Track:
    t = pilot.Track(DROTTEN, VISBY, destination=destination, ais_eta=ais_eta)
    for point in points:
        t.add(fix(*point))
    return t


# Söderut mot Visby i 20 knop: ungefär 3,3 km var femte minut.
TOWARDS_VISBY_FAR = [(0, 58.00, 18.10, 20.0), (5, 57.97, 18.10, 20.0), (10, 57.94, 18.10, 20.0)]
TOWARDS_VISBY_NEAR = [(0, 57.80, 18.20, 18.0), (5, 57.77, 18.21, 18.0), (10, 57.74, 18.22, 18.0)]
LEAVING_VISBY = [(0, 57.74, 18.22, 18.0), (5, 57.77, 18.21, 18.0), (10, 57.80, 18.20, 18.0)]


class ApproachTests(SimpleTestCase):
    def test_a_ferry_closing_in_at_speed_is_approaching(self):
        self.assertTrue(pilot.approaching(track(TOWARDS_VISBY_FAR)))

    def test_a_departure_is_never_an_approach(self):
        self.assertFalse(pilot.approaching(track(LEAVING_VISBY)))
        self.assertIsNone(pilot.estimate(track(LEAVING_VISBY), NOW + dt.timedelta(minutes=10)))

    def test_a_slow_ferry_is_not_approaching(self):
        slow = [(m, lat, lon, 3.0) for m, lat, lon, _ in TOWARDS_VISBY_FAR]
        self.assertFalse(pilot.approaching(track(slow)))

    def test_one_position_is_no_trend(self):
        self.assertFalse(pilot.approaching(track(TOWARDS_VISBY_FAR[:1])))

    def test_the_buffer_keeps_half_an_hour(self):
        t = track([(0, 58.30, 18.00, 20.0), (40, 58.00, 18.10, 20.0), (45, 57.97, 18.10, 20.0)])
        self.assertEqual(len(t.fixes), 2)

    def test_berthed_means_inside_the_terminal_box_and_nearly_still(self):
        self.assertTrue(pilot.berthed(track([(0, VISBY.port.lat, VISBY.port.lon, 0.2)])))
        self.assertFalse(pilot.berthed(track([(0, VISBY.port.lat, VISBY.port.lon, 8.0)])))
        self.assertFalse(pilot.berthed(track([(0, 57.94, 18.10, 0.2)])))


class BerthEstimateTests(SimpleTestCase):
    def test_distance_and_speed_give_the_berth_time(self):
        est = pilot.estimate(track(TOWARDS_VISBY_FAR), NOW + dt.timedelta(minutes=10))
        self.assertEqual(est.basis, pilot.BASIS_DISTANCE)
        minutes = (est.berth_eta - (NOW + dt.timedelta(minutes=10))).total_seconds() / 60
        # ~33 km fågelväg × 1,05 i 20 knop (37 km/h).
        self.assertTrue(50 <= minutes <= 62, minutes)

    def test_far_away_the_ships_own_eta_is_used_when_it_points_here(self):
        eta = NOW + dt.timedelta(minutes=80)
        est = pilot.estimate(track(TOWARDS_VISBY_FAR, destination="SE VBY", ais_eta=eta), NOW + dt.timedelta(minutes=10))
        self.assertEqual(est.basis, pilot.BASIS_AIS_ETA)
        # Ingen blandning: kajtiden ÄR AIS-ETA:n, inte ett medel av två.
        self.assertEqual(est.berth_eta, eta)
        self.assertIsNotNone(est.distance_eta)
        self.assertNotEqual(est.distance_eta, eta)

    def test_an_eta_for_another_port_is_ignored(self):
        eta = NOW + dt.timedelta(minutes=80)
        est = pilot.estimate(track(TOWARDS_VISBY_FAR, destination="SE NYN", ais_eta=eta), NOW + dt.timedelta(minutes=10))
        self.assertEqual(est.basis, pilot.BASIS_DISTANCE)

    def test_near_the_terminal_distance_wins_over_the_eta(self):
        eta = NOW + dt.timedelta(hours=3)
        est = pilot.estimate(track(TOWARDS_VISBY_NEAR, destination="SE VBY", ais_eta=eta), NOW + dt.timedelta(minutes=10))
        self.assertEqual(est.basis, pilot.BASIS_DISTANCE)
        self.assertLessEqual(est.distance_km, pilot.NEAR_KM)

    def test_the_pickup_window_is_separate_from_the_berth_time(self):
        est = pilot.estimate(track(TOWARDS_VISBY_FAR), NOW + dt.timedelta(minutes=10))
        start, end = est.pickup_window
        self.assertEqual(start - est.berth_eta, pilot.PICKUP_FROM)
        self.assertEqual(end - est.berth_eta, pilot.PICKUP_UNTIL)

    def test_small_changes_do_not_grow_the_history(self):
        call = FerryCall(call_id="x", mmsi=DROTTEN, terminal="visby", started_at=NOW)
        est = pilot.estimate(track(TOWARDS_VISBY_FAR), NOW + dt.timedelta(minutes=10))
        self.assertTrue(pilot.record_estimate(call, est, NOW))
        nudged = pilot.BerthEstimate(est.berth_eta + dt.timedelta(minutes=1), est.basis, est.distance_km, est.speed_knots, None, est.distance_eta)
        self.assertFalse(pilot.record_estimate(call, nudged, NOW))
        self.assertEqual(len(call.estimates), 1)
        self.assertEqual(call.first_berth_eta, est.berth_eta)


class RegisterTests(SimpleTestCase):
    def test_every_vessel_belongs_to_a_pilot_terminal_and_says_where_it_was_seen(self):
        for vessel in REGISTER:
            self.assertIn(vessel.terminal, TERMINALS)
            self.assertIn("AIS", vessel.source)

    def test_each_terminal_lies_inside_its_approach_box(self):
        for terminal in TERMINALS.values():
            (south, west), (north, east) = terminal.approach_box
            self.assertTrue(south <= terminal.port.lat <= north and west <= terminal.port.lon <= east)

    def test_one_filtered_subscription_latitude_first(self):
        sub = pilot.subscription("nyckel")
        self.assertEqual(sorted(sub["FiltersShipMMSI"]), sorted(str(m) for m in BY_MMSI))
        for (south, west), (north, east) in sub["BoundingBoxes"]:
            self.assertTrue(54 < south < north < 70 and 10 < west < east < 25)


class WriteTipTests(TestCase):
    def test_the_tip_covers_the_pickup_window_and_is_rewritten_not_duplicated(self):
        call = FerryCall.objects.create(call_id=f"{DROTTEN}:visby:20260914T0900", mmsi=DROTTEN, terminal="visby", started_at=NOW)
        est = pilot.estimate(track(TOWARDS_VISBY_FAR), NOW + dt.timedelta(minutes=10))
        ext = pilot.write_tip(call, est, name="DROTTEN", length_m=196)
        later = pilot.BerthEstimate(est.berth_eta + dt.timedelta(minutes=6), est.basis, est.distance_km, est.speed_knots, None, est.distance_eta)
        pilot.write_tip(call, later, name="DROTTEN", length_m=196)

        tip = Opportunity.objects.get(external_id=ext)
        self.assertEqual(Opportunity.objects.filter(external_id=ext).count(), 1)
        self.assertEqual(tip.start_time, later.pickup_window[0])
        self.assertEqual(tip.end_time, later.pickup_window[1])
        self.assertEqual(tip.rule_id, pilot.RULE_ID)
        reasons = " ".join(tip.reasons if isinstance(tip.reasons, list) else json.loads(tip.reasons))
        self.assertIn("framgår inte av AIS", reasons)
        self.assertIn("okalibrerat", reasons)


class PilotDeadlineTests(SimpleTestCase):
    """--duration är väggklocka: en dator som sovit ska inte förlänga körningen."""

    def test_the_run_ends_when_the_wall_clock_has_passed_the_deadline(self):
        import asyncio
        from unittest.mock import patch

        from maritime.management.commands.run_ais_pilot import PilotListener

        start = dt.datetime(2026, 9, 14, 7, 4, tzinfo=dt.timezone.utc)
        # Första anropet sätter gränsen, nästa är efter att datorn sovit i fyra timmar.
        clock = iter([start, start + dt.timedelta(hours=4)])
        listener = PilotListener("test-key", dry_run=True)
        with patch("maritime.management.commands.run_ais_pilot.timezone.now", side_effect=lambda: next(clock)):
            asyncio.run(asyncio.wait_for(listener._wait_until_done(12600), timeout=2))
        self.assertFalse(listener.stop.is_set())
