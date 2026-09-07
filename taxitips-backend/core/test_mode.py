"""
Tester för core/mode.py -- port av worker/test/mode.test.js, fixtur för
fixtur.
"""

from django.test import TestCase

from core.mode import classify_mode


def _m(header: str, description: str = "", routes: list[str] | None = None) -> str:
    return classify_mode({"header": header, "description": description, "routes": routes or []})


class ClassifyMode(TestCase):
    def test_boilerplate_mentioning_trains_does_not_make_a_bus_a_train(self):
        # Found by eye on the national map: Dalarna showed only `bus` in
        # the region table, yet 7 of its alerts had classified as `train`.
        # Cause: Dalatrafik's standard sign-off appended to every message
        # ("...anslutande tåg eller bussar...") promoted 7 bus disruptions
        # into the rail severity branch.
        self.assertEqual(
            _m(
                "Buss linje 265 riskerar att bli försenad",
                "Buss linje 265 riskerar att bli försenad på grund av vägarbete. "
                "Har ni tider att passa, anslutande tåg eller bussar, se Dalatrafiks app.",
            ),
            "bus",
        )

    def test_a_replacement_bus_still_means_a_rail_disruption(self):
        self.assertEqual(
            _m("Inställd - Buss ersätter", "Tåget är inställt. 2 bussar ersätter."), "train"
        )
        self.assertEqual(
            _m("Bussar ersätter spårvagnarna", "Från 17 augusti ersätter bussar spårvagnarna."),
            "train",
        )

    def test_the_header_decides_when_header_and_body_disagree(self):
        self.assertEqual(
            _m("Förseningar", "Förseningar för buss linje 173 från Skärholmen."), "bus"
        )
        self.assertEqual(_m("Stopp i tågtrafiken", "Det är stopp i tågtrafiken."), "train")

    def test_a_stated_mode_hint_always_wins(self):
        self.assertEqual(
            classify_mode({"header": "Förseningar", "mode_hint": "metro"}), "metro"
        )
        self.assertEqual(
            classify_mode({"header": "Buss linje 1", "mode_hint": "tram"}), "tram"
        )

    def test_no_keyword_at_all_stays_unknown_never_guessed(self):
        self.assertEqual(_m("Trafikinformation", "Se appen för mer information."), "unknown")
