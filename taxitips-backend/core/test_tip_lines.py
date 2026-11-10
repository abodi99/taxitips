"""Tipsets två korta rader (core/tip_lines.py): ett fall per regel, plus ordgränserna."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from django.test import SimpleTestCase

from core import tip_lines

UTC = dt.timezone.utc
# 2026-11-09 22:00 svensk tid (vintertid, UTC+1).
NOW = dt.datetime(2026, 11, 9, 21, 0, tzinfo=UTC)


def at(hour: int, minute: int = 0, day: int = 9) -> dt.datetime:
    """Svensk klocktid i november (UTC+1) som aware datetime."""
    return dt.datetime(2026, 11, day, hour - 1, minute, tzinfo=UTC)


def tip(**kw):
    base = dict(
        rule_id="", mode="train", kind="transit", severity_tier="line_paused",
        next_departure_at=None, next_departure_minutes=None, is_last_departure=False,
        has_alternative=False, delay_minutes=None, departure_at=None,
        start_time=None, end_time=None, title="", summary="", places=[], line="",
    )
    base.update(kw)
    return SimpleNamespace(**base)


# (namn, tips, headline, decision, ton)
CASES = [
    ("train long gap, clock", tip(rule_id="train.line_paused.long_gap", next_departure_at=at(23, 48)),
     "Tåg inställt", "Nästa tåg 23:48", "go"),
    ("train long gap, minutes only", tip(rule_id="train.line_paused.long_gap", next_departure_minutes=60),
     "Tåg inställt", "Nästa 1 tim senare", "go"),
    ("long gap, odd minutes round to hours", tip(rule_id="train.line_paused.long_gap", next_departure_minutes=80),
     "Tåg inställt", "Nästa 1 tim senare", "go"),
    ("train last departure", tip(rule_id="train.line_paused.last_departure", is_last_departure=True),
     "Sista tåget inställt", "Inget mer i kväll", "go"),
    ("bus last departure by flag", tip(rule_id="bus.vehicle_cancelled.single_departure", mode="bus", is_last_departure=True),
     "Sista bussen inställd", "Inget mer i kväll", "go"),
    ("whole line stop", tip(rule_id="train.line_paused.whole_line_stop"),
     "Linjen står still", "Ingen trafik", "go"),
    ("alternative soon, quick", tip(rule_id="train.vehicle_cancelled.alternative_soon", next_departure_minutes=10),
     "Tåg inställt", "Nästa 10 min senare", "no"),
    ("alternative soon, slower", tip(rule_id="train.vehicle_cancelled.alternative_soon", next_departure_minutes=25),
     "Tåg inställt", "Nästa 25 min senare", "wait"),
    ("replacement", tip(rule_id="train.vehicle_cancelled.replacement", has_alternative=True),
     "Tåg inställt", "Buss ersätter", "no"),
    ("has_alternative without replacement rule", tip(rule_id="train.line_paused.long_gap", has_alternative=True),
     "Tåg inställt", "Buss ersätter", "no"),
    ("stated alternative bus", tip(rule_id="bus.vehicle_cancelled.stated_alternative", mode="bus"),
     "Buss inställd", "Annan resa finns", "no"),
    ("stated alternative tram", tip(rule_id="tram.vehicle_cancelled.stated_alternative", mode="tram"),
     "Spårvagn inställd", "Annan resa finns", "no"),
    ("single departure bus", tip(rule_id="bus.vehicle_cancelled.single_departure", mode="bus"),
     "Buss inställd", "Nästa går snart", "no"),
    ("single departure metro", tip(rule_id="metro.vehicle_cancelled.single_departure", mode="metro"),
     "Tunnelbana inställd", "Nästa går snart", "no"),
    ("single departure boat", tip(rule_id="boat.vehicle_cancelled.single_departure", mode="boat", kind="transit"),
     "Båt inställd", "Nästa går snart", "no"),
    ("single departure unknown mode", tip(rule_id="unknown.vehicle_cancelled.single_departure", mode="unknown"),
     "Avgång inställd", "Nästa går snart", "no"),
    ("known gap, long", tip(rule_id="bus.line_paused.known_gap", mode="bus", next_departure_minutes=45),
     "Buss inställd", "Nästa 45 min senare", "go"),
    ("known gap, short", tip(rule_id="bus.vehicle_cancelled.known_gap", mode="bus", next_departure_minutes=8),
     "Buss inställd", "Nästa 8 min senare", "no"),
    ("line paused unknown", tip(rule_id="train.line_paused.unknown"),
     "Stopp i trafiken", "Oklart läge", "wait"),
    ("ambiguous", tip(rule_id="train.line_paused.ambiguous"),
     "Stopp i trafiken", "Oklart läge", "wait"),
    ("unclassified", tip(rule_id="unknown.unclassified", mode="unknown", severity_tier="disruption_unclassified"),
     "Störning", "Oklart läge", "wait"),
    ("cancelled bus, nothing more known", tip(rule_id="bus.vehicle_cancelled.serious", mode="bus",
                                              severity_tier="vehicle_cancelled"),
     "Buss inställd", "Oklart läge", "wait"),
    ("train delayed", tip(rule_id="train.line_delayed", severity_tier="line_delayed",
                          delay_minutes=51, departure_at=at(23, 26)),
     "Tåg 51 min sent", "Kommer 00:17", "wait"),
    ("train delayed without minutes", tip(rule_id="train.line_delayed", severity_tier="line_delayed"),
     "Tåg sent", "", "wait"),
    ("bus delayed", tip(rule_id="bus.vehicle_delayed.mediumish", mode="bus", severity_tier="vehicle_delayed",
                        delay_minutes=12, departure_at=at(20, 0)),
     "Buss 12 min sen", "Kommer 20:12", "wait"),
    ("bus delayed, text only", tip(rule_id="bus.vehicle_delayed.watched_line_notice", mode="bus",
                                   severity_tier="vehicle_delayed"),
     "Buss sen", "", "wait"),
    ("flight wave", tip(rule_id="flight.arrival_wave", mode="flight", kind="flight", severity_tier="arrival_wave",
                        summary="8 plan landar mellan 23:30 och 00:00."),
     "8 plan landar", "23:30–00:00", "wait"),
    ("flight wave, unparsable summary", tip(rule_id="flight.arrival_wave", mode="flight", kind="flight",
                                            severity_tier="arrival_wave", summary="", start_time=at(23, 30)),
     "Många plan landar", "23:30", "wait"),
    ("flight last arrival", tip(rule_id="flight.last_arrival", mode="flight", kind="flight",
                                severity_tier="last_arrival", start_time=at(23, 0)),
     "Sista planet", "Landar 23:00", "go"),
    ("ferry", tip(rule_id="boat.arrival_wave", mode="boat", kind="ferry", severity_tier="arrival_wave",
                  summary="Stor färja väntas lägga till kl 23:00.", start_time=at(23, 0)),
     "Färja kommer", "23:00", "wait"),
    ("ferry, clock from start_time", tip(rule_id="boat.arrival_wave", mode="boat", kind="ferry",
                                         severity_tier="arrival_wave", summary="", start_time=at(22, 15)),
     "Färja kommer", "22:15", "wait"),
    ("road accident", tip(rule_id="road.road_accident_or_closure.accident", mode="road", kind="road",
                          severity_tier="road_accident_or_closure"),
     "Olycka", "", "no"),
    ("ignore tier", tip(rule_id="bus.ignore.facility", mode="bus", severity_tier="ignore", title="Hållplats flyttad"),
     "", "", "wait"),
]


class TipLinesTests(SimpleTestCase):
    def test_every_rule_row(self):
        for name, o, headline, decision, tone in CASES:
            with self.subTest(name):
                got = tip_lines.lines_for(o, now=NOW)
                self.assertEqual(got, {"headline": headline, "decision": decision, "decision_tone": tone})

    def test_word_limits_and_plain_characters(self):
        """Raderna ska läsas på en sekund: högst 4 ord rubrik, högst 5 ord beslut, inga tankstreck."""
        for name, o, _h, _d, _t in CASES:
            got = tip_lines.lines_for(o, now=NOW)
            with self.subTest(name):
                self.assertLessEqual(len(got["headline"].split()), 4)
                self.assertLessEqual(len(got["decision"].split()), 5)
                self.assertNotIn("—", got["headline"] + got["decision"])

    def test_every_mode_gets_correct_gender(self):
        expected = {
            "train": "Tåg inställt", "bus": "Buss inställd", "metro": "Tunnelbana inställd",
            "tram": "Spårvagn inställd", "boat": "Båt inställd", "unknown": "Avgång inställd",
        }
        for mode, text in expected.items():
            with self.subTest(mode):
                o = tip(rule_id=f"{mode}.vehicle_cancelled.single_departure", mode=mode)
                self.assertEqual(tip_lines.lines_for(o, now=NOW)["headline"], text)

    def test_last_departure_names_the_vehicle_in_correct_gender(self):
        expected = {
            "train": "Sista tåget inställt", "bus": "Sista bussen inställd",
            "metro": "Sista tunnelbanan inställd", "tram": "Sista spårvagnen inställd",
            "boat": "Sista båten inställd",
        }
        for mode, text in expected.items():
            with self.subTest(mode):
                o = tip(rule_id=f"{mode}.line_paused.last_departure", mode=mode, is_last_departure=True)
                self.assertEqual(tip_lines.lines_for(o, now=NOW)["headline"], text)

    def test_gap_is_counted_from_the_cancelled_departure_not_from_now(self):
        """
        Tipset visas upp till två timmar i förväg. Glappet är avståndet mellan
        den inställda avgången och nästa, och raden är två klockslag.
        """
        o = tip(rule_id="train.vehicle_cancelled.alternative_soon",
                departure_at=NOW + dt.timedelta(hours=2),
                next_departure_at=NOW + dt.timedelta(hours=2, minutes=10))
        got = tip_lines.lines_for(o, now=NOW)
        self.assertRegex(got["headline"], r"^Tåg \d{2}:\d{2} inställt$")
        self.assertRegex(got["decision"], r"^Nästa tåg \d{2}:\d{2}$")
        self.assertEqual(got["decision_tone"], "no")

    def test_long_gap_with_both_clocks(self):
        o = tip(rule_id="train.line_paused.long_gap", departure_at=at(22, 48), next_departure_at=at(23, 48))
        self.assertEqual(
            tip_lines.lines_for(o, now=NOW),
            {"headline": "Tåg 22:48 inställt", "decision": "Nästa tåg 23:48", "decision_tone": "go"},
        )

    def test_the_line_names_the_vehicle_when_it_is_short(self):
        """Fyra kort med "Centralen · Buss sen" gick inte att skilja åt."""
        delayed = tip(rule_id="bus.vehicle_delayed.mediumish", mode="bus", severity_tier="vehicle_delayed",
                      line="Buss 190", title="Förseningar",
                      summary="Förseningar upp till 10 minuter för buss linje 190 från Farsta strand 02:14.")
        self.assertEqual(
            tip_lines.lines_for(delayed, now=NOW),
            {"headline": "Buss 190 sen", "decision": "Upp till 10 min", "decision_tone": "wait"},
        )
        cancelled = tip(rule_id="train.line_paused.long_gap", line="Pendeltåg 41",
                        departure_at=at(22, 48), next_departure_at=at(23, 48))
        self.assertEqual(tip_lines.lines_for(cancelled, now=NOW)["headline"], "Pendeltåg 41 22:48 inställt")
        unknown = tip(rule_id="unknown.vehicle_delayed.ai_facts.short_delay", mode="unknown",
                      severity_tier="vehicle_delayed", line="Linje 890",
                      summary="Linje 890 mot Centralen beräknas vara cirka 10 minuter försenad.")
        self.assertEqual(
            tip_lines.lines_for(unknown, now=NOW),
            {"headline": "Linje 890 sen", "decision": "Cirka 10 min", "decision_tone": "wait"},
        )

    def test_a_named_line_on_rails_is_not_neuter(self):
        o = tip(rule_id="train.vehicle_cancelled.stated_alternative", line="Lidingöbanan")
        self.assertEqual(tip_lines.lines_for(o, now=NOW)["headline"], "Lidingöbanan inställd")

    def test_long_or_replacement_lines_fall_back_to_the_mode(self):
        long_name = tip(rule_id="train.line_delayed", severity_tier="line_delayed", line="SJ Snabbtåg 451",
                        delay_minutes=51, departure_at=at(23, 26))
        self.assertEqual(tip_lines.lines_for(long_name, now=NOW)["headline"], "Tåg 51 min sent")
        replacement = tip(rule_id="train.vehicle_cancelled.stated_alternative", line="Ersättningsbuss 21B")
        self.assertEqual(tip_lines.lines_for(replacement, now=NOW)["headline"], "Tåg inställt")

    def test_works_without_optional_fields(self):
        got = tip_lines.lines_for(SimpleNamespace(rule_id="train.line_paused.long_gap"), now=NOW)
        self.assertEqual(got["headline"], "Tåg inställt")
        self.assertEqual(tip_lines.lines_for(SimpleNamespace(), now=NOW)["headline"], "Stopp i trafiken")
