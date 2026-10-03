"""
Förarens inloggning med bara e-post: inbjudan till en bil, en kod i mejlet,
och telefonen kopplas till bilen chefen valde.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from unittest import mock

from django.test import Client, override_settings
from django.utils import timezone

from fleet import auth_admin
from fleet.models import DeviceApproval, DriverInvite, DriverLoginCode, OutboxMessage
from fleet.tests.base import FleetTestCase
from fleet.tests.test_support import SECRET, jwt

EMAIL = "anna@forare.test"


@override_settings(SUPABASE_JWT_SECRET=SECRET, SUPABASE_SERVICE_ROLE_KEY="test-service-role")
class DriverLoginTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.company = self.make_company()
        self.owner = self.make_owner(self.company)
        self.make_subscription(self.company)
        self.vehicle, self.license = self.make_license(self.company, plate="EPO123", county="01")
        self.driver_user = str(uuid.uuid4())
        patcher = mock.patch(
            "fleet.auth_admin.invite_link",
            return_value=auth_admin.AuthLink(url="https://x", user_id=self.driver_user, kind="invite"),
        )
        self.link = patcher.start()
        self.addCleanup(patcher.stop)

    def post(self, path, body, user=None):
        headers = {"authorization": f"Bearer {jwt(str(user))}"} if user else {}
        return self.client.post(path, data=json.dumps(body), content_type="application/json", headers=headers)

    def invite(self, email=EMAIL):
        response = self.post("/api/fleet/driver-invites", {
            "email": email, "licenseId": str(self.license.id), "label": "Anna",
        }, user=self.owner.user_id)
        self.assertEqual(response.status_code, 200, response.content)

    def start(self, email=EMAIL):
        return self.post("/api/fleet/driver-login/start", {"email": email})

    def last_code(self):
        return OutboxMessage.objects.filter(category="driver_login_code").order_by("-created_at").first().payload["code"]

    def verify(self, code, email=EMAIL, installation="install-anna-0001"):
        return self.post("/api/fleet/driver-login/verify", {
            "email": email, "code": code, "installation_id": installation, "platform": "android",
        })

    def test_the_driver_types_the_email_gets_a_code_and_the_phone_joins_the_car(self):
        self.invite()
        response = self.start("Anna@Forare.TEST")
        self.assertEqual(response.status_code, 200, response.content)
        mail = OutboxMessage.objects.get(category="driver_login_code")
        self.assertEqual(mail.to_address, EMAIL)
        code = mail.payload["code"]
        self.assertEqual(len(code), 6)
        self.assertIn(code, mail.subject)
        # Bara hashen sparas.
        self.assertNotEqual(DriverLoginCode.objects.get().code_hash, code)

        verified = self.verify(f"{code[:3]} {code[3:]}")
        self.assertEqual(verified.status_code, 200, verified.content)
        body = verified.json()
        self.assertTrue(body["deviceToken"])
        self.assertEqual(body["plate"], "EPO123")
        approval = DeviceApproval.objects.get()
        self.assertEqual(approval.license_id, self.license.id)
        invite = DriverInvite.objects.get()
        self.assertEqual(invite.status, DriverInvite.Status.CONSUMED)
        self.assertEqual(str(invite.consumed_by_user), self.driver_user)

        # Koden fungerar en gång.
        self.assertEqual(self.verify(code, installation="install-anna-0002").status_code, 410)

    def test_an_address_without_invite_gets_the_same_answer_and_no_mail(self):
        response = self.start("okand@exempel.se")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(OutboxMessage.objects.filter(category="driver_login_code").exists())
        self.assertEqual(self.verify("123456", email="okand@exempel.se").status_code, 410)

    def test_a_wrong_code_counts_and_five_wrong_codes_lock_it(self):
        self.invite()
        self.start()
        code = self.last_code()
        wrong = "000000" if code != "000000" else "111111"
        for _ in range(5):
            self.assertEqual(self.verify(wrong).status_code, 400)
        self.assertEqual(DriverLoginCode.objects.get().attempts, 5)
        # Inte ens rätt kod gäller efter fem fel.
        self.assertEqual(self.verify(code).status_code, 429)
        self.assertFalse(DeviceApproval.objects.exists())

    def test_an_old_code_has_expired(self):
        self.invite()
        self.start()
        DriverLoginCode.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.assertEqual(self.verify(self.last_code()).status_code, 410)

    def test_a_new_code_replaces_the_previous(self):
        self.invite()
        self.start()
        first = self.last_code()
        self.start()
        second = self.last_code()
        if first != second:
            self.assertEqual(self.verify(first).status_code, 400)
        self.assertEqual(self.verify(second).status_code, 200)

    def test_the_driver_logs_in_again_on_a_new_phone_with_only_the_email(self):
        self.invite()
        self.start()
        self.assertEqual(self.verify(self.last_code()).status_code, 200)

        self.start()
        again = self.verify(self.last_code(), installation="install-anna-ny-telefon")
        self.assertEqual(again.status_code, 200, again.content)
        active = DeviceApproval.objects.filter(status=DeviceApproval.Status.ACTIVE)
        self.assertEqual(active.count(), 1)

    def test_a_blocked_driver_cannot_log_in_again(self):
        self.invite()
        self.start()
        self.verify(self.last_code())
        DeviceApproval.objects.update(status=DeviceApproval.Status.BLOCKED)
        self.start()
        response = self.verify(self.last_code(), installation="install-anna-ny-telefon")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["reason"], "driver_blocked")

    @override_settings(SUPABASE_SERVICE_ROLE_KEY="")
    def test_it_works_without_supabase_auth(self):
        self.invite()
        self.start()
        response = self.verify(self.last_code())
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNotNone(DriverInvite.objects.get().auth_user_id)
