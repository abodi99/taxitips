"""
Tester för core/taxi_relevance.py -- port av worker/test/seriousness.test.js,
plus ett par NOISE_RE-fall direkt ur taxiRelevance.js (ingen egen JS-testfil
för dem).
"""

from datetime import datetime, timedelta, timezone as dt_tz

from django.test import TestCase, override_settings

from core.taxi_relevance import enrich_alert


def _alert(header: str, description: str = "") -> dict:
    now = datetime.now(dt_tz.utc)
    return {
        "id": "skane:test", "header": header, "description": description,
        "active_from": now, "active_to": now + timedelta(hours=1),
    }


@override_settings(MARKET_SCOPE="skane", TRAFIKLAB_OPERATORS="skane")
class SeriousnessRegressions(TestCase):
    def test_a_cancelled_train_in_the_neuter_form_is_serious(self):
        # "inställt" -- the neuter form, and the one Swedish actually uses
        # for a train ("tåget är inställt") -- was missing from SERIOUS_RE
        # in an earlier version, which listed only inställd/inställda.
        # Found via Västtrafik, where every cancelled Öresundståg reads
        # "... är inställt" and was therefore scored `ignore`.
        taxi = enrich_alert(_alert(
            "Öresundståg 20189 klockan 23:55 är inställt från Göteborg Central."
        ))
        self.assertNotEqual(taxi["level"], "ignore", "inställt must be recognised as serious")

    def test_the_older_forms_still_work(self):
        self.assertNotEqual(enrich_alert(_alert("Tåget är inställd"))["level"], "ignore")
        self.assertNotEqual(enrich_alert(_alert("Inställda avgångar"))["level"], "ignore")

    def test_does_not_fire_on_unrelated_words(self):
        # Guard against the widened pattern swallowing unrelated words:
        # "installerat" contains "installera", not "inställ".
        self.assertEqual(enrich_alert(_alert("Hiss ur funktion"))["level"], "ignore")
        self.assertEqual(
            enrich_alert(_alert("Vi har installerat nya skyltar"))["level"], "ignore"
        )


@override_settings(MARKET_SCOPE="skane", TRAFIKLAB_OPERATORS="skane")
class NoiseFiltering(TestCase):
    """Station/info utan taxinytta ska ignoreras, även när rubriken nämner
    en station -- taxiRelevance.js's egna kommentar, ingen JS-testfil."""

    def test_elevator_out_of_service_is_ignored(self):
        self.assertEqual(enrich_alert(_alert("Hissen ur funktion", "Malmö C"))["level"], "ignore")

    def test_noise_word_alongside_a_real_cancellation_is_kept(self):
        # "Hiss + inställda tåg i samma text -> behåll allvarliga delen"
        taxi = enrich_alert(_alert(
            "Hissen ur funktion", "Tåget är inställt på grund av tekniskt fel."
        ))
        self.assertNotEqual(taxi["level"], "ignore")
