"""
Tester för core/text_scoring.py -- en per gren i classify_transit_alert,
test_rail.py-stil (RailAlert-portens "kärnfallet" mönster): bygg alert+taxi
direkt i stället för att gå via score_alert(), så varje gren kan verifieras
isolerat mot en känd ScoringRule-rad.
"""

from django.test import TestCase

from core.models import Confidence, SeverityTier
from core.text_scoring import (
    AMBIGUOUS_SCORE,
    BUS_LINE_CANCELLED_SCORE,
    SINGLE_DEPARTURE_SCORE,
    STATED_ALTERNATIVE_SCORE,
    WHOLE_LINE_STOP_SCORE,
    classify_transit_alert,
    departure_date,
)


def _taxi(**overrides) -> dict:
    base = dict(score=0, level="high", why="allvarlig störning", places=[], hubs=[], driver_hint=None,
                serious=True, mediumish=False)
    base.update(overrides)
    return base


class WholeLineStop(TestCase):
    def test_no_stated_alternative_is_a_stranding(self):
        alert = {"header": "Stopp i tågtrafiken", "description": "Inga tåg går just nu."}
        result = classify_transit_alert(alert, _taxi(score=40))
        self.assertEqual(result.tier, SeverityTier.LINE_PAUSED)
        self.assertEqual(result.score, WHOLE_LINE_STOP_SCORE)
        self.assertTrue(result.stranded)
        self.assertEqual(result.mode, "train")
        self.assertEqual(result.confidence, Confidence.HIGH)


class SingleDeparture(TestCase):
    """SL 2026-09-30/10-01: en inställd tur blev "Hela linjen stoppad" 85 och push."""

    def test_one_cancelled_trip_is_not_a_stopped_line(self):
        for text in (
            "Hagsätra - Vällingby kl 16:59 är inställd 2026-09-30 på grund av tekniskt fel.",
            "Inställd avgång kl 20:40 på linje 5 från hållplats Hälla. Resenärer hänvisas till nästa avgång.",
            "Zinkensdamm - Ropsten kl 16:02 är inställd på grund av ordningsproblem.",
        ):
            result = classify_transit_alert({"header": "Inställd avgång", "description": text}, _taxi(score=85))
            self.assertEqual(result.tier, SeverityTier.VEHICLE_CANCELLED, text)
            self.assertEqual(result.score, SINGLE_DEPARTURE_SCORE, text)
            self.assertFalse(result.stranded)

    def test_a_stop_from_a_given_time_is_still_the_whole_line(self):
        alert = {"header": "Trafikstopp", "description": "Ingen trafik mellan Lund och Malmö från kl 14.30."}
        result = classify_transit_alert(alert, _taxi(score=85))
        self.assertTrue(result.rule_id.endswith("whole_line_stop"), result.rule_id)

    def test_a_known_next_departure_uses_the_gap(self):
        alert = {"header": "Inställd avgång", "description": "Linje 4 kl 12:00 är inställd.",
                 "next_departure_minutes": 45}
        result = classify_transit_alert(alert, _taxi(score=85))
        self.assertEqual(result.tier, SeverityTier.LINE_PAUSED)
        self.assertTrue(result.stranded)
        self.assertEqual(result.wait_minutes, 45)


class ReducedSpeed(TestCase):
    def test_slow_trains_are_a_delay_not_a_stop(self):
        alert = {"header": "Tågen kör med reducerad hastighet",
                 "description": "Tågen kör med reducerad hastighet vid Fridhemsplan, inställda avgångar kan förekomma."}
        result = classify_transit_alert(alert, _taxi(score=85, mediumish=False))
        self.assertEqual(result.tier, SeverityTier.LINE_DELAYED)


class StatedAlternative(TestCase):
    def test_a_named_alternative_caps_lower_than_a_full_stop(self):
        alert = {"header": "Tåg 501 inställt", "description": "Se övriga avgångar."}
        result = classify_transit_alert(alert, _taxi(score=50))
        self.assertEqual(result.tier, SeverityTier.VEHICLE_CANCELLED)
        self.assertEqual(result.score, STATED_ALTERNATIVE_SCORE)
        self.assertTrue(result.quick_alternative)
        self.assertEqual(result.confidence, Confidence.MEDIUM)


class Ambiguous(TestCase):
    def test_serious_but_neither_signal_explicit_is_at_most_medium(self):
        alert = {"header": "Tåg 501 kraftigt försenat", "description": "Trafiken är påverkad."}
        result = classify_transit_alert(alert, _taxi(score=45))
        self.assertEqual(result.tier, SeverityTier.LINE_PAUSED)
        self.assertEqual(result.score, AMBIGUOUS_SCORE)
        self.assertFalse(result.stranded, "oklart läge får aldrig bli Stark")
        self.assertEqual(result.confidence, Confidence.LOW, "no sl/vt editorial signal -> low")

    def test_sl_importance_lifts_confidence_not_score(self):
        alert = {
            "header": "Tåg 501 kraftigt försenat", "description": "Trafiken är påverkad.",
            "sl": {"importance_level": 7},
        }
        result = classify_transit_alert(alert, _taxi(score=45))
        self.assertEqual(result.confidence, Confidence.MEDIUM)
        self.assertEqual(result.score, AMBIGUOUS_SCORE)  # unchanged -- confidence only

    def test_vt_severity_lifts_confidence_the_same_way_sl_importance_does(self):
        alert = {
            "header": "Tåg 501 kraftigt försenat", "description": "Trafiken är påverkad.",
            "vt": {"severity": "veryHigh"},
        }
        result = classify_transit_alert(alert, _taxi(score=45))
        self.assertEqual(result.confidence, Confidence.MEDIUM)


