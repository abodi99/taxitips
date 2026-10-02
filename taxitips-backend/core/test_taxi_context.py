"""
Omständigheterna (core/taxi_context.py): rena funktioner, ingen databas.

Varje test är en situation en förare känner igen. Ändras en siffra i
taxi_context ska testet säga vad som hände med förarens bild.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from core import taxi_context as tc

L = ZoneInfo("Europe/Stockholm")
THURSDAY_0730 = datetime(2026, 10, 1, 7, 30, tzinfo=L)
THURSDAY_1200 = datetime(2026, 10, 1, 12, 0, tzinfo=L)
THURSDAY_1630 = datetime(2026, 10, 1, 16, 30, tzinfo=L)
SATURDAY_0730 = datetime(2026, 10, 3, 7, 30, tzinfo=L)
FRIDAY_2230 = datetime(2026, 10, 2, 22, 30, tzinfo=L)
SATURDAY_0200 = datetime(2026, 10, 3, 2, 0, tzinfo=L)


def stranded(base=50, **kw) -> tc.Situation:
    return tc.Situation(base=base, stranded=True, factors=[tc.wait_factor(45)], **kw)


class TimeOfDay(SimpleTestCase):
    def test_rush_is_a_weekday_thing(self):
        self.assertEqual(tc.time_factor(THURSDAY_0730).weight, tc.MORNING_RUSH_BONUS)
        self.assertIsNone(tc.time_factor(SATURDAY_0730))
        self.assertEqual(tc.time_factor(THURSDAY_1630).weight, tc.AFTERNOON_RUSH_BONUS)
        self.assertIsNone(tc.time_factor(THURSDAY_1200))

    def test_evening_and_night_every_day(self):
        self.assertEqual(tc.time_factor(FRIDAY_2230).weight, tc.LATE_EVENING_BONUS)
        self.assertEqual(tc.time_factor(SATURDAY_0200).weight, tc.NIGHT_BONUS)

    def test_utc_input_is_read_as_swedish_time(self):
        from datetime import timezone

        utc = datetime(2026, 10, 1, 5, 30, tzinfo=timezone.utc)  # 07:30 svensk sommartid
        self.assertEqual(tc.time_factor(utc).text, "Morgon en vardag – folk ska till jobbet")


class Weather(SimpleTestCase):
    def test_severe_weighs_more_than_bad(self):
        heavy = tc.weather_factor({"precipitation_mm_h": 4, "precipitation_probability_pct": 80})
        self.assertEqual((heavy.text, heavy.weight), ("Kraftigt regn", tc.SEVERE_WEATHER_BONUS))
        snow = tc.weather_factor({"precipitation_mm_h": 1.2, "precipitation_probability_pct": 70,
                                  "frozen_probability_pct": 80, "temperature_c": -2})
        self.assertEqual(snow.text, "Snöfall")
        light = tc.weather_factor({"precipitation_mm_h": 1.5, "precipitation_probability_pct": 60})
        self.assertEqual((light.text, light.weight), ("Regn", tc.WEATHER_BONUS))
        self.assertIsNone(tc.weather_factor({"precipitation_mm_h": 0, "temperature_c": 12}))


class Assess(SimpleTestCase):
    def test_circumstances_can_make_a_stranding_strong(self):
        noon = tc.assess(stranded(), when=THURSDAY_1200)
        rush = tc.assess(stranded(), when=THURSDAY_0730, compensation={"cap_kr": 2960})
        self.assertEqual(noon.level, "medium")
        self.assertEqual(rush.level, "high")
        texts = [f["text"] for f in rush.factors]
        self.assertIn("Resenären kan få taxin betald (upp till 2 960 kr)", texts)
        self.assertIn("Morgon en vardag – folk ska till jobbet", texts)

    def test_circumstances_never_make_a_non_stranding_strong(self):
        situation = tc.Situation(base=45, stranded=False, factors=[tc.UNCERTAIN])
        o = tc.assess(situation, when=SATURDAY_0200, busy_station=True,
                      weather={"wind_gust_ms": 25}, compensation={"cap_kr": 1480})
        self.assertGreaterEqual(o.score, tc.STRONG_SCORE)
        self.assertEqual(o.level, "medium")

    def test_a_quick_alternative_ignores_circumstances_but_states_the_compensation(self):
        situation = tc.Situation(base=15, stranded=False, quick_alternative=True,
                                 factors=[tc.wait_factor(5, "Nästa tåg")])
        o = tc.assess(situation, when=THURSDAY_0730, busy_station=True, compensation={"cap_kr": 2960})
        self.assertEqual((o.score, o.level), (15, "low"))
        self.assertEqual(o.factors[0], {"text": "Nästa tåg går 5 min senare", "sign": "-"})
        self.assertNotIn("Morgon en vardag – folk ska till jobbet", [f["text"] for f in o.factors])

    def test_circumstances_are_capped(self):
        o = tc.assess(stranded(base=50), when=SATURDAY_0200, busy_station=True,
                      weather={"wind_gust_ms": 25}, compensation={"cap_kr": 1480})
        self.assertEqual(o.score, 50 + tc.CONTEXT_CAP)
        self.assertTrue(any("kapade" in r for r in o.reasons))

    def test_low_confidence_is_never_strong(self):
        o = tc.assess(stranded(base=80, confidence="low"), when=SATURDAY_0200)
        self.assertEqual(o.level, "medium")

    def test_at_most_four_reasons(self):
        o = tc.assess(stranded(), when=SATURDAY_0200, busy_station=True,
                      weather={"wind_gust_ms": 25}, compensation={"cap_kr": 1480})
        self.assertEqual(len(o.factors), 4)
        self.assertEqual(o.factors[0]["text"], "Nästa resa går först 45 min senare")
