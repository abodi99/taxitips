"""
Tester för core/sources/sl.py -- port av worker/test/sl.test.js, fixtur för
fixtur.
"""

from datetime import datetime, timedelta, timezone as dt_tz

from django.test import TestCase

from core.sources.sl import build_site_index, is_actionable, mode_hint_from, normalize_deviation, pick_variant

NOW = datetime(2026, 9, 5, 18, 0, tzinfo=dt_tz.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def deviation(**overrides) -> dict:
    base = {
        "deviation_case_id": 12524985,
        "publish": {
            "from": _iso(NOW - timedelta(hours=1)),
            "upto": _iso(NOW + timedelta(hours=4)),
        },
        "priority": {"importance_level": 7},
        "message_variants": [
            {"header": "Flera inställda avgångar", "details": "Vagnbrist.", "language": "sv"},
        ],
        "scope": {"stop_areas": [], "lines": [{"designation": "7", "transport_mode": "TRAM"}]},
    }
    base.update(overrides)
    return base


class IsActionable(TestCase):
    def test_rejects_a_long_running_notice_published_years_ago(self):
        d = deviation(publish={"from": "2024-01-03T07:45:54.647+01:00", "upto": "2026-12-31T23:30:00+01:00"})
        self.assertFalse(is_actionable(d, NOW))

    def test_rejects_a_recent_but_open_ended_notice(self):
        d = deviation(publish={
            "from": _iso(NOW - timedelta(hours=1)),
            "upto": _iso(NOW + timedelta(days=30)),
        })
        self.assertFalse(is_actionable(d, NOW))

    def test_rejects_a_short_notice_that_is_already_over(self):
        d = deviation(publish={
            "from": _iso(NOW - timedelta(hours=5)),
            "upto": _iso(NOW - timedelta(hours=1)),
        })
        self.assertFalse(is_actionable(d, NOW))

    def test_accepts_a_recent_bounded_still_running_disruption(self):
        self.assertTrue(is_actionable(deviation(), NOW))

    def test_a_missing_upto_is_treated_as_open_ended_not_as_short(self):
        d = deviation(publish={"from": _iso(NOW - timedelta(hours=1))})
        self.assertFalse(is_actionable(d, NOW))


class PickVariant(TestCase):
    def test_picks_the_swedish_variant(self):
        v = pick_variant([{"header": "Delays", "language": "en"}, {"header": "Förseningar", "language": "sv"}])
        self.assertEqual(v["header"], "Förseningar")

    def test_falls_back_to_the_first_variant_when_no_swedish_one_exists(self):
        self.assertEqual(pick_variant([{"header": "Delays", "language": "en"}])["header"], "Delays")
        self.assertIsNone(pick_variant([]))


class ModeHintFrom(TestCase):
    def test_maps_transport_mode_preferring_the_most_stranding_mode(self):
        self.assertEqual(mode_hint_from([{"transport_mode": "BUS"}]), "bus")
        self.assertEqual(mode_hint_from([{"transport_mode": "METRO"}]), "metro")
        self.assertEqual(mode_hint_from([{"transport_mode": "TRAM"}]), "tram")
        self.assertEqual(
            mode_hint_from([{"transport_mode": "BUS"}, {"transport_mode": "METRO"}]), "metro"
        )
        self.assertIsNone(mode_hint_from([]))


class NormalizeDeviation(TestCase):
    def test_normalizes_into_the_shared_alert_shape_with_an_sl_prefix(self):
        a = normalize_deviation(deviation(), {})
        self.assertEqual(a["id"], "sl:12524985")
        self.assertEqual(a["source"], "sl")
        self.assertEqual(a["region"], "sl")
        self.assertEqual(a["mode_hint"], "tram")
        self.assertEqual(a["routes"], ["7"])
        self.assertEqual(a["sl"]["importance_level"], 7)

    def test_resolves_coordinates_via_the_stop_area_index(self):
        index = build_site_index([
            {"gid": "80351", "operator": "sl", "name": "Södergården", "lat": 59.2, "lon": 18.1},
        ])
        a = normalize_deviation(
            deviation(scope={"stop_areas": [{"id": 80351, "name": "Södergården"}], "lines": []}), index
        )
        self.assertEqual(a["lat"], 59.2)
        self.assertEqual(a["lon"], 18.1)
        self.assertEqual(a["areas"], ["Södergården"])

    def test_leaves_coordinates_null_rather_than_guessing_a_location(self):
        # A line-level disruption has no single location. Inventing one
        # (e.g. the line's first stop) would send drivers to a specific
        # wrong corner of Stockholm with false precision.
        a = normalize_deviation(deviation(), {})
        self.assertIsNone(a["lat"])
        self.assertIsNone(a["lon"])

    def test_an_unknown_stop_area_id_yields_null_not_a_wrong_coordinate(self):
        index = build_site_index([
            {"gid": "999", "operator": "sl", "name": "Annat", "lat": 59.9, "lon": 18.9},
        ])
        a = normalize_deviation(
            deviation(scope={"stop_areas": [{"id": 80351, "name": "Södergården"}], "lines": []}), index
        )
        self.assertIsNone(a["lat"])