class RailLikeMediumish(TestCase):
    def test_mediumish_without_serious_is_line_delayed(self):
        alert = {"header": "Tåg 12 försenat", "description": ""}
        result = classify_transit_alert(alert, _taxi(score=30, serious=False, mediumish=True))
        self.assertEqual(result.tier, SeverityTier.LINE_DELAYED)
        self.assertLessEqual(result.score, 45)


class BusSerious(TestCase):
    def test_serious_bus_disruption_is_medium_at_most(self):
        alert = {"header": "Buss 173 inställd", "description": "Ingen ersättare."}
        result = classify_transit_alert(alert, _taxi(score=55))
        self.assertEqual(result.tier, SeverityTier.VEHICLE_CANCELLED)
        self.assertEqual(result.score, BUS_LINE_CANCELLED_SCORE)
        self.assertFalse(result.stranded)
        self.assertEqual(result.mode, "bus")

    def test_explicit_cancellation_statement_stays_high_confidence(self):
        alert = {"header": "Buss 173 inställd", "description": "Ingen ersättare."}
        result = classify_transit_alert(alert, _taxi(score=55))
        self.assertEqual(result.confidence, Confidence.HIGH)

    def test_serious_only_via_the_broader_word_soup_is_low_confidence(self):
        # "serious" fired here from SERIOUS_RE's wider vocabulary (strejk),
        # not an explicit "inställd"/"ställs in"/"inga avgångar" statement
        # -- this is exactly the "just the word 'installed'" blind trust
        # the user pushed back on. It must now be reviewable, not silently
        # HIGH just because *a* serious-sounding word matched.
        alert = {"header": "Buss 173 påverkas av strejk", "description": "Personalen strejkar idag."}
        result = classify_transit_alert(alert, _taxi(score=55))
        self.assertEqual(result.tier, SeverityTier.VEHICLE_CANCELLED)
        self.assertEqual(result.confidence, Confidence.LOW)


class BusMediumish(TestCase):
    def test_mediumish_bus_caps_at_25(self):
        alert = {"header": "Buss 42 försenad", "description": ""}
        result = classify_transit_alert(alert, _taxi(score=30, serious=False, mediumish=True))
        self.assertEqual(result.tier, SeverityTier.VEHICLE_DELAYED)
        self.assertLessEqual(result.score, 25)


class IgnorePassthrough(TestCase):
    def test_no_taxi_is_ignore(self):
        result = classify_transit_alert({"header": "Hissen ur funktion"}, None)
        self.assertEqual(result.tier, SeverityTier.IGNORE)
        self.assertEqual(result.score, 0)

    def test_ignore_level_taxi_is_ignore(self):
        alert = {"header": "Hissen ur funktion"}
        taxi = {"level": "ignore", "why": "Stationsservice — ingen taxinytta"}
        result = classify_transit_alert(alert, taxi)
        self.assertEqual(result.tier, SeverityTier.IGNORE)
        self.assertIn("Stationsservice — ingen taxinytta", result.reasons)


class RoadTier(TestCase):
    """
    Väggrenen är inte längre en stub (se core/sources/trafikverket_road.py).
    Tierindelningen i sig testas i core/test_road.py; det som vaktas här är
    att den bara ETIKETTERAR -- score_road_alert har redan kapat poängen
    lågt med avsikt, och tiern får inte smyga tillbaka in den.
    """

    def test_road_tier_labels_without_re_scoring(self):
        alert = {"header": "Vägarbete", "description": "", "source_kind": "road"}
        result = classify_transit_alert(alert, _taxi(score=5, level="low"))
        self.assertEqual(result.mode, "road")
        self.assertEqual(result.tier, SeverityTier.ROAD_WORK)
        self.assertEqual(result.score, 5)

    def test_accident_and_queue_get_their_own_tiers(self):
        accident = classify_transit_alert(
            {"header": "Olycka", "description": "", "source_kind": "road"},
            _taxi(score=15, level="low"),
        )
        queue = classify_transit_alert(
            {"header": "Kövarning", "description": "", "source_kind": "road"},
            _taxi(score=10, level="low"),
        )
        self.assertEqual(accident.tier, SeverityTier.ROAD_ACCIDENT_OR_CLOSURE)
        self.assertEqual(queue.tier, SeverityTier.ROAD_WORK_OR_QUEUE)


class NamedTrainCancelled(TestCase):
    """Vy Tågs strejkinställda tåg Göteborg–Halden blev "Hela linjen stoppad" 53 och 97 (2026-10-02)."""

    def test_a_named_train_is_one_departure(self):
        for header in (
            "Vy Tåg 382, 7 oktober klockan 06:14, är inställt från Göteborg Central till Halden stasjon",
            "Vy Tåg 397 klockan 19:är inställt från Halden statjon till Göteborg Central.",
            "VY Tåg 393 klockan 17:18 är inställt från Halden stasjon till Göteborg Central.",
        ):
            alert = {"header": header, "description": "För mer information, kontakta Vy Tåg. Orsaken är strejk."}
            result = classify_transit_alert(alert, _taxi(score=85))
            self.assertEqual(result.tier, SeverityTier.VEHICLE_CANCELLED, header)
            self.assertEqual(result.score, SINGLE_DEPARTURE_SCORE, header)
            self.assertFalse(result.stranded, header)

    def test_the_date_in_the_text(self):
        import datetime as dt

        self.assertEqual(departure_date("7 oktober klockan 06:14", dt.date(2026, 10, 2)), dt.date(2026, 10, 7))
        self.assertEqual(departure_date("tåget 3 januari", dt.date(2026, 12, 20)), dt.date(2027, 1, 3))
        self.assertIsNone(departure_date("klockan 06:14", dt.date(2026, 10, 2)))
