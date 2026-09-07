"""
Tester för core/sources/trafiklab.py.

parse_feed byggs mot en riktig, in-test-konstruerad FeedMessage (via
gtfs_realtime_bindings) i stället för en incheckad binärfixtur -- billigare
att läsa, och bevisar samma sak: att fältnamnen (snake_case i Python-
paketet, till skillnad från npm-paketets camelCase) faktiskt läses rätt.
"""

from django.test import TestCase, override_settings
from google.transit import gtfs_realtime_pb2 as pb

from core.sources.trafiklab import configured_operators, mock_alerts, parse_feed


def _build_feed_with_alert() -> bytes:
    feed = pb.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"

    entity = feed.entity.add()
    entity.id = "1234"
    alert = entity.alert

    header = alert.header_text.translation.add()
    header.text, header.language = "Tåg 501 inställt", "sv"
    description = alert.description_text.translation.add()
    description.text, description.language = "Tåget är inställt på grund av tekniskt fel.", "sv"

    alert.cause = pb.Alert.TECHNICAL_PROBLEM
    alert.effect = pb.Alert.NO_SERVICE

    period = alert.active_period.add()
    period.start, period.end = 1700000000, 1700003600

    informed = alert.informed_entity.add()
    informed.route_id, informed.stop_id = "PA", "82000"

    # A non-alert entity (e.g. a bare vehicle position) must be skipped,
    # not crash the parser.
    other = feed.entity.add()
    other.id = "vp-1"
    other.vehicle.trip.trip_id = "t1"

    return feed.SerializeToString()


class ParseFeed(TestCase):
    def test_decodes_one_alert_and_skips_non_alert_entities(self):
        alerts = parse_feed(_build_feed_with_alert())
        self.assertEqual(len(alerts), 1)

        a = alerts[0]
        self.assertEqual(a["id"], "1234")
        self.assertEqual(a["header"], "Tåg 501 inställt")
        self.assertIn("Tekniskt fel", a["description"] + a["cause"])
        self.assertEqual(a["cause"], "Tekniskt fel")
        self.assertEqual(a["effect"], "Ingen service")
        self.assertIn("PA", a["routes"])
        self.assertIn("82000", a["stops"])
        self.assertIsNotNone(a["active_from"])
        self.assertIsNotNone(a["active_to"])
        self.assertLess(a["active_from"], a["active_to"])

    def test_empty_feed_yields_no_alerts(self):
        feed = pb.FeedMessage()
        feed.header.gtfs_realtime_version = "2.0"
        self.assertEqual(parse_feed(feed.SerializeToString()), [])


class MockAlerts(TestCase):
    def test_shape_matches_real_alerts(self):
        alerts = mock_alerts()
        self.assertEqual(len(alerts), 2)
        for a in alerts:
            for key in ("id", "header", "description", "cause", "effect", "areas",
                        "routes", "stops", "url", "active_from", "active_to"):
                self.assertIn(key, a)
            self.assertLess(a["active_from"], a["active_to"])


class ConfiguredOperators(TestCase):
    @override_settings(TRAFIKLAB_OPERATORS="skane")
    def test_default_is_skane_only(self):
        self.assertEqual(configured_operators(), ["skane"])

    @override_settings(TRAFIKLAB_OPERATORS="skane, sl,  vt,skane")
    def test_comma_list_is_trimmed_lowercased_and_deduped(self):
        self.assertEqual(configured_operators(), ["skane", "sl", "vt"])
