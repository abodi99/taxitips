"""
Hela kundresan i ett test, i den ordning en ny kund går igenom den:

registrera företaget -> provbil -> bjud in föraren med e-post -> föraren
loggar in med bara e-post och koden i mejlet -> provet startar -> föraren tar
bilen och får tips i bilens län -> ägaren bjuder in en kollega -> plattformens
admin ser allt på kundsidan.

Varje steg har egna, noggrannare tester. Det här testet finns för att fånga
när stegen var för sig fungerar men inte längre hänger ihop -- det som en kund
märker först och en enhetstest sist.
"""

from __future__ import annotations

import json
import uuid
from unittest import mock

from django.test import Client, RequestFactory, override_settings

from billing.models import CompanyMember
from fleet import access, auth_admin
from fleet.models import DriverInvite, OutboxMessage, StaffRole, Trial
from fleet.tests.base import FleetTestCase
from fleet.tests.test_support import SECRET, jwt


def _link(email, redirect_to):
    return auth_admin.AuthLink(url="https://api.taxitips.se/auth/v1/verify?token=t", user_id=str(uuid.uuid4()), kind="invite")


@override_settings(SUPABASE_JWT_SECRET=SECRET, SUPABASE_SERVICE_ROLE_KEY="test-service-role")
class LaunchFlowTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        patcher = mock.patch("fleet.auth_admin.invite_link", side_effect=_link)
        patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, method, path, body=None, *, user=None, email="", device=None):
        headers = {}
        if user:
            headers["authorization"] = f"Bearer {jwt(str(user), email)}"
        if device:
            headers["x-device-token"] = device
        if method == "get":
            return self.client.get(path, headers=headers)
        return self.client.post(path, data=json.dumps(body or {}), content_type="application/json", headers=headers)

    def ok(self, response, status=200):
        self.assertEqual(response.status_code, status, response.content)
        return response.json()

    def test_a_new_customer_from_registration_to_a_driver_with_tips(self):
        owner = str(uuid.uuid4())

        # 1. Ägaren registrerar företaget med en bil i Skåne. Provet väntar på första telefonen.
        reg = self.ok(self.call("post", "/api/fleet/register", {
            "orgNumber": "5560360793", "companyName": "Nya Taxi AB", "contactName": "Ali",
            "contactPhone": "070-812 34 91", "vehicles": [{"plate": "ABC123", "baseCounty": "12"}],
        }, user=owner, email="agare@nyataxi.test"), status=201)
        company_id = reg["companyId"]
        trial = Trial.objects.get(company_id=company_id)
        self.assertIsNone(trial.started_at)

        overview = self.ok(self.call("get", "/api/fleet/company", user=owner, email="agare@nyataxi.test"))
        car = next(row for row in overview["licenses"] if row["vehicle"] == "ABC123")
        self.assertTrue(overview["driverInvites"]["enabled"])
        # Appens välkomst till provet: längden och vad som ingår, före första telefonen.
        self.assertGreater(overview["trial"]["plannedDays"], 0)
        self.assertEqual(overview["features"]["plan"], "trial")
        self.assertNotIn("betal", overview["features"]["lockedMessage"].lower())
        self.assertEqual(car["countyChanges"]["remaining"], 2)

        # 2. Ägaren bjuder in föraren med e-post till bilen. Mejlet har ingen länk.
        self.ok(self.call("post", "/api/fleet/driver-invites", {
            "email": "anna@forare.test", "licenseId": car["licenseId"], "label": "Anna",
        }, user=owner, email="agare@nyataxi.test"))
        invite_mail = OutboxMessage.objects.get(category="driver_invite")
        self.assertIn("Jag är förare", invite_mail.body)

        # 3. Föraren skriver bara sin e-post och koden från mejlet.
        self.ok(self.call("post", "/api/fleet/driver-login/start", {"email": "anna@forare.test"}))
        code = OutboxMessage.objects.get(category="driver_login_code").payload["code"]
        paired = self.ok(self.call("post", "/api/fleet/driver-login/verify", {
            "email": "anna@forare.test", "code": code, "installation_id": "install-anna-0001",
            "platform": "android",
        }))
        secret = paired["deviceToken"]
        self.assertEqual(DriverInvite.objects.get().status, DriverInvite.Status.CONSUMED)

        # 4. Första telefonen startade provet.
        trial.refresh_from_db()
        self.assertIsNotNone(trial.started_at)

        # 5. Föraren kör bilen och får tips i bilens län -- och bara där.
        if not paired.get("sessionStarted"):
            self.ok(self.call("post", "/api/fleet/session", {"license_id": car["licenseId"]}, device=secret))
        request = RequestFactory().get("/api/alerts", headers={"x-device-token": secret})
        result = access.resolve(request)
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.vehicle_plate, "ABC123")
        self.assertEqual(result.counties, ("12",))

        # 6. Ägaren bjuder in en kollega som sköter fakturorna.
        self.ok(self.call("post", "/api/fleet/members/invite", {
            "email": "ekonomi@nyataxi.test", "role": "finance",
        }, user=owner, email="agare@nyataxi.test"))
        self.assertTrue(OutboxMessage.objects.filter(category="member_invite", to_address="ekonomi@nyataxi.test").exists())
        colleague = str(uuid.uuid4())
        self.ok(self.call("post", "/api/fleet/claim-invite", user=colleague, email="ekonomi@nyataxi.test"))
        self.assertEqual(CompanyMember.objects.get(user_id=colleague).role, "finance")
        self.ok(self.call("get", "/api/fleet/company", user=colleague, email="ekonomi@nyataxi.test"))

        # 7. Plattformens admin ser kunden: bilen, föraren som kör och båda inloggningarna.
        staff = str(uuid.uuid4())
        StaffRole.objects.create(user_id=staff, role=StaffRole.Role.PLATFORM_ADMIN)
        detail = self.ok(self.call("get", f"/api/admin/companies/{company_id}", user=staff))
        admin_car = next(row for row in detail["licenses"] if row["vehicle"] == "ABC123")
        self.assertIsNotNone(admin_car["activePhone"])
        self.assertEqual(len([m for m in detail["members"] if m["status"] == "active"]), 2)
        self.assertEqual(detail["trial"]["status"], "active")
