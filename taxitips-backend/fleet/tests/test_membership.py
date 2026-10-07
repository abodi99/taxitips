"""
Kontobaserat medlemskap (2026-10): tilldela ett konto i stället för en bil,
och en app-session per konto.

Portalen begränsas inte -- den tar aldrig en MembershipSession -- och det prövas
här, eftersom felet annars vore att en ägare plötsligt bara kunde vara inloggad
på ett ställe.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid

from django.test import Client, RequestFactory, override_settings
from django.utils import timezone

from billing.models import Device
from fleet import access, licensing, membership
from fleet.models import License, MembershipSession
from fleet.tests.base import FleetTestCase

SECRET = "support-test-secret-at-least-32-characters!"


def _jwt(sub, email="") -> str:
    def seg(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    head = seg({"alg": "HS256", "typ": "JWT"})
    claims = {"sub": str(sub), "exp": int(time.time()) + 3600, "aal": "aal1"}
    if email:
        claims["email"] = email
    body = seg(claims)
    sig = hmac.new(SECRET.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class MembershipTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.data = self.full_setup(county="12")
        self.company = self.data["company"]
        self.owner = self.data["owner"]
        self.license = self.data["license"]

    def owner_headers(self) -> dict:
        return {"authorization": f"Bearer {_jwt(self.owner.user_id, 'agare@taxi.test')}"}

    def post(self, path, body=None, headers=None):
        return self.client.post(
            path, data=json.dumps(body or {}), content_type="application/json",
            headers=headers or self.owner_headers(),
        )

    def resolve(self, headers):
        return access.resolve(RequestFactory().get("/api/alerts", headers=headers))

    # --- tilldelning -----------------------------------------------------

    def test_owner_assigns_the_membership_to_self(self):
        r = self.post(f"/api/fleet/memberships/{self.license.id}/assign", {"mode": "self"})
        self.assertEqual(r.status_code, 200, r.content)
        self.license.refresh_from_db()
        self.assertEqual(str(self.license.assignee_user_id), str(self.owner.user_id))

    def test_assign_to_email_is_claimed_when_that_account_logs_in(self):
        r = self.post(
            f"/api/fleet/memberships/{self.license.id}/assign",
            {"mode": "email", "email": "forare@taxi.test"},
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.license.refresh_from_db()
        self.assertEqual(self.license.assignee_email, "forare@taxi.test")
        self.assertIsNone(self.license.assignee_user_id)

        driver_id = uuid.uuid4()
        headers = {"authorization": f"Bearer {_jwt(driver_id, 'forare@taxi.test')}"}
        listed = self.client.get("/api/fleet/memberships", headers=headers)
        self.assertEqual(listed.status_code, 200, listed.content)
        self.license.refresh_from_db()
        self.assertEqual(str(self.license.assignee_user_id), str(driver_id))
        self.assertEqual(
            [m["licenseId"] for m in listed.json()["memberships"]], [str(self.license.id)]
        )

    def test_unassign_frees_the_seat(self):
        self.post(f"/api/fleet/memberships/{self.license.id}/assign", {"mode": "self"})
        r = self.post(f"/api/fleet/memberships/{self.license.id}/unassign")
        self.assertEqual(r.status_code, 200, r.content)
        self.license.refresh_from_db()
        self.assertIsNone(self.license.assignee_user_id)

    # --- app-sessionen: ett konto, en enhet ------------------------------

    def test_a_second_device_must_take_over(self):
        self.post(f"/api/fleet/memberships/{self.license.id}/assign", {"mode": "self"})
        d1, d2 = uuid.uuid4(), uuid.uuid4()
        first = self.post(
            "/api/fleet/membership-session",
            {"licenseId": str(self.license.id), "deviceId": str(d1)},
        )
        self.assertEqual(first.status_code, 200, first.content)

        second = self.post(
            "/api/fleet/membership-session",
            {"licenseId": str(self.license.id), "deviceId": str(d2)},
        )
        self.assertEqual(second.status_code, 409, second.content)
        self.assertEqual(second.json()["reason"], "takeover_required")

        forced = self.post(
            "/api/fleet/membership-session",
            {"licenseId": str(self.license.id), "deviceId": str(d2), "force": True},
        )
        self.assertEqual(forced.status_code, 200, forced.content)
        open_rows = MembershipSession.objects.filter(license=self.license, ended_at__isnull=True)
        self.assertEqual(open_rows.count(), 1)
        self.assertEqual(str(open_rows.first().device_id), str(d2))

    def test_one_open_session_per_account_across_memberships(self):
        vehicle = licensing.create_vehicle(company_id=self.company.id, plate="TWO123")
        second = licensing.create_license(company_id=self.company.id, vehicle=vehicle, base_county="14")
        for lic in (self.license, second):
            membership.assign_to_self(license=lic, user_id=self.owner.user_id)

        self.post("/api/fleet/membership-session", {"licenseId": str(self.license.id)})
        self.post("/api/fleet/membership-session", {"licenseId": str(second.id)})
        open_rows = MembershipSession.objects.filter(user_id=self.owner.user_id, ended_at__isnull=True)
        self.assertEqual(open_rows.count(), 1)
        self.assertEqual(str(open_rows.first().license_id), str(second.id))

    def test_session_grants_driver_access(self):
        self.post(f"/api/fleet/memberships/{self.license.id}/assign", {"mode": "self"})
        self.post("/api/fleet/membership-session", {"licenseId": str(self.license.id)})
        result = self.resolve(self.owner_headers())
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.kind, "driver")
        self.assertEqual(result.counties, ("12",))

    def test_portal_needs_no_session(self):
        # Utan app-session är den inloggade vägen oförändrad (ägaren är medlem).
        result = self.resolve(self.owner_headers())
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.kind, "member")

    def test_an_owner_app_without_a_jwt_gets_the_accounts_access(self):
        # Ägarappen skickar enhetstoken men inte alltid Authorization
        # (`/api/fleet/me`). Telefonraden bär kontot, så en inloggad ägare ska
        # få kontots åtkomst -- inte "Telefonen är inte godkänd för någon bil".
        device = Device.objects.create(
            id=uuid.uuid4(), company_id=self.company.id, token="install-owner-app",
            label="Ägarapp", kind="owner_app", notify_prefs={},
            created_at=timezone.now(), user_id=self.owner.user_id,
        )
        result = self.resolve({"X-Device-Token": device.token})
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(result.kind, "member")
        self.assertEqual(result.counties, ("12",))

    def test_a_phone_without_an_account_is_unchanged(self):
        # Regression: en telefon utan konto på raden får telefonens eget skäl.
        device = Device.objects.create(
            id=uuid.uuid4(), company_id=self.company.id, token="install-no-account",
            label="Okänd", kind="driver", notify_prefs={}, created_at=timezone.now(),
        )
        result = self.resolve({"X-Device-Token": device.token})
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, "device_not_approved")

    # --- län -------------------------------------------------------------

    def test_trial_assignee_chooses_the_county(self):
        vehicle = licensing.create_vehicle(company_id=self.company.id, plate="TRI123")
        trial_license = licensing.create_license(
            company_id=self.company.id, vehicle=vehicle, base_county="01",
            status=License.Status.TRIAL,
        )
        driver_id = uuid.uuid4()
        membership.assign_to_email(license=trial_license, email="ny@taxi.test")
        membership.claim_for_email(email="ny@taxi.test", user_id=driver_id)

        headers = {"authorization": f"Bearer {_jwt(driver_id, 'ny@taxi.test')}"}
        r = self.post(f"/api/fleet/memberships/{trial_license.id}/county", {"base": "12"}, headers=headers)
        self.assertEqual(r.status_code, 200, r.content)
        trial_license.refresh_from_db()
        self.assertEqual(trial_license.base_county, "12")

    # --- appens provsteg: ta platsen och välj län (registrera -> kod -> app) --

    def start_trial(self):
        from fleet import trials
        from fleet.models import Trial

        return trials.create_trial(
            company_id=self.company.id, country="SE", org_number="5566778899",
            source=Trial.Source.SELF_SIGNUP, requires_payment_method=False,
        )

    def test_trial_step_creates_a_membership_on_the_owners_own_account(self):
        self.start_trial()
        r = self.post("/api/fleet/memberships/trial", {"baseCounty": "14"})
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()["membership"]
        self.assertEqual(body["baseCounty"], "14")
        self.assertEqual(body["counties"], ["14"])
        license = License.objects.get(id=body["licenseId"])
        self.assertEqual(license.status, License.Status.TRIAL)
        self.assertTrue(license.is_assigned_to(self.owner.user_id))

    def test_trial_step_is_idempotent(self):
        self.start_trial()
        first = self.post("/api/fleet/memberships/trial", {"baseCounty": "12"}).json()
        again = self.post("/api/fleet/memberships/trial", {"baseCounty": "14"}).json()
        self.assertEqual(again["membership"]["licenseId"], first["membership"]["licenseId"])
        self.assertEqual(again["membership"]["baseCounty"], "14")
        self.assertEqual(License.objects.filter(trial__isnull=False).count(), 1)

    def test_trial_step_adopts_an_unassigned_trial_license(self):
        from fleet.models import Trial

        trial = self.start_trial()
        vehicle = licensing.create_vehicle(company_id=self.company.id, plate="WEB123")
        existing = licensing.create_license(
            company_id=self.company.id, vehicle=vehicle, base_county="01",
            status=License.Status.TRIAL, trial=trial,
        )
        self.assertIsNone(existing.assignee_user_id)

        r = self.post("/api/fleet/memberships/trial", {"baseCounty": "12"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["membership"]["licenseId"], str(existing.id))
        existing.refresh_from_db()
        self.assertTrue(existing.is_assigned_to(self.owner.user_id))
        self.assertEqual(existing.base_county, "12")
        self.assertEqual(License.objects.filter(trial=Trial.objects.get(company_id=self.company.id)).count(), 1)
