"""
Kombinationslagret: dubbletter blir en rad, knutpunkter och ankomster förstärks -- och
inget kombineras som inte faktiskt delar plats och tid.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.utils import timezone

from core import combine
from core.test_api import DEVICE_TOKEN, MALMO, ApiTestCase, opportunity

NOW = dt.datetime(2026, 9, 14, 8, 0, tzinfo=dt.timezone.utc)
LUND_C = (55.7056, 13.1868)


def tip(external_id, *, lat=LUND_C[0], lon=LUND_C[1], **overrides):
    fields = {
        "external_id": external_id, "kind": "transit", "mode": "train", "severity_tier": "vehicle_cancelled",
        "demand_score": 60, "confidence": "low", "has_alternative": False, "lat": lat, "lon": lon,
        "start_time": NOW - dt.timedelta(minutes=10), "end_time": NOW + dt.timedelta(hours=1), "title": "Tåg inställt",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


class FindTests(SimpleTestCase):
    def test_the_same_cancellation_from_two_sources_is_one_row(self):
        found = combine.find([
            tip("tvr:1", demand_score=60),
            tip("skane:1", demand_score=70, lat=LUND_C[0] + 0.0005),  # ~55 m
        ], NOW)
        self.assertEqual([(f.rule_id, f.effect, f.primary, f.members) for f in found],
                         [("combo.duplicate", "merge", "skane:1", ("tvr:1",))])
        self.assertIn("tvr", found[0].reason)

    def test_the_same_source_is_never_a_duplicate(self):
        self.assertEqual(combine.find([tip("tvr:1"), tip("tvr:2")], NOW), [])

    def test_far_apart_or_at_different_times_is_nothing(self):
        far = tip("skane:1", lat=LUND_C[0] + 0.02)  # ~2 km
        later = tip("skane:2", start_time=NOW + dt.timedelta(hours=3), end_time=NOW + dt.timedelta(hours=4))
        self.assertEqual(combine.find([tip("tvr:1"), far], NOW), [])
        self.assertEqual(combine.find([tip("tvr:1"), later], NOW), [])

    def test_different_modes_at_the_same_stop_reinforce(self):
        found = combine.find([tip("tvr:1", demand_score=70), tip("skane:9", mode="bus", demand_score=55)], NOW)
        self.assertEqual([(f.rule_id, f.primary, f.boost) for f in found], [("combo.hub", "tvr:1", combine.HUB_BOOST)])

    def test_a_stated_alternative_is_never_reinforced(self):
        found = combine.find([tip("tvr:1"), tip("skane:9", mode="bus", has_alternative=True)], NOW)
        self.assertEqual(found, [])

    def test_an_arrival_wave_with_stopped_transit_is_reinforced(self):
        arrival = tip("swedavia:ARN:1", kind="flight", mode="air", severity_tier="arrival_wave", lat=59.6519, lon=17.9186)
        train = tip("tvr:ARN", lat=59.6490, lon=17.9290, severity_tier="line_paused")  # Arlanda C, ~700 m
        found = combine.find([arrival, train], NOW)
        self.assertEqual([(f.rule_id, f.primary, f.boost) for f in found],
                         [("combo.arrival", "swedavia:ARN:1", combine.ARRIVAL_BOOST)])

    def test_road_is_context_and_never_combined(self):
        self.assertEqual(combine.find([tip("tvr:1"), tip("trafikverket:1", kind="road", mode="road")], NOW), [])


class FeedTests(ApiTestCase):
    def test_the_duplicate_is_hidden_and_the_primary_says_why(self):
        now = timezone.now()
        opportunity(external_id="skane:1", title="Tåg 1234 inställt (Skånetrafiken)", demand_score=85, mode="train",
                    lat=55.6092, lon=13.0007, start_time=now - dt.timedelta(minutes=5))
        opportunity(external_id="tvr:1", title="Tåg 1234 inställt (Trafikverket)", demand_score=70, mode="train",
                    lat=55.6095, lon=13.0010, start_time=now - dt.timedelta(minutes=5))
        combine.run()
        body = self.client.get("/api/alerts", MALMO, headers={"x-device-token": DEVICE_TOKEN}).json()
        titles = [a["title"] for a in body["alerts"]]
        self.assertEqual(titles, ["Tåg 1234 inställt (Skånetrafiken)"])
        self.assertIn("combo.duplicate", body["alerts"][0]["combined"])
        self.assertTrue(any("rapporteras även av tvr" in r for r in body["alerts"][0]["reasons"]))
