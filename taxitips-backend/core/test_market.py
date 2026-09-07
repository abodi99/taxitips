"""
Tester för core/market.py -- port av worker/test/skane.test.js.

Innehåller de två regressionstesten från Node-testets senaste (ännu
oincheckade) diff: den placeless-larm-fallbacken får inte släppa in en
okonfigurerad region ("SL-läckan").
"""

from django.test import TestCase, override_settings

from core.market import alert_in_market, is_national_scope, place_looks_skane


class PlaceLooksSkane(TestCase):
    def test_exact_and_substring_match(self):
        self.assertTrue(place_looks_skane("Malmö"))
        self.assertTrue(place_looks_skane("malmö c"))
        self.assertFalse(place_looks_skane("Göteborg"))
        self.assertFalse(place_looks_skane(None))


@override_settings(MARKET_SCOPE="skane", TRAFIKLAB_OPERATORS="skane")
class AlertInMarketDefaultScope(TestCase):
    def test_default_scope_is_not_national(self):
        self.assertFalse(is_national_scope())

    def test_region_skane_is_admitted(self):
        self.assertTrue(alert_in_market({"region": "skane", "header": "", "description": ""}))

    def test_text_naming_another_region_is_rejected(self):
        alert = {"region": "skane", "header": "Störning Kalmar C", "description": ""}
        self.assertFalse(alert_in_market(alert))

    def test_oresundstag_running_through_kalmar_but_naming_skane_is_admitted(self):
        alert = {
            "region": "skane", "header": "Öresundståg Malmö–Kalmar försenat",
            "description": "",
        }
        self.assertTrue(alert_in_market(alert))

    def test_place_in_taxi_places_is_admitted(self):
        alert = {"region": "", "header": "Försening", "description": ""}
        taxi = {"places": ["Lund"]}
        self.assertTrue(alert_in_market(alert, taxi))

    def test_placeless_fallback_does_not_admit_an_unconfigured_region(self):
        """The 'SL leak': an SL alert with no place name must not be
        admitted to the Skåne-only market just because it's placeless."""
        alert = {
            "id": "sl:93075231", "region": "sl", "header": "Indragna hållplatser",
            "description": "Hållplats Södergården trafikeras inte.",
        }
        self.assertFalse(alert_in_market(alert))

    def test_placeless_skane_feed_alert_is_still_admitted(self):
        alert = {
            "id": "skane:9", "region": "skane", "header": "Försening",
            "description": "Tåget är försenat. Orsaken är växelfel.",
        }
        self.assertTrue(alert_in_market(alert))


@override_settings(MARKET_SCOPE="skane", TRAFIKLAB_OPERATORS="skane,sl")
class AlertInMarketConfiguredOperator(TestCase):
    def test_a_configured_operators_placeless_alert_is_admitted(self):
        alert = {"id": "sl:1", "region": "sl", "header": "Försening", "description": ""}
        self.assertTrue(alert_in_market(alert))


@override_settings(MARKET_SCOPE="national")
class AlertInMarketNationalScope(TestCase):
    def test_national_scope_admits_every_region(self):
        for region in ("sl", "vt", "skane", "otraf", ""):
            self.assertTrue(alert_in_market({"region": region, "header": "", "description": ""}))
