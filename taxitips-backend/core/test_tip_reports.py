"""Tester för tipprapporter och undertryckning."""

from __future__ import annotations

import uuid
from datetime import timedelta
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import Opportunity, OpportunityReport, SeverityTier
from core.repository import upsert_opportunities
from core.test_api import ApiTestCase, DEVICE_TOKEN, JWT_SECRET, make_jwt, opportunity
from fleet.models import StaffRole


class TipReportApiTests(ApiTestCase):
    def post_report(self, body, token=DEVICE_TOKEN):
        return self.client.post(
            "/api/tip-reports",
            data=body,
            content_type="application/json",
            headers={"x-device-token": token} if token else {},
        )

    def test_entitled_driver_can_report(self):
        o = opportunity()
        res = self.post_report({"opportunity_id": str(o.id), "reason": "Stämmer inte"})
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.json()["ok"])
        self.assertEqual(OpportunityReport.objects.count(), 1)

    def test_duplicate_report_is_idempotent(self):
        o = opportunity()
        self.post_report({"opportunity_id": str(o.id), "reason": "Fel"})
        res = self.post_report({"opportunity_id": str(o.id), "reason": "Fel igen"})
        self.assertTrue(res.json().get("duplicate"))
        self.assertEqual(OpportunityReport.objects.count(), 1)

    def test_report_requires_entitlement(self):
        o = opportunity()
        self.assertEqual(self.post_report({"opportunity_id": str(o.id)}, token="nope").status_code, 403)

    def test_suppressed_tip_leaves_feed(self):
        o = opportunity()
        o.suppressed_at = timezone.now()
        o.demand_score = 0
        o.end_time = timezone.now()
        o.save(update_fields=["suppressed_at", "demand_score", "end_time"])
        body = self.get_alerts()
        self.assertEqual(body["alerts"], [])


class SuppressionRepositoryTests(TestCase):
    def test_upsert_does_not_revive_suppressed_tip(self):
        now = timezone.now()
        ext = f"test:suppressed:{uuid.uuid4()}"
        upsert_opportunities([{
            "external_id": ext,
            "kind": "transit",
            "mode": "train",
            "severity_tier": SeverityTier.LINE_PAUSED,
            "level": "high",
            "title": "Första",
            "summary": "",
            "lat": 55.6,
            "lon": 13.0,
            "region": "skane",
            "start_time": now,
            "end_time": now + timedelta(hours=1),
            "demand_score": 80,
            "confidence": "medium",
            "reasons": "[]",
            "rule_id": "train.line_paused",
            "source_event_ids": "[]",
            "compensation_eligible": False,
            "compensation_amount_kr": None,
            "compensation_per_person": None,
            "next_departure_minutes": None,
            "next_departure_at": None,
            "places": "[]",
            "h3_index": "",
            "alternative_note": "",
        }])
        row = Opportunity.objects.get(external_id=ext)
        row.suppressed_at = now
        row.save(update_fields=["suppressed_at"])
        upsert_opportunities([{
            "external_id": ext,
            "kind": "transit",
            "mode": "train",
            "severity_tier": SeverityTier.LINE_PAUSED,
            "level": "high",
            "title": "Skulle skrivas över",
            "summary": "",
            "lat": 55.6,
            "lon": 13.0,
            "region": "skane",
            "start_time": now,
            "end_time": now + timedelta(hours=1),
            "demand_score": 99,
            "confidence": "medium",
            "reasons": "[]",
            "rule_id": "train.line_paused",
            "source_event_ids": "[]",
            "compensation_eligible": False,
            "compensation_amount_kr": None,
            "compensation_per_person": None,
            "next_departure_minutes": None,
            "next_departure_at": None,
            "places": "[]",
            "h3_index": "",
            "alternative_note": "",
        }])
        row.refresh_from_db()
        self.assertEqual(row.title, "Första")
        self.assertEqual(row.demand_score, 80)


@override_settings(SUPABASE_JWT_SECRET=JWT_SECRET)
class AdminTipReportTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.staff_id = str(uuid.uuid4())
        StaffRole.objects.create(user_id=self.staff_id, role=StaffRole.Role.PLATFORM_ADMIN)
        self.staff_auth = {"HTTP_AUTHORIZATION": f"Bearer {make_jwt(self.staff_id)}"}

    def test_admin_can_list_and_suppress(self):
        o = opportunity()
        OpportunityReport.objects.create(
            opportunity=o, device_token=DEVICE_TOKEN, reason="Fel plats"
        )
        list_res = self.client.get("/api/admin/tip-reports?status=open", **self.staff_auth)
        self.assertEqual(list_res.status_code, 200)
        reports = list_res.json()["reports"]
        self.assertEqual(len(reports), 1)
        report_id = reports[0]["id"]
        resolve = self.client.post(
            f"/api/admin/tip-reports/{report_id}/resolve",
            data='{"suppressTip": true, "note": "Borttaget"}',
            content_type="application/json",
            **self.staff_auth,
        )
        self.assertEqual(resolve.status_code, 200)
        o.refresh_from_db()
        self.assertIsNotNone(o.suppressed_at)
        self.assertEqual(o.demand_score, 0)
        self.assertEqual(
            OpportunityReport.objects.get(id=report_id).status,
            OpportunityReport.Status.RESOLVED,
        )
        self.assertEqual(self.get_alerts()["alerts"], [])
