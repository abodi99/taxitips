"""
Adminwebben: vem som kommer in, och att varje ändring lämnar spår.

Den viktigaste egenskapen testas först: en kund kommer aldrig in, hur hög
roll hen än har i sitt eget bolag. Adminwebben ser ALLA bolag -- en läcka här
är inte en läcka av ett bolags data utan av samtligas.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import timedelta

from django.test import Client, override_settings
from django.utils import timezone

from fleet.models import AuditEvent, StaffRole, Subscription, SubscriptionStatus
from fleet.tests.base import FleetTestCase

SECRET = "admin-test-secret-at-least-32-characters!"


def jwt(sub: str, aal: str = "aal1") -> str:
    def seg(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    head = seg({"alg": "HS256", "typ": "JWT"})
    body = seg({"sub": sub, "exp": int(time.time()) + 3600, "aal": aal})
    sig = hmac.new(SECRET.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class AdminAccessTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.data = self.full_setup()
        self.admin_id = str(uuid.uuid4())
        StaffRole.objects.create(user_id=self.admin_id, role=StaffRole.Role.PLATFORM_ADMIN)

    def get(self, path, user_id, aal="aal1"):
        return self.client.get(path, headers={"authorization": f"Bearer {jwt(user_id, aal)}"})

    def post(self, path, user_id, body, aal="aal1"):
        return self.client.post(
            path, data=json.dumps(body), content_type="application/json",
            headers={"authorization": f"Bearer {jwt(user_id, aal)}"},
        )

    def test_without_login_nothing_is_returned(self):
        response = self.client.get("/api/admin/companies")
        self.assertEqual(response.status_code, 401)

    def test_a_company_owner_is_not_a_platform_admin(self):
        """Den viktigaste regeln: en kunds högsta roll ger inget här."""
        owner = self.data["owner"]
        for path in ("/api/admin/overview", "/api/admin/companies",
                     f"/api/admin/companies/{self.data['company'].id}",
                     "/api/admin/notifications", "/api/admin/reviews"):
            with self.subTest(path=path):
                response = self.get(path, str(owner.user_id))
                self.assertEqual(response.status_code, 403, response.content)
                self.assertEqual(response.json()["reason"], "not_staff")

    def test_a_platform_admin_sees_every_company(self):
        other = self.make_company(name="Annat Taxi AB")
        body = self.get("/api/admin/companies", self.admin_id).json()
        names = {c["name"] for c in body["companies"]}
        self.assertIn("Taxi Demo AB", names)
        self.assertIn(other.name, names)

    def test_support_can_read_but_not_change(self):
        support_id = str(uuid.uuid4())
        StaffRole.objects.create(user_id=support_id, role=StaffRole.Role.SUPPORT)
        company_id = self.data["company"].id

        self.assertEqual(self.get("/api/admin/companies", support_id).status_code, 200)
        response = self.post(
            f"/api/admin/companies/{company_id}/subscription", support_id, {"extendDays": 30}
        )
        self.assertEqual(response.status_code, 403)

    def test_sales_can_open_customers_but_not_change_access_by_hand(self):
        """
        Sedan säljflödet ser säljaren kunderna -- men att ändra status eller
        förlänga en period utan betalning är fortfarande administratörens.
        """
        sales_id = str(uuid.uuid4())
        StaffRole.objects.create(user_id=sales_id, role=StaffRole.Role.SALES)
        company_id = self.data["company"].id
        self.assertEqual(self.get("/api/admin/companies", sales_id).status_code, 200)
        response = self.post(
            f"/api/admin/companies/{company_id}/subscription", sales_id, {"extendDays": 30}
        )
        self.assertEqual(response.status_code, 403)

    def test_an_inactive_staff_role_grants_nothing(self):
        StaffRole.objects.filter(user_id=self.admin_id).update(is_active=False)
        self.assertEqual(self.get("/api/admin/companies", self.admin_id).status_code, 403)

    def test_changes_require_two_factor_once_enforced(self):
        company_id = self.data["company"].id
        yesterday = (timezone.now() - timedelta(days=1)).isoformat()
        with self.settings(FLEET_TWO_FACTOR_REQUIRED_FROM=yesterday):
            response = self.post(
                f"/api/admin/companies/{company_id}/subscription", self.admin_id,
                {"extendDays": 30}, aal="aal1",
            )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["reason"], "two_factor_required")
            response = self.post(
                f"/api/admin/companies/{company_id}/subscription", self.admin_id,
                {"extendDays": 30}, aal="aal2",
            )
            self.assertEqual(response.status_code, 200)


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class AdminActionTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.data = self.full_setup()
        self.admin_id = str(uuid.uuid4())
        StaffRole.objects.create(user_id=self.admin_id, role=StaffRole.Role.PLATFORM_ADMIN)
        self.auth = {"authorization": f"Bearer {jwt(self.admin_id)}"}

    def post(self, path, body):
        return self.client.post(
            path, data=json.dumps(body), content_type="application/json", headers=self.auth
        )

    def test_extending_the_period_restores_access_and_is_logged(self):
        company = self.data["company"]
        Subscription.objects.filter(company_id=company.id).update(
            current_period_end=timezone.now() - timedelta(days=2),
            grace_until=timezone.now() - timedelta(days=1),
            status=SubscriptionStatus.PAST_DUE,
        )
        response = self.post(
            f"/api/admin/companies/{company.id}/subscription",
            {"extendDays": 14, "note": "Betalat via banköverföring"},
        )
        self.assertEqual(response.status_code, 200, response.content)

        from fleet import access

        self.assertTrue(access.company_window(company.id).ok)
        event = AuditEvent.objects.filter(action="admin_subscription_changed").get()
        self.assertEqual(event.actor_kind, "platform_admin")
        self.assertEqual(str(event.actor_user_id), self.admin_id)
        self.assertEqual(event.detail["before"]["status"], SubscriptionStatus.PAST_DUE)

    def test_an_unknown_status_is_refused(self):
        response = self.post(
            f"/api/admin/companies/{self.data['company'].id}/subscription",
            {"status": "gratis_for_evigt"},
        )
        self.assertEqual(response.status_code, 400)

    def test_the_company_detail_never_contains_a_secret(self):
        from billing.models import Device

        Device.objects.filter(id=self.data["device"].id).update(push_token="fcm-hemlig-token")
        body = self.client.get(
            f"/api/admin/companies/{self.data['company'].id}", headers=self.auth
        ).content.decode()
        self.assertNotIn(self.data["secret"], body)
        self.assertNotIn(self.data["device"].token, body)
        self.assertNotIn("fcm-hemlig-token", body)
        self.assertIn('"hasPush": true', body)

    def test_an_admin_can_issue_a_pairing_code_for_a_customer(self):
        response = self.post(
            f"/api/admin/companies/{self.data['company'].id}/pairing-code",
            {"license_id": str(self.data["license"].id)},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(response.json()["code"]), 8)
        self.assertTrue(AuditEvent.objects.filter(action="admin_pairing_code_issued").exists())

    def test_a_licence_from_another_company_is_not_found(self):
        other = self.full_setup(plate="XYZ999")
        response = self.post(
            f"/api/admin/companies/{self.data['company'].id}/pairing-code",
            {"license_id": str(other["license"].id)},
        )
        self.assertEqual(response.status_code, 404)

    def test_blocking_a_phone_ends_its_session(self):
        from fleet import sessions
        from fleet.models import VehicleSession

        sessions.start_session(
            device_id=self.data["device"].id, license_id=self.data["license"].id
        )
        response = self.post(f"/api/admin/approvals/{self.data['approval'].id}/block", {})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            VehicleSession.objects.filter(
                device_id=self.data["device"].id, ended_at__isnull=True
            ).exists()
        )

    def test_the_overview_reports_revenue_from_the_pricing_engine(self):
        body = self.client.get("/api/admin/overview", headers=self.auth).json()
        # En aktiv licens i grundnivån: 799 kr exklusive moms.
        self.assertEqual(body["mrrOre"], 79900)
        self.assertEqual(body["licensesActive"], 1)
