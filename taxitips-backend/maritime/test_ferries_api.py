"""
/api/ferries: bara för behöriga, bara terminaler i förarens område, och aldrig hela landet
utan område eller position.
"""

from __future__ import annotations

import datetime as dt

from django.core.cache import cache
from django.utils import timezone

from core.test_api import DEVICE_TOKEN, ApiTestCase
from maritime.models import AisVessel
from maritime.ports import by_key


class FerriesApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        now = timezone.now()
        helsingborg, stromstad = by_key("helsingborg"), by_key("stromstad")
        AisVessel.objects.create(mmsi=219622000, name="HAMLET", ship_type=60, length_m=106,
                                 latitude=56.040, longitude=12.650, speed_knots=12.0, course=85.0,
                                 position_at=now - dt.timedelta(minutes=1))
        AisVessel.objects.create(mmsi=259000001, name="COLOR HYBRID", ship_type=60, length_m=160,
                                 latitude=stromstad.lat, longitude=stromstad.lon, speed_knots=0.0,
                                 position_at=now - dt.timedelta(minutes=1))
        # Ett fartyg som är i området men på väg någon annanstans visas inte i appen.
        AisVessel.objects.create(mmsi=219000999, name="PASSERAR", ship_type=60, length_m=150,
                                 latitude=56.000, longitude=12.600, speed_knots=15.0, course=180.0,
                                 position_at=now - dt.timedelta(minutes=1))
        self.helsingborg = helsingborg

    def get(self, params=None, **headers):
        return self.client.get("/api/ferries", params or {}, headers={"x-device-token": DEVICE_TOKEN, **headers}).json()

    def test_a_county_choice_keeps_its_terminals_only(self):
        body = self.get({"counties": "12"})
        self.assertEqual([f["name"] for f in body["ferries"]], ["HAMLET"])
        self.assertEqual(body["ferries"][0]["status"], "approaching")
        self.assertIn("helsingborg", {t["key"] for t in body["terminals"]})
        self.assertNotIn("stromstad", {t["key"] for t in body["terminals"]})
        self.assertIn("AISStream", body["attribution"])
        self.assertIn("arrivals", body)
        self.assertIsInstance(body["arrivals"], list)

    def test_a_position_uses_the_radius_instead(self):
        body = self.get(**{"x-tt-position": "58.94,11.17"})
        self.assertEqual([(f["name"], f["status"]) for f in body["ferries"]], [("COLOR HYBRID", "berthed")])

    def test_no_area_and_no_position_is_not_the_whole_country(self):
        body = self.get()
        self.assertEqual((body["ferries"], body.get("arrivals"), body.get("needsArea")), ([], [], True))

    def test_without_access_nothing_is_shown(self):
        body = self.client.get("/api/ferries", {"counties": "12"}).json()
        self.assertEqual((body["ferries"], body["entitled"]), ([], False))
