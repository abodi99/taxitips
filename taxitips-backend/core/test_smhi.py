"""
Tester för core/sources/smhi.py.

Trösklarna är porterade tal från worker/src/smhi.js -- de här testerna finns
för att de ska ändras medvetet, inte av misstag. Varje gräns testas på båda
sidor, och defaultvärdena (saknad temperatur = 99, dvs aldrig halka) har egna
fall eftersom de är lätta att tappa i en port.
"""

from django.test import TestCase

from core.sources.smhi import (
    describe_weather,
    is_adverse_weather,
    nearest_weather,
    summarize,
    weather_points,
)


def _w(**overrides) -> dict:
    base = dict(
        point="Malmö", region="skane", lat=55.605, lon=13.0,
        temperature_c=10.0, wind_speed_ms=3.0, wind_gust_ms=None,
        precipitation_mm_h=0.0, precipitation_probability_pct=0,
        thunderstorm_probability_pct=0, frozen_probability_pct=0,
    )
    base.update(overrides)
    return base


class Thresholds(TestCase):
    def test_calm_weather_is_not_adverse(self):
        self.assertFalse(is_adverse_weather(_w()))

    def test_no_weather_at_all_is_not_adverse(self):
        self.assertFalse(is_adverse_weather(None))

    def test_rain_needs_both_amount_and_probability(self):
        # 1.0 mm/h men bara 39 % sannolikhet -- under gränsen.
        self.assertFalse(is_adverse_weather(
            _w(precipitation_mm_h=1.0, precipitation_probability_pct=39)))
        self.assertTrue(is_adverse_weather(
            _w(precipitation_mm_h=1.0, precipitation_probability_pct=40)))

    def test_gust_wins_over_sustained_wind(self):
        # Medelvind under gränsen, byvind över -- byvinden ska avgöra.
        self.assertTrue(is_adverse_weather(_w(wind_speed_ms=3.0, wind_gust_ms=12.0)))
        self.assertFalse(is_adverse_weather(_w(wind_speed_ms=3.0, wind_gust_ms=11.9)))

    def test_sustained_wind_used_when_no_gust_reported(self):
        self.assertTrue(is_adverse_weather(_w(wind_speed_ms=12.0, wind_gust_ms=None)))

    def test_thunder_threshold(self):
        self.assertFalse(is_adverse_weather(_w(thunderstorm_probability_pct=29)))
        self.assertTrue(is_adverse_weather(_w(thunderstorm_probability_pct=30)))

    def test_freezing_needs_both_cold_and_frozen_precipitation(self):
        self.assertFalse(is_adverse_weather(_w(temperature_c=0.0, frozen_probability_pct=39)))
        self.assertTrue(is_adverse_weather(_w(temperature_c=0.0, frozen_probability_pct=40)))

    def test_missing_temperature_never_counts_as_freezing(self):
        # Defaulten 99 är betydelsebärande: utan den hade en saknad
        # temperatur läst som 0 grader och gett falsk halka.
        self.assertFalse(is_adverse_weather(
            _w(temperature_c=None, frozen_probability_pct=90)))


class Descriptions(TestCase):
    def test_rain_and_snow_are_distinguished_by_frozen_probability(self):
        rain = _w(precipitation_mm_h=2.0, precipitation_probability_pct=80)
        self.assertEqual(describe_weather(rain), "regn")
        snow = _w(precipitation_mm_h=2.0, precipitation_probability_pct=80,
                  frozen_probability_pct=80, temperature_c=5.0)
        self.assertEqual(describe_weather(snow), "snöfall")

    def test_several_conditions_are_joined(self):
        w = _w(precipitation_mm_h=2.0, precipitation_probability_pct=80,
               wind_gust_ms=15.0, thunderstorm_probability_pct=50)
        self.assertEqual(describe_weather(w), "regn, hård vind, åska")

    def test_calm_weather_has_nothing_to_say(self):
        self.assertIsNone(describe_weather(_w()))


class Nearest(TestCase):
    def test_picks_the_closest_point(self):
        points = [
            _w(point="Malmö", lat=55.605, lon=13.0),
            _w(point="Stockholm", lat=59.33, lon=18.06),
        ]
        self.assertEqual(nearest_weather(59.3, 18.0, points)["point"], "Stockholm")
        self.assertEqual(nearest_weather(55.7, 13.2, points)["point"], "Malmö")

    def test_missing_coordinates_give_no_weather(self):
        points = [_w()]
        self.assertIsNone(nearest_weather(None, 13.0, points))
        self.assertIsNone(nearest_weather(55.6, None, points))
        self.assertIsNone(nearest_weather(55.6, 13.0, []))


class Points(TestCase):
    def test_points_are_national_not_skane_only(self):
        # Node har sju hårdkodade Skåne-punkter kvar sedan före den
        # nationella utrullningen -- porten härleder dem ur REGION_ANCHOR.
        with self.settings(MARKET_SCOPE="national"):
            points = weather_points()
        names = {p["point"] for p in points}
        self.assertIn("Malmö", names)
        self.assertIn("Stockholm", names)
        self.assertIn("Göteborg", names)
        self.assertGreaterEqual(len(points), 15)


class Summarize(TestCase):
    def test_reads_the_first_time_step(self):
        # snow1g-formen: platt `data`-dict och `time`, INTE pmp3g:s
        # `parameters`-lista med `validTime`. Verifierat mot ett riktigt svar
        # -- porten läste först fel form och fick bara None:er.
        raw = {"timeSeries": [{
            "time": "2026-09-08T12:00:00Z",
            "data": {"air_temperature": 7.5, "wind_speed_of_gust": 14.0},
        }]}
        out = summarize(raw, {"point": "Malmö", "region": "skane", "lat": 55.6, "lon": 13.0})
        self.assertEqual(out["temperature_c"], 7.5)
        self.assertEqual(out["wind_gust_ms"], 14.0)
        self.assertEqual(out["observed_at"], "2026-09-08T12:00:00Z")
        self.assertIsNone(out["thunderstorm_probability_pct"])

    def test_empty_forecast_gives_nothing(self):
        self.assertIsNone(summarize({"timeSeries": []}, {"point": "x", "region": "y", "lat": 1, "lon": 2}))
