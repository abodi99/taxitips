"""
Linje, hållplats och klockslag ur trafikbolagens fritext (core/tip_text.py).

Texterna är verkliga mallar ur produktionen och den lokala databasen
(2026-09-20 -- 2026-10-08): SL, Värmlandstrafik, Östgötatrafiken, Skånetrafiken,
UL, Västtrafik, X-trafik, Din Tur.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.test import SimpleTestCase, TestCase

from core import tip_text
from core.models import Station, StopArea
from core.tip_text import extract, line_label, registry_coords, text_key


class LineTests(SimpleTestCase):
    def test_the_line_as_a_driver_says_it(self):
        cases = [
            ("Förseningar upp till 10 minuter för buss linje 725 från Tumba station", "", "Buss 725"),
            ("Förseningar upp till 10 minuter för blåbuss linje 175 på grund av", "", "Blåbuss 175"),
            ("Stadsbuss Malmö linje 11 mot Elinelund stannar inte vid", "", "Buss 11"),
            ("Förseningar på tunnelbanans gröna linje mot Skarpnäck", "metro", "Tunnelbanans gröna linje"),
            ("Pågatåg 1612 från Malmö C kl 07:12 är inställt", "train", "Pågatåg 1612"),
            ("Västtågen 3104 klockan 13:34 är försenat", "train", "Västtåg 3104"),
            ("Spårvagn 7 mot Bergsjön är inställd", "tram", "Spårvagn 7"),
            ("Försening på 10 minuter för Lidingöbanan 21 från Baggeby", "tram", "Lidingöbanan 21"),
            ("Tvärbanan: Stopp mellan Liljeholmen och Stora Essingen", "tram", "Tvärbanan"),
            ("Linje 2 Ilanda bytespunkt, Karlstad kl 21:54", "bus", "Buss 2"),
            ("Linje S Golfbanan Jakobsberg, Karlstad kl 9:44", "", "Linje S"),
            ("Försening på linje 302 mot Väster", "", "Linje 302"),
        ]
        for text, mode, expected in cases:
            self.assertEqual(line_label(text, mode=mode), expected, text)

    def test_a_structured_line_field_wins_but_a_generic_one_is_ignored(self):
        self.assertEqual(line_label("vad som helst", route_label="Blåbuss 176"), "Blåbuss 176")
        self.assertEqual(line_label("", route_label="6", mode="tram"), "Spårvagn 6")
        self.assertEqual(line_label("", route_label="X4", mode="bus"), "Buss X4")
        # Västtrafik sätter "TÅG" på alla tåg: läs numret ur texten i stället.
        self.assertEqual(line_label("Västtågen 3265 klockan 17:09", route_label="TÅG", mode="train"), "Västtåg 3265")

    def test_a_lowercase_word_after_linjen_is_not_a_line(self):
        self.assertEqual(line_label("Linjen i båda riktningar är inställd."), "")


class StationTests(SimpleTestCase):
    def test_the_two_examples_from_the_owner(self):
        tumba = extract("Förseningar", "Förseningar upp till 10 minuter för buss linje 725 från Tumba station "
                                       "16:58 mot Söderby park på grund av framkomlighetsproblem.")
        self.assertEqual((tumba.line, tumba.station, tumba.destination), ("Buss 725", "Tumba station", "Söderby park"))
        self.assertEqual((tumba.departure_clock, tumba.delay_minutes, tumba.delay_qualifier), ("16:58", 10, "upp till"))
        karolinska = extract("Ny avgångstid", "Avgången från Karolinska sjukhuset norra kl 16:01 till Sollentuna "
                                              "station är cirka 9 minuter försenad pga framkomlighetsproblem.")
        self.assertEqual(karolinska.station, "Karolinska sjukhuset norra")
        self.assertEqual(karolinska.destination, "Sollentuna station")
        self.assertEqual((karolinska.departure_clock, karolinska.delay_minutes, karolinska.delay_qualifier),
                         ("16:01", 9, "cirka"))

    def test_templates_from_the_regional_operators(self):
        cases = [
            # Värmlandstrafik: orten efter kommat hör till namnet.
            ("Linje 2 försenad mot Vammelsvägen, Karlstad",
             "Linje 2 Ilanda bytespunkt, Karlstad kl 21:54 mot Vammelsvägen, Karlstad beräknas vara försenad 10 minuter eller mer.",
             "Ilanda bytespunkt, Karlstad", "Vammelsvägen, Karlstad", "21:54"),
            ("Försening på linje 501 mot Skattkärr Karlstad",
             "11 minuters försening registrerades från Arnövägen, Väse klockan 17.42. Se reseplaneraren för mera information.",
             "Arnövägen, Väse", "Skattkärr Karlstad", "17:42"),
            # Östgötatrafiken: "A - B kl HH:MM".
            ("Buss linje 540 är försenad", "Linköpings resecentrum - Kisa resecentrum kl 18:50 är försenad på grund av trafikköer. ",
             "Linköpings resecentrum", "Kisa resecentrum", "18:50"),
            # UL: klockslaget före "från".
            ("Avgången kl 8:53 från Knutby skola mot Uppsala Centralstationen försenad",
             "Avgången kl 8:53 från Knutby skola är cirka 15 minuter försenad.",
             "Knutby skola", "Uppsala Centralstationen", "08:53"),
            # Skånetrafiken: "Tåget är inställt A - B."
            ("Inställd - Övriga avgångar", "Tåget är inställt Malmö Hyllie - Malmö C. Orsaken är planeringsfel.",
             "Malmö Hyllie", "Malmö C", ""),
            # SL: "mellan A kl HH:MM och B".
            ("Inställd avgång", "Inställd avgång för buss linje 55 mellan Tjärhovsplan kl 20:04 och Tanto pga personalbrist.",
             "Tjärhovsplan", "", "20:04"),
            # Västtrafik: klockslaget står före "är inställt från".
            ("Västtågen 3265 klockan 17:09 är inställt från Vänersborg resecentrum till Göteborg Central.",
             "Orsaken är fordonsfel.", "Vänersborg resecentrum", "Göteborg Central", "17:09"),
        ]
        for header, description, station, destination, clock in cases:
            facts = extract(header, description)
            self.assertEqual((facts.station, facts.destination, facts.departure_clock),
                             (station, destination, clock), description)

    def test_every_name_is_a_literal_part_of_the_text(self):
        fixture = Path(__file__).resolve().parent / "fixtures" / "golden_extraction.jsonl"
        for line in fixture.read_text(encoding="utf-8").splitlines():
            case = json.loads(line)
            text = f"{case['title']}\n{case['summary']}"
            facts = extract(case["title"], case["summary"], route_label=case.get("route_label"), mode=case["mode"])
            for name in facts.places:
                self.assertTrue(tip_text.literal(name, text), (name, text))

    def test_a_referral_is_not_where_the_disruption_is(self):
        facts = extract(
            "Stängd hållplats",
            "Regionbuss linje 159 stannar inte vid Lund Motorvägsbron (läge A och B) på grund av vägarbete. "
            "Hänvisning till Professorsgatan (läge A och B), cirka 1,2 km västerut, på Tornavägen.",
        )
        self.assertEqual(facts.station, "Lund Motorvägsbron")
        self.assertNotIn("Professorsgatan", facts.places)
        self.assertNotIn("Tornavägen", facts.places)

    def test_a_clock_that_is_not_a_departure_is_not_one(self):
        facts = extract("Stopp i tågtrafiken",
                        "Det är stopp i tågtrafiken mellan Göteborg och Kungsbacka sedan klockan 08:30.")
        self.assertEqual(facts.stops, ["Göteborg", "Kungsbacka"])
        self.assertEqual(facts.departure_clock, "")
        self.assertEqual(facts.clocks, ["08:30"])

    def test_the_destination_alone_is_not_a_station(self):
        facts = extract("Försening på linje 661 mot Skänninge",
                        "En försening har registrerats på din bevakade linje. Sök din resa i appen.")
        self.assertEqual((facts.station, facts.destination), ("", "Skänninge"))
        self.assertEqual(facts.places, ["Skänninge"])

    def test_nothing_is_invented(self):
        facts = extract("Försenad p.g.a. tekniskt fel", "Försenad p.g.a. tekniskt fel")
        self.assertEqual((facts.line, facts.station, facts.places, facts.delay_minutes), ("", "", [], None))

    def test_delay_wording_is_kept(self):
        self.assertEqual(tip_text.delay("Försenad ca. 20-30 minuter p.g.a. tekniskt fel."), (30, "mellan 20 och"))
        self.assertEqual(tip_text.delay("är försenad ca. 7 minuter."), (7, "cirka"))
        self.assertEqual(tip_text.delay("11 minuters försening registrerades"), (11, ""))
        # Minuter utan försening i meningen är ingen försening.
        self.assertIsNone(tip_text.delay("Ersättningsbussen går var 30 minut."))


class TextKeyTests(SimpleTestCase):
    def test_the_same_message_has_the_same_key_whatever_the_whitespace(self):
        a = text_key("Förseningar", "Förseningar upp till 10  minuter\nför buss linje 725.")
        b = text_key("förseningar", "Förseningar upp till 10 minuter för buss linje 725.")
        self.assertEqual(a, b)
        self.assertEqual(len(a), 40)
        self.assertNotEqual(a, text_key("Förseningar", "Förseningar upp till 15 minuter för buss linje 725."))


class RegistryTests(TestCase):
    def setUp(self):
        tip_text.reset_registry()
        self.addCleanup(tip_text.reset_registry)

    def test_the_stop_register_gives_the_coordinate_within_the_operator(self):
        StopArea.objects.create(gid="sl:1", operator="sl", name="Tumba", lat=59.1993, lon=17.8358)
        self.assertEqual(registry_coords("Tumba station", "sl"), (59.1993, 17.8358))
        # Västtrafiks register gäller inte ett SL-tips.
        self.assertIsNone(registry_coords("Tumba station", "vt"))

    def test_a_name_in_two_places_gives_no_coordinate(self):
        StopArea.objects.create(gid="sl:1", operator="sl", name="Mörby", lat=59.398, lon=18.036)
        StopArea.objects.create(gid="sl:2", operator="sl", name="Mörby", lat=58.905, lon=17.95)
        self.assertIsNone(registry_coords("Mörby", "sl"))

    def test_two_stop_points_of_the_same_stop_are_one_place(self):
        StopArea.objects.create(gid="sl:1", operator="sl", name="Slussen", lat=59.3195, lon=18.0721)
        StopArea.objects.create(gid="sl:2", operator="sl", name="Slussen", lat=59.3200, lon=18.0730)
        self.assertEqual(registry_coords("Slussen", "sl"), (59.3195, 18.0721))

    def test_rail_stations_are_used_but_never_outside_the_county(self):
        Station.objects.create(signature="Lu", name="Lund C", lat=55.7058, lon=13.1866)
        self.assertEqual(registry_coords("Lund C", "skane"), (55.7058, 13.1866))
        # Ett Östgötatrafiken-tips om "Lund C" är inte i Skåne.
        self.assertIsNone(registry_coords("Lund C", "otraf"))

    def test_an_unknown_name_gives_nothing(self):
        self.assertIsNone(registry_coords("Ingenstans", "sl"))
        self.assertIsNone(registry_coords("", "sl"))
