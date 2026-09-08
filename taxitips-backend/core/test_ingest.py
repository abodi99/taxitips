"""
Tester för core/ingest.py:s skrivsteg -- särskilt väderbonusen, som är den
enda platsen i pipelinen där något ANNAT än klassificeraren rör poängen.

Bonusen går inte att verifiera mot riktig data på beställning (den kräver att
dåligt väder råkar sammanfalla med en störning på samma ort), så den bevisas
här i stället.
"""

from django.test import TestCase

from core.ingest import WEATHER_BONUS, assess, write
from core.models import Opportunity, ScoringRule, SeverityTier


def _alert(**overrides) -> dict:
    base = {
        "id": "test:1",
        "header": "Stopp i tågtrafiken",
        "description": "Inga tåg går just nu.",
        "cause": None, "effect": None,
        "areas": [], "routes": [], "stops": [], "url": None,
        "region": "skane",
        "active_from": None, "active_to": None,
    }
    base.update(overrides)
    return base


def _weather(point="Malmö", lat=55.605, lon=13.0, **overrides) -> dict:
    base = dict(
        point=point, region="skane", lat=lat, lon=lon,
        temperature_c=10.0, wind_speed_ms=3.0, wind_gust_ms=None,
        precipitation_mm_h=0.0, precipitation_probability_pct=0,
        thunderstorm_probability_pct=0, frozen_probability_pct=0,
    )
    base.update(overrides)
    return base


class WeatherBonus(TestCase):
    def _write_one(self, weather):
        assessed = assess([_alert()])
        write("trafiklab", assessed, weather)
        return Opportunity.objects.get(external_id="test:1")

    def test_calm_weather_leaves_the_score_alone(self):
        before = assess([_alert()])[0][2].score
        o = self._write_one([_weather()])
        self.assertEqual(o.demand_score, before)
        self.assertFalse(any("väder" in r for r in o.reasons))

    def test_adverse_weather_adds_the_bonus_and_says_why(self):
        before = assess([_alert()])[0][2].score
        o = self._write_one([_weather(wind_gust_ms=15.0)])
        self.assertEqual(o.demand_score, min(100, before + WEATHER_BONUS))
        self.assertIn("väder: hård vind", o.reasons)

    def test_bonus_never_pushes_past_100(self):
        # Golvet för whole_line_stop är 85; med bonus hade det blivit 97,
        # men ett larm som redan ligger högt får aldrig gå över 100.
        ScoringRule.objects.update_or_create(
            tier=SeverityTier.LINE_PAUSED, mode="", condition="whole_line_stop",
            defaults={"floor": 95, "confidence": "high"},
        )
        o = self._write_one([_weather(wind_gust_ms=15.0)])
        self.assertEqual(o.demand_score, 100)

    def test_weather_cites_its_own_source_event(self):
        # Utan citeringen kan get_opportunity_detail inte visa VARFÖR poängen
        # höjdes -- den panelen joinar strikt genom source_event_ids.
        o = self._write_one([_weather(wind_gust_ms=15.0)])
        self.assertEqual(len(o.source_event_ids), 2, "störningen + vädret")

    def test_distant_weather_is_not_applied(self):
        # Väder i Kiruna ska inte lyfta ett Malmötips. nearest_weather väljer
        # närmaste punkt, men den enda punkten här är långt borta och lugn.
        o = self._write_one([_weather(point="Kiruna", lat=67.85, lon=20.23)])
        self.assertFalse(any("väder" in r for r in o.reasons))

    def test_ignored_alerts_never_get_weather(self):
        # Väder får skärpa en signal, aldrig skapa en.
        assessed = assess([_alert(header="Hissen ur funktion", description="")])
        write("trafiklab", assessed, [_weather(wind_gust_ms=15.0)])
        o = Opportunity.objects.get(external_id="test:1")
        self.assertEqual(o.severity_tier, SeverityTier.IGNORE)
        self.assertFalse(any("väder" in r for r in o.reasons))


class RegionIsNullNotEmpty(TestCase):
    def test_unknown_region_is_written_as_null(self):
        # get_smart_alerts gör coalesce(region,'skane') för platslösa tips.
        # Tom sträng hade matchat ingen marknad alls -- tipset hade
        # försvunnit tyst ur förarflödet.
        assessed = assess([_alert(region=None)])
        write("trafiklab", assessed, [])
        o = Opportunity.objects.get(external_id="test:1")
        self.assertIsNone(o.region)
