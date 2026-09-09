"""
Tester för core/sources/sl.py -- port av worker/test/sl.test.js, fixtur för
fixtur.
"""

from datetime import datetime, timedelta, timezone as dt_tz

from django.test import TestCase

from core.sources.sl import (
    build_site_index,
    extract_stop_and_time_from_details,
    is_actionable,
    mode_hint_from,
    normalize_deviation,
    pick_variant,
)

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

    def test_falls_back_to_the_free_text_stop_and_time_when_stop_areas_is_empty(self):
        # "mellan Varvsgatan kl 6:45 och Fridhemsplan" -- a real example
        # from the field inventory measurement (docs/api-field-inventory.md #5).
        index = build_site_index([
            {"gid": "9001", "operator": "sl", "name": "Varvsgatan", "lat": 59.33, "lon": 18.02},
        ])
        a = normalize_deviation(
            deviation(message_variants=[{
                "header": "Inställd avgång",
                "details": "Inställd avgång för buss linje 4 mellan Varvsgatan kl 6:45 och "
                           "Fridhemsplan pga tekniskt fel.",
                "language": "sv",
            }]),
            index,
        )
        self.assertEqual(a["lat"], 59.33)
        self.assertEqual(a["lon"], 18.02)
        self.assertEqual(a["mentioned_time_at"].strftime("%H:%M"), "06:45")


class ExtractStopAndTimeFromDetails(TestCase):
    def test_extracts_a_stop_name_and_time_after_fran(self):
        index = build_site_index([
            {"gid": "1", "operator": "sl", "name": "Skärholmen", "lat": 59.28, "lon": 17.9},
        ])
        hit = extract_stop_and_time_from_details(
            "Förseningar upp till 15 minuter för buss linje 865 från Skärholmen 08:52 "
            "mot Rudsjöterrassen på grund av ett tekniskt fel.",
            index,
        )
        self.assertIsNotNone(hit)
        self.assertEqual(hit["lat"], 59.28)
        self.assertEqual(hit["lon"], 17.9)
        self.assertEqual(hit["time"].strftime("%H:%M"), "08:52")

    def test_returns_none_when_the_text_has_no_stop_and_time_pattern(self):
        index = build_site_index([
            {"gid": "1", "operator": "sl", "name": "Skärholmen", "lat": 59.28, "lon": 17.9},
        ])
        self.assertIsNone(extract_stop_and_time_from_details("Vagnbrist.", index))

    def test_kl_alone_is_not_mistaken_for_a_stop_name(self):
        # Regression for the measured false-hit: "mellan kl. 6:45 och 8:00"
        # has no stop name before "kl." at all.
        index = build_site_index([
            {"gid": "1", "operator": "sl", "name": "Kl", "lat": 59.0, "lon": 18.0},
        ])
        self.assertIsNone(
            extract_stop_and_time_from_details(
                "Anropsstyrd trafik ersätter buss 148 mellan kl. 6:45 och 8:00.", index
            )
        )

    def test_a_name_not_found_in_the_registry_yields_no_hit_not_a_guess(self):
        # The text says "Sollentuna station" but the registry only has
        # "Sollentuna" -- an exact-match lookup must not fuzzy its way
        # to a coordinate.
        index = build_site_index([
            {"gid": "1", "operator": "sl", "name": "Sollentuna", "lat": 59.43, "lon": 17.95},
        ])
        self.assertIsNone(
            extract_stop_and_time_from_details(
                "Förseningar för pendeltåg från Sollentuna station 07:10 mot Stockholm C.", index
            )
        )

    def test_returns_none_without_a_site_index(self):
        self.assertIsNone(
            extract_stop_and_time_from_details("från Skärholmen 08:52 mot Rudsjöterrassen", {})
        )
        self.assertIsNone(
            extract_stop_and_time_from_details("från Skärholmen 08:52 mot Rudsjöterrassen", None)
        )

