"""
Adminwebbens appversionskort: vem får läsa, vem får ändra, och att en ändring
som skulle låsa ute förare utan väg ut aldrig sparas.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

from django.test import Client, override_settings
from django.utils import timezone

from core.models import AppVersionPolicy
from fleet.models import AuditEvent, StaffRole
from fleet.tests.base import FleetTestCase
from fleet.tests.test_admin import SECRET, jwt

PATH = "/api/admin/app-version"


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class AdminAppVersionTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.data = self.full_setup()
        self.admin_id = str(uuid.uuid4())
        self.support_id = str(uuid.uuid4())
        StaffRole.objects.create(user_id=self.admin_id, role=StaffRole.Role.PLATFORM_ADMIN)
        StaffRole.objects.create(user_id=self.support_id, role=StaffRole.Role.SUPPORT)

    def get(self, user_id):
        return self.client.get(PATH, headers={"authorization": f"Bearer {jwt(user_id)}"})

    def post(self, user_id, body, aal="aal1"):
        return self.client.post(
            PATH, data=json.dumps(body), content_type="application/json",
            headers={"authorization": f"Bearer {jwt(user_id, aal)}"},
        )

    def test_only_staff_get_in(self):
        self.assertEqual(self.client.get(PATH).status_code, 401)
        response = self.get(str(self.data["owner"].user_id))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["reason"], "not_staff")
        # En bolagsägare kan inte heller ändra -- det skulle stänga ute alla bolags förare.
        response = self.post(str(self.data["owner"].user_id), {"android": {"min": "9.0.0"}})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(AppVersionPolicy.objects.filter(android_min_version="9.0.0").count(), 0)

    def test_support_reads_but_cannot_change(self):
        response = self.get(self.support_id)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("android", response.json()["platforms"])
        response = self.post(self.support_id, {"android": {"min": "1.0.2"}})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["reason"], "missing_permission")

    def test_platform_admin_changes_it_and_the_app_sees_it_at_once(self):
        response = self.post(self.admin_id, {
            "android": {"min": "1.0.2", "recommended": "1.0.3"}, "message": "Ny karta.",
        })
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["platforms"]["android"]["min"], {"value": "1.0.2", "source": "db"})
        config = self.client.get("/api/config").json()["appVersion"]
        self.assertEqual(config["android"]["min"], "1.0.2")
        self.assertEqual(config["android"]["recommended"], "1.0.3")
        self.assertEqual(config["message"], "Ny karta.")

        event = AuditEvent.objects.get(action="admin_app_version_changed")
        self.assertEqual(event.actor_kind, "platform_admin")
        self.assertEqual(str(event.actor_user_id), self.admin_id)
        self.assertEqual(event.detail["before"]["android_min_version"], "")
        self.assertEqual(event.detail["after"]["android_min_version"], "1.0.2")

    def test_a_missing_key_is_left_alone_and_an_empty_one_clears(self):
        self.post(self.admin_id, {"android": {"min": "1.0.2", "recommended": "1.0.3"}})
        self.post(self.admin_id, {"android": {"recommended": ""}})
        row = AppVersionPolicy.current()
        self.assertEqual(row.android_min_version, "1.0.2")
        self.assertEqual(row.android_recommended_version, "")

    def test_mistakes_that_would_lock_drivers_out_are_refused(self):
        cases = [
            ({"android": {"min": "1.0.x"}}, "invalid_version"),
            ({"android": {"min": "1.1.0", "recommended": "1.0.9"}}, "recommended_below_min"),
            # Utan App Store-länk har en blockerad iPhone-förare ingen väg ut.
            ({"ios": {"min": "1.0.0"}}, "ios_store_url_required"),
            ({"ios": {"storeUrl": "javascript:alert(1)"}}, "invalid_store_url"),
            ({"message": "x" * 301}, "message_too_long"),
        ]
        for body, reason in cases:
            response = self.post(self.admin_id, body)
            self.assertEqual(response.status_code, 400, body)
            self.assertEqual(response.json()["reason"], reason, body)
        row = AppVersionPolicy.current()
        self.assertEqual((row.android_min_version, row.ios_min_version), ("", ""))
        self.assertFalse(AuditEvent.objects.filter(action="admin_app_version_changed").exists())

    def test_ios_min_is_accepted_with_a_store_link(self):
        response = self.post(self.admin_id, {
            "ios": {"min": "1.0.0", "storeUrl": "https://apps.apple.com/app/id123"},
        })
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            self.client.get("/api/config").json()["appVersion"]["ios"]["min"], "1.0.0"
        )

    def test_changes_require_two_factor_once_enforced(self):
        yesterday = (timezone.now() - timedelta(days=1)).isoformat()
        with self.settings(FLEET_TWO_FACTOR_REQUIRED_FROM=yesterday):
            response = self.post(self.admin_id, {"android": {"min": "1.0.2"}}, aal="aal1")
            self.assertEqual(response.json()["reason"], "two_factor_required")
            response = self.post(self.admin_id, {"android": {"min": "1.0.2"}}, aal="aal2")
            self.assertEqual(response.status_code, 200, response.content)
