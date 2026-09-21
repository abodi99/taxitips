"""
Licensens län gäller överallt: tips, väghändelser, evenemang, färjor och
notisinställningar. Förarens val får smalna av, aldrig vidga.
"""

from __future__ import annotations

import json
from datetime import timedelta

from django.test import Client
from django.utils import timezone

from core.models import Opportunity, SeverityTier
from fleet import sessions
from fleet.tests.base import FleetTestCase
from fleet.tests.test_access import MALMO, tip


class AreaGateTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.data = self.full_setup(county="12")
        self.secret = self.data["secret"]
        sessions.start_session(device_id=self.data["device"].id, license_id=self.data["license"].id)

    def get(self, path, **params):
        return self.client.get(path, params, headers={"x-device-token": self.secret}).json()

    def test_all_road_events_when_the_driver_asks_for_road(self):
        now = timezone.now()
        for i in range(70):
            Opportunity.objects.create(
                external_id=f"road:{i}", kind="road", mode="road",
                severity_tier=SeverityTier.ROAD_WORK, title=f"Vägarbete {i}", summary="",
                lat=55.60 + i * 0.001, lon=13.00, region="skane", area_codes=["12"],
                start_time=now - timedelta(minutes=10), end_time=now + timedelta(hours=3),
                demand_score=5, reasons=[], rule_id="road.work",
            )
        capped = self.get("/api/alerts", **MALMO)
        full = self.get("/api/alerts", road="all", **MALMO)
        self.assertEqual(len(capped["context"]), 50)
        self.assertEqual(capped["contextTotal"], 70)
        self.assertEqual(len(full["context"]), 70)

    def test_events_outside_the_licence_are_refused(self):
        body = self.get("/api/events", counties="01")
        self.assertEqual(body["events"], [])
        self.assertEqual(body["reason"], "no_entitled_county")

    def test_ferries_outside_the_licence_are_refused(self):
        body = self.get("/api/ferries", counties="01")
        self.assertEqual(body["terminals"], [])
        self.assertEqual(body["reason"], "no_entitled_county")

    def test_notify_counties_are_limited_to_the_licence(self):
        response = self.client.post(
            "/api/notify-prefs", data=json.dumps({"counties": ["01", "12"]}),
            content_type="application/json", headers={"x-device-token": self.secret},
        ).json()
        self.assertEqual(response["prefs"]["counties"], ["12"])
        self.assertEqual(response["licensedCounties"], ["12"])
        self.assertFalse(response["licensedCountiesUnrestricted"])

    def test_notify_rules_are_saved(self):
        response = self.client.post(
            "/api/notify-prefs",
            data=json.dumps({"categories": {"road": False, "okänd": False}, "minLevel": "high", "pauseHours": 999}),
            content_type="application/json", headers={"x-device-token": self.secret},
        ).json()
        prefs = response["prefs"]
        self.assertEqual(prefs["categories"], {"road": False})
        self.assertEqual(prefs["minLevel"], "high")
        # Pausen kapas till 24 timmar och räknas på serverns klocka.
        from django.utils.dateparse import parse_datetime
        until = parse_datetime(prefs["pausedUntil"])
        self.assertLessEqual(until, timezone.now() + timedelta(hours=24, minutes=1))
        cleared = self.client.post(
            "/api/notify-prefs", data=json.dumps({"pauseHours": 0}),
            content_type="application/json", headers={"x-device-token": self.secret},
        ).json()
        self.assertNotIn("pausedUntil", cleared["prefs"])

    def test_licensed_tips_still_arrive(self):
        tip()
        body = self.get("/api/alerts", **MALMO)
        self.assertTrue(body["entitled"], body)
        self.assertEqual(len(body["alerts"]), 1)


class FavoriteOwnerKeyTests(FleetTestCase):
    """Favoriterna ägs av telefonens id -- aldrig av dess hemlighet."""

    def test_a_favorite_is_stored_under_the_device_id_not_the_secret(self):
        from core.models import OpportunityFavorite

        data = self.full_setup(county="12")
        sessions.start_session(device_id=data["device"].id, license_id=data["license"].id)
        o = tip()
        client = Client()
        response = client.post(
            "/api/favorites", data=json.dumps({"opportunity_id": str(o.id), "favorite": True}),
            content_type="application/json", headers={"x-device-token": data["secret"]},
        )
        self.assertIn(response.status_code, (200, 201), response.content)
        keys = set(OpportunityFavorite.objects.values_list("owner_key", flat=True))
        self.assertEqual(keys, {f"device:{data['device'].id}"})
        self.assertNotIn(data["secret"], json.dumps(list(keys)))

    def test_an_old_favorite_keyed_by_the_secret_moves_on_first_request(self):
        from core.models import OpportunityFavorite

        data = self.full_setup(county="12")
        sessions.start_session(device_id=data["device"].id, license_id=data["license"].id)
        o = tip()
        from core import notify

        OpportunityFavorite.objects.create(
            owner_key=data["secret"], opportunity=o, opportunity_external_id=o.external_id,
            snapshot=notify.snapshot_of(o),
        )
        body = Client().get("/api/alerts", MALMO, headers={"x-device-token": data["secret"]}).json()
        self.assertEqual([f["id"] for f in body["favorites"]], [str(o.id)])
        self.assertFalse(OpportunityFavorite.objects.filter(owner_key=data["secret"]).exists())
