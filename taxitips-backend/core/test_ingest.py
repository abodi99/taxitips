"""
Tester för core/ingest.py:s skrivsteg -- särskilt omständigheterna (väder,
tid), den enda platsen i fritextens pipeline där något ANNAT än
klassificeraren rör poängen.

Väder går inte att verifiera mot riktig data på beställning (det kräver att
dåligt väder råkar sammanfalla med en störning på samma ort), så det bevisas
här i stället.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from django.test import TestCase

from core import taxi_context
from core.ingest import assess, write
from core.models import Opportunity, ScoringRule, SeverityTier
from core.taxi_context import SEVERE_WEATHER_BONUS, WEATHER_BONUS

# En lördag mitt på dagen: ingen tidsomständighet, så att bara vädret syns.
SATURDAY_NOON = datetime(2027, 1, 2, 12, 0, tzinfo=ZoneInfo("Europe/Stockholm"))


def _alert(**overrides) -> dict:
    base = {
        "id": "test:1",
        "header": "Stopp i tågtrafiken",
        "description": "Inga tåg går just nu.",
        "cause": None, "effect": None,
        "areas": [], "routes": [], "stops": [], "url": None,
        "region": "skane",
        "active_from": SATURDAY_NOON, "active_to": None,
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
        self.assertIn(f"väder: Hård vind (+{WEATHER_BONUS})", o.reasons)
        self.assertIn({"text": "Hård vind", "sign": "+"}, o.factors)

    def test_severe_weather_weighs_more(self):
        before = assess([_alert()])[0][2].score
        o = self._write_one([_weather(wind_gust_ms=21.0)])
        self.assertEqual(o.demand_score, min(100, before + SEVERE_WEATHER_BONUS))
        self.assertIn({"text": "Hård blåst", "sign": "+"}, o.factors)

    def test_bonus_never_pushes_past_100(self):
        ScoringRule.objects.update_or_create(
            tier=SeverityTier.LINE_PAUSED, mode="", condition="whole_line_stop",
            defaults={"floor": 99, "cap": None, "confidence": "high"},
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


class RoadIsNeverLiftedByWeather(TestCase):
    def test_road_alerts_keep_their_cap_in_bad_weather(self):
        from core import thresholds

        assessed = assess([_alert(id="road:1", header="Olycka på E6", description="Olycka, ett körfält avstängt.")])
        write("trafikverket_road", assessed, [_weather(wind_gust_ms=15.0)], kind="road")
        o = Opportunity.objects.get(external_id="road:1")
        self.assertLessEqual(o.demand_score, max(thresholds.ROAD_SCORE_CAP, assessed[0][2].score))
        self.assertFalse(any("väder" in r for r in o.reasons))


class StoredLevelFollowsTheFeedRule(TestCase):
    def test_written_level_is_the_final_level(self):
        assessed = assess([_alert()])
        write("trafiklab", assessed, [])
        o = Opportunity.objects.get(external_id="test:1")
        # "Stopp i tågtrafiken": hela linjen, strandsatt.
        self.assertEqual(
            o.level, taxi_context.final_level(o.demand_score, True, o.has_alternative, o.confidence),
        )
        self.assertEqual(o.level, "high")
        self.assertEqual(o.factors[0], {"text": "Hela linjen står still", "sign": "+"})

    def test_a_single_departure_is_weak_and_short_lived(self):
        """SL 2026-09-30: en inställd tunnelbaneavgång blev "Hela linjen stoppad" 85 och push."""
        assessed = assess([_alert(
            header="Inställd avgång",
            description="Hagsätra - Vällingby kl 16:59 är inställd 2026-09-30 på grund av tekniskt fel.",
            region="sl", active_from=datetime(2026, 9, 30, 16, 30, tzinfo=ZoneInfo("Europe/Stockholm")),
        )])
        write("sl", assessed, [])
        o = Opportunity.objects.get(external_id="test:1")
        self.assertTrue(o.rule_id.endswith(".single_departure"), o.rule_id)
        self.assertEqual(o.level, "low")
        self.assertEqual(
            o.end_time, datetime(2026, 9, 30, 17, 44, tzinfo=ZoneInfo("Europe/Stockholm")),
        )


class FutureSingleDeparture(TestCase):
    """Vy Tåg 382 den 7 oktober syntes som aktivt tips från den 2 oktober (2026-10-02)."""

    def test_it_starts_an_hour_before_the_departure_on_the_given_date(self):
        published = datetime(2026, 10, 2, 15, 34, tzinfo=ZoneInfo("Europe/Stockholm"))
        alert = _alert(
            region="vt", active_from=published,
            header="Vy Tåg 382, 7 oktober klockan 06:14, är inställt från Göteborg Central till Halden stasjon",
            description="För mer information, kontakta Vy Tåg. Orsaken är strejk.",
        )
        write("vasttrafik", assess([alert]), [])
        o = Opportunity.objects.get(external_id="test:1")
        departure = datetime(2026, 10, 7, 6, 14, tzinfo=ZoneInfo("Europe/Stockholm"))
        self.assertEqual(o.severity_tier, SeverityTier.VEHICLE_CANCELLED)
        self.assertEqual(o.departure_at, departure)
        self.assertEqual(o.start_time, datetime(2026, 10, 7, 5, 14, tzinfo=ZoneInfo("Europe/Stockholm")))
        self.assertLessEqual(o.end_time, datetime(2026, 10, 7, 7, 0, tzinfo=ZoneInfo("Europe/Stockholm")))


class PlannedFutureMaintenanceAndExpiration(TestCase):
    def test_planned_future_disruption_starts_on_stated_date(self):
        published = datetime(2026, 9, 29, 14, 21, tzinfo=ZoneInfo("Europe/Stockholm"))
        alert = _alert(
            id="sl:planned1",
            region="sl",
            active_from=published,
            header="Kommande: Spårvagnslinje 21 ersätts med buss 10–15 oktober på grund av banarbete",
            description="Från lördag 10 oktober till torsdag 15 oktober är spårvagnstrafiken på Lidingöbanan ersatt med bussar.",
        )
        write("sl", assess([alert]), [])
        o = Opportunity.objects.get(external_id="sl:planned1")
        self.assertEqual(o.start_time, datetime(2026, 10, 10, 0, 0, tzinfo=ZoneInfo("Europe/Stockholm")))
        self.assertTrue(o.has_alternative)

    def test_vanished_alert_is_expired_on_next_write(self):
        from django.utils import timezone

        now = timezone.now()
        a1 = _alert(id="sl:keep", region="sl", active_from=now)
        a2 = _alert(id="sl:vanish", region="sl", active_from=now)
        write("sl", assess([a1, a2]), [])
        self.assertIsNone(Opportunity.objects.get(external_id="sl:vanish").end_time)

        # Nästa poll har bara kvar sl:keep -> sl:vanish ska avslutas med source_removed.
        write("sl", assess([a1]), [])
        vanished = Opportunity.objects.get(external_id="sl:vanish")
        self.assertEqual(vanished.expired_reason, "source_removed")
        self.assertIsNotNone(vanished.end_time)
        self.assertLessEqual(vanished.end_time, timezone.now())

