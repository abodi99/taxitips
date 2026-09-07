"""
Tester för core/sources/vasttrafik.py -- port av worker/test/vasttrafik.test.js,
plus en egen noggrannhetstest för sweref99_to_wgs84 mot en känd referenspunkt
(det enda matematiska stycket i den här planen där "ser rätt ut" inte räcker).
"""

from datetime import datetime, timedelta, timezone as dt_tz

from django.test import TestCase

from core.sources.vasttrafik import (
    build_stop_area_index, is_actionable, mode_hint_from, normalize_severity,
    normalize_situation, sweref99_to_wgs84,
)

NOW = datetime(2026, 9, 5, 20, 0, tzinfo=dt_tz.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def situation(**overrides) -> dict:
    base = {
        "situationNumber": "RT3029517",
        "title": "Linje 1 och 5 är indragna",
        "description": "Ersättningsbuss 1E kör. Orsaken är spårarbete.",
        "severity": "slight",
        "startTime": _iso(NOW - timedelta(hours=1)),
        "endTime": _iso(NOW + timedelta(hours=3)),
        "affectedLines": [{"designation": "1", "defaultTransportModeCode": "tram"}],
        "affectedStopPoints": [{
            "gid": "9022014001760001", "stopAreaGid": "9021014001760000",
            "name": "Brunnsparken", "stopAreaName": "Brunnsparken", "municipalityName": "Göteborg",
        }],
    }
    base.update(overrides)
    return base


class Sweref99ToWgs84(TestCase):
    def test_brunnsparken_reference_point(self):
        # Known reference from worker/test/vasttrafik.test.js's own comment:
        # SWEREF99TM (319346, 6400119) -> WGS84 (57.707373, 11.967851).
        lat, lon = sweref99_to_wgs84(319346, 6400119)
        self.assertAlmostEqual(lat, 57.707373, places=5)
        self.assertAlmostEqual(lon, 11.967851, places=5)


class IsActionable(TestCase):
    def test_rejects_a_disruption_that_has_not_started_yet(self):
        # The bug this file exists for: Västtrafik publishes planned
        # night-time track work weeks ahead (measured 17/87, 10/19 of
        # those that passed age+duration alone had not started).
        s = situation(
            startTime=_iso(NOW + timedelta(days=3)),
            endTime=_iso(NOW + timedelta(days=3, hours=6)),
        )
        self.assertFalse(is_actionable(s, NOW))

    def test_accepts_a_disruption_that_is_running_right_now(self):
        self.assertTrue(is_actionable(situation(), NOW))

    def test_rejects_a_month_long_planned_closure(self):
        s = situation(endTime=_iso(NOW + timedelta(days=30)))
        self.assertFalse(is_actionable(s, NOW))

    def test_rejects_one_that_already_ended(self):
        s = situation(startTime=_iso(NOW - timedelta(hours=5)), endTime=_iso(NOW - timedelta(hours=1)))
        self.assertFalse(is_actionable(s, NOW))


class ModeHintFrom(TestCase):
    def test_uses_default_transport_mode_code_not_prose(self):
        self.assertEqual(mode_hint_from([{"defaultTransportModeCode": "tram"}]), "tram")
        self.assertEqual(mode_hint_from([{"defaultTransportModeCode": "bus"}]), "bus")
        self.assertIsNone(mode_hint_from([]))


class NormalizeSeverityTests(TestCase):
    def test_carries_severity_as_evidence_never_as_score(self):
        self.assertEqual(normalize_severity("slight"), "slight")
        self.assertEqual(normalize_severity("veryHigh"), "veryHigh")
        self.assertIsNone(normalize_severity("nonsense"))


class NormalizeSituationTests(TestCase):
    def test_resolves_coordinates_through_stop_area_gid(self):
        index = build_stop_area_index([
            {"gid": "9021014001760000", "operator": "vt", "name": "Brunnsparken", "lat": 57.707373, "lon": 11.967851},
        ])
        a = normalize_situation(situation(), index)
        self.assertEqual(a["id"], "vt:RT3029517")
        self.assertEqual(a["source"], "vt")
        self.assertEqual(a["region"], "vt")
        self.assertEqual(a["mode_hint"], "tram")
        self.assertAlmostEqual(a["lat"], 57.707, delta=0.01)
        self.assertAlmostEqual(a["lon"], 11.968, delta=0.01)

    def test_an_unknown_stop_area_yields_null_not_a_wrong_coordinate(self):
        a = normalize_situation(situation(), build_stop_area_index([]))
        self.assertIsNone(a["lat"])
        self.assertIsNone(a["lon"])
