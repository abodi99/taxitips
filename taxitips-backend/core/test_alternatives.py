"""
Tester för "vad gör resenären i stället?" (core/alternatives.py).

Två saker vaktas: att vi aldrig HITTAR PÅ ett alternativ, och att minuterna
räknas från den absoluta tidpunkten. Det andra är inte kosmetiskt -- ett
tips som skrevs för 20 minuter sedan påstod "nästa om 45 min" när det i
verkligheten var 25, och en förare som kör dit på det beskedet kommer för
sent till en perrong som redan tömts.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from django.test import TestCase

from core.alternatives import alternative_from_text, human_gap, travel_options

NOW = datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc)


class AlternativeFromTextTests(TestCase):
    def test_the_source_sentence_is_quoted_not_paraphrased(self):
        found, note = alternative_from_text(
            "Tåget inställt",
            "Avgången är inställd. Buss ersätter mellan Lund C och Eslöv.",
        )
        self.assertTrue(found)
        self.assertIn("Buss ersätter", note)
        self.assertIn("Eslöv", note)

    def test_the_more_specific_label_wins(self):
        # "ersättningsbuss" säger vilket färdsätt; "ersättningstrafik" gör
        # det inte. Föraren ska få den mer informativa av dem.
        _, note = alternative_from_text("", "Ersättningsbuss är insatt, ersättningstrafik pågår.")
        self.assertTrue(note.startswith("Ersättningsbuss"))

    def test_no_alternative_mentioned_gives_nothing(self):
        # Inte "vi vet inte" som blir "det finns inget": tomt svar, och
        # appen visar då ingen rad alls.
        self.assertEqual(alternative_from_text("Signalfel", "Tåget är försenat."), (False, ""))
        self.assertEqual(alternative_from_text(None, None), (False, ""))

    def test_long_source_sentences_fall_back_to_the_label(self):
        long_text = "Buss ersätter. " + "x" * 200
        found, note = alternative_from_text("", long_text)
        self.assertTrue(found)
        self.assertEqual(note, "Buss ersätter")

    def test_the_variants_the_sources_actually_write(self):
        for text, expect in [
            ("Ersättningsbussar går från läge C", "Ersättningsbuss"),
            ("Bussar ersätter tågen", "Buss ersätter"),
            ("Ersättningstrafik är insatt", "Ersättningstrafik"),
            ("Resenärer hänvisas till linje 4", "Hänvisas till annan linje"),
            ("Övriga avgångar går som vanligt", "Övriga avgångar går"),
        ]:
            with self.subTest(text):
                found, note = alternative_from_text("", text)
                self.assertTrue(found)
                self.assertTrue(note.startswith(expect), note)


class TravelOptionsTests(TestCase):
    def options(self, **kw):
        base = dict(
            next_departure_at=None, next_departure_minutes=None,
            is_last_departure=False, has_alternative=False,
            alternative_note="", now=NOW,
        )
        base.update(kw)
        return travel_options(**base)

    def test_minutes_are_recomputed_from_the_absolute_time(self):
        # Skrivet för 20 min sedan med "45 min kvar" -- sanningen är 25.
        result = self.options(
            next_departure_at=NOW + timedelta(minutes=25),
            next_departure_minutes=45,
        )
        self.assertEqual(result["next_departure_minutes"], 25)
        self.assertIn("om 25 min", result["summary"])

    def test_the_clock_time_is_shown_because_it_never_goes_stale(self):
        result = self.options(next_departure_at=NOW + timedelta(minutes=25))
        self.assertIsNotNone(result["next_departure_clock"])
        self.assertIn(result["next_departure_clock"], result["summary"])

    def test_without_an_absolute_time_the_stored_minutes_are_used(self):
        result = self.options(next_departure_minutes=45)
        self.assertEqual(result["summary"], "Nästa avgång om 45 min")

    def test_last_departure_outranks_a_gap(self):
        result = self.options(is_last_departure=True, next_departure_minutes=45)
        self.assertEqual(result["summary"], "Sista avgången härifrån")

    def test_alternative_is_appended_to_the_gap(self):
        result = self.options(
            next_departure_minutes=90, has_alternative=True, alternative_note="Buss ersätter"
        )
        self.assertEqual(result["summary"], "Nästa avgång om 1 tim 30 min · Buss ersätter")

    def test_nothing_known_gives_no_sentence(self):
        # None, inte tom sträng: appen ska kunna skilja "vi vet inget" från
        # "vi vet att det inte finns något".
        self.assertIsNone(self.options()["summary"])

    def test_a_departure_in_the_past_says_it_already_left(self):
        # "om 0 min" hade låtit som att tåget står kvar på perrongen.
        result = self.options(next_departure_at=NOW - timedelta(minutes=5))
        self.assertEqual(result["next_departure_minutes"], 0)
        self.assertTrue(result["next_departure_departed"])
        self.assertTrue(result["summary"].startswith("Nästa avgång gick"))


class HumanGapTests(TestCase):
    def test_minutes_become_something_a_driver_reads_at_a_glance(self):
        self.assertEqual(human_gap(45), "45 min")
        self.assertEqual(human_gap(60), "1 tim")
        self.assertEqual(human_gap(322), "5 tim 22 min")
