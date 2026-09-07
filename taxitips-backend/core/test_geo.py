"""
Tester för core/geo.py:s resolve_coords -- de fyra upplösningsnivåerna, med
fokus på de två nya (gazetteer, regioncentrum) från Fas 2+3.

resolve_coords cachar gazetteret i en modulnivå-variabel (samma mönster som
poller.js:s stopNameGazetteer-singleton) -- Djangos testrunner kör alla
tester i samma process, så varje test som rör gazetteret måste nolla cachen
själv, annars läser ett senare test en stale cache från ett tidigare.
"""

from django.test import TestCase

import core.geo as geo_module
from core.geo import resolve_coords
from core.models import StopArea


class ResetGazetteerCache(TestCase):
    def setUp(self):
        geo_module._gazetteer_cache = None

    def tearDown(self):
        geo_module._gazetteer_cache = None


class ExactAndPlaceTiers(ResetGazetteerCache):
    def test_exact_coords_on_the_alert_win_over_everything(self):
        alert = {"lat": 55.6, "lon": 13.0, "region": "skane"}
        lat, lon, precision = resolve_coords(alert, {})
        self.assertEqual((lat, lon, precision), (55.6, 13.0, "exact"))

    def test_a_resolvable_hub_or_city_name_is_tier_2(self):
        alert = {"region": "skane"}
        taxi = {"places": ["Lund C"]}
        lat, lon, precision = resolve_coords(alert, taxi)
        self.assertIsNotNone(lat)
        self.assertEqual(precision, "place")


class GazetteerTier(ResetGazetteerCache):
    def test_a_local_stop_name_in_the_text_resolves_via_the_gazetteer(self):
        StopArea.objects.create(gid="1", operator="sl", name="Hässelby strand", lat=59.36, lon=17.83)
        alert = {"header": "Störning vid Hässelby strand", "description": "", "region": "sl"}
        lat, lon, precision = resolve_coords(alert, {})
        self.assertEqual((lat, lon), (59.36, 17.83))
        self.assertEqual(precision, "gazetteer")

    def test_longest_match_wins(self):
        StopArea.objects.create(gid="1", operator="sl", name="Hässelby", lat=1.0, lon=1.0)
        StopArea.objects.create(gid="2", operator="sl", name="Hässelby strand", lat=2.0, lon=2.0)
        alert = {"header": "Störning vid Hässelby strand", "description": "", "region": "sl"}
        lat, lon, precision = resolve_coords(alert, {})
        self.assertEqual((lat, lon, precision), (2.0, 2.0, "gazetteer"))

    def test_names_shorter_than_five_chars_are_excluded(self):
        # Short names ("Ås", "Bro") match inside unrelated words and would
        # place a tip in the wrong town -- worse than no coordinate at all.
        StopArea.objects.create(gid="1", operator="vt", name="Ås", lat=1.0, lon=1.0)
        alert = {"header": "Vägarbete Åsgatan", "description": "", "region": "vt"}
        lat, lon, precision = resolve_coords(alert, {})
        self.assertNotEqual((lat, lon), (1.0, 1.0))

    def test_a_real_place_match_is_preferred_over_the_gazetteer(self):
        StopArea.objects.create(gid="1", operator="sl", name="Some Local Stop", lat=99.0, lon=99.0)
        alert = {"header": "Some Local Stop", "description": "", "region": "sl"}
        taxi = {"places": ["Malmö"]}
        lat, lon, precision = resolve_coords(alert, taxi)
        self.assertEqual(precision, "place")
        self.assertNotEqual((lat, lon), (99.0, 99.0))


class RegionCentroidTier(ResetGazetteerCache):
    def test_a_known_region_with_no_resolvable_place_gets_a_city_centre_pin(self):
        alert = {"header": "Inställd avgång", "description": "", "region": "sl"}
        lat, lon, precision = resolve_coords(alert, {})
        self.assertIsNotNone(lat)
        self.assertEqual(precision, "region")

    def test_an_unknown_region_and_no_place_yields_nothing(self):
        alert = {"header": "Inställd avgång", "description": "", "region": "made-up-region"}
        lat, lon, precision = resolve_coords(alert, {})
        self.assertEqual((lat, lon, precision), (None, None, "none"))
