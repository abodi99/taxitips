"""
Tester för SL:s "nästa avgång" (core/sources/sl.py).

Stockholm hade inget svar alls på frågan innan det här: SL:s avvikelsetext
bär ingen tidtabell. Endpointen /v1/sites/{id}/departures gör det, och de
tre sakerna som kan gå fel med den vaktas här: tidszonen, den inställda
avgången, och frestelsen att kalla ett tomt fönster för "sista turen".
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.test import TestCase

from core.sources.sl import (
    STOCKHOLM,
    enrich_next_departures,
    is_actionable,
    next_departure,
)

NOW = datetime(2026, 9, 8, 16, 40, tzinfo=dt_timezone.utc)  # 18:40 svensk tid


def departure(minutes_from_now: int, *, line="4", stop_area="11002", state="EXPECTED"):
    when = (NOW + timedelta(minutes=minutes_from_now)).astimezone(STOCKHOLM)
    return {
        "state": state,
        # Naken tidsstämpel, precis som SL svarar.
        "expected": when.replace(tzinfo=None).isoformat(timespec="seconds"),
        "line": {"designation": line},
        "stop_area": {"id": int(stop_area)},
    }


class NextDepartureTests(TestCase):
    def test_the_naive_timestamp_is_read_as_swedish_local_time(self):
        # SL:s departures-endpoint svarar utan tidszon medan deviations
        # svarar med. Läses de rakt av blir felet en till två timmar, och
        # alltid åt hållet som får avgången att se närmare ut än den är.
        when = next_departure([departure(20)], stop_area_id="11002", line="4", now=NOW)
        self.assertEqual(round((when - NOW).total_seconds() / 60), 20)

    def test_a_cancelled_departure_is_not_an_answer(self):
        # En resenär vars buss ställts in hjälps inte av att nästa också är
        # inställd.
        departures = [departure(5, state="CANCELLED"), departure(25)]
        when = next_departure(departures, stop_area_id="11002", line="4", now=NOW)
        self.assertEqual(round((when - NOW).total_seconds() / 60), 25)

    def test_the_line_must_match(self):
        # "Något går härifrån om 3 minuter" är sant och oanvändbart -- det
        # kan vara en buss åt fel håll.
        departures = [departure(3, line="57"), departure(30, line="4")]
        when = next_departure(departures, stop_area_id="11002", line="4", now=NOW)
        self.assertEqual(round((when - NOW).total_seconds() / 60), 30)

    def test_the_stop_must_match(self):
        departures = [departure(3, stop_area="99999"), departure(30)]
        when = next_departure(departures, stop_area_id="11002", line="4", now=NOW)
        self.assertEqual(round((when - NOW).total_seconds() / 60), 30)

    def test_no_departures_means_no_answer_not_last_departure(self):
        self.assertIsNone(next_departure([], stop_area_id="11002", line="4", now=NOW))


class EnrichTests(TestCase):
    def alert(self, **kw):
        base = {"id": "sl:1", "stops": ["11002"], "routes": ["4"]}
        base.update(kw)
        return base

    def index(self):
        return {"11002": {"lat": 59.3, "lon": 18.0, "site_id": "9192"}}

    def test_the_answer_lands_on_the_alert(self):
        alerts = [self.alert()]
        filled = enrich_next_departures(
            alerts, self.index(), now=NOW, fetch=lambda site_id: [departure(12)]
        )
        self.assertEqual(filled, 1)
        self.assertEqual(alerts[0]["next_departure_minutes"], 12)
        self.assertIsNotNone(alerts[0]["next_departure_at"])
        # Aldrig sista avgången härifrån: fönstret är två timmar, inte dygnet.
        self.assertNotIn("is_last_departure", alerts[0])

    def test_an_alert_without_a_line_is_left_alone(self):
        alerts = [self.alert(routes=[])]
        called = []
        enrich_next_departures(
            alerts, self.index(), now=NOW,
            fetch=lambda site_id: called.append(site_id) or [],
        )
        self.assertEqual(called, [])
        self.assertNotIn("next_departure_at", alerts[0])

    def test_a_stop_that_does_not_answer_does_not_stop_the_cycle(self):
        def boom(site_id):
            raise RuntimeError("sl-departures 503")

        alerts = [self.alert()]
        self.assertEqual(enrich_next_departures(alerts, self.index(), now=NOW, fetch=boom), 0)
        self.assertNotIn("next_departure_at", alerts[0])

    def test_each_stop_is_fetched_once_however_many_alerts_name_it(self):
        calls = []
        enrich_next_departures(
            [self.alert(id="sl:1"), self.alert(id="sl:2"), self.alert(id="sl:3")],
            self.index(), now=NOW,
            fetch=lambda site_id: calls.append(site_id) or [departure(9)],
        )
        self.assertEqual(calls, ["9192"])


class CategoryFilterTests(TestCase):
    def deviation(self, categories):
        return {
            "categories": categories,
            "publish": {
                "from": (NOW - timedelta(hours=1)).isoformat(),
                "upto": (NOW + timedelta(hours=5)).isoformat(),
            },
        }

    def test_a_broken_lift_is_not_a_taxi_opportunity(self):
        # Ett verkligt tillgänglighetsproblem, men det strandar ingen.
        # Föll tidigare bort på åldersfiltret -- alltså av tur: ett FÄRSKT
        # hissfel nådde flödet 2026-09-08.
        self.assertFalse(
            is_actionable(self.deviation([{"group": "FACILITY", "type": "LIFT"}]), NOW)
        )

    def test_an_ordinary_disruption_still_passes(self):
        self.assertTrue(is_actionable(self.deviation([]), NOW))
