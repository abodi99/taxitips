"""
Förarinbjudan med e-post: administratören skriver förarens e-post, föraren
väljer lösenord via länken och loggar in i appen -- och telefonen blir godkänd
genom samma väg som engångskoden.

Inga anrop till Supabase Auth och inga riktiga mejl: länken mockas
(`fleet.auth_admin.invite_link`) och utkorgen saknar avsändare i testerna.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from unittest import mock

import requests
from django.test import Client, override_settings
from django.utils import timezone

from fleet import auth_admin
from fleet.models import (
    AuditEvent,
    DeviceApproval,
    DriverInvite,
    OutboxMessage,
    RiskSignal,
)
from fleet.tests.base import FleetTestCase
from fleet.tests.test_support import SECRET, jwt

DRIVER_EMAIL = "anna@forare.test"


def fake_link(user_id):
    def _link(email, redirect_to):
        return auth_admin.AuthLink(
            url=f"https://auth.test/verify?token=t-{uuid.uuid4().hex[:6]}&redirect_to={redirect_to}",
            user_id=user_id, kind="invite",
        )
    return _link


@override_settings(
    SUPABASE_JWT_SECRET=SECRET,
    SUPABASE_SERVICE_ROLE_KEY="test-service-role",
    FLEET_DRIVER_INVITE_REDIRECT="https://taxitips.se/forare",
)
class DriverInviteTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.company = self.make_company()
        self.owner = self.make_owner(self.company)
        self.make_subscription(self.company)
        self.vehicle, self.license = self.make_license(self.company, plate="EPO123", county="01")
        self.driver_user = str(uuid.uuid4())
        patcher = mock.patch("fleet.auth_admin.invite_link", side_effect=fake_link(self.driver_user))
        self.link = patcher.start()
        self.addCleanup(patcher.stop)

    # --- hjälp -------------------------------------------------------------

    def owner_post(self, path, body=None, user=None):
        return self.client.post(
            path, data=json.dumps(body or {}), content_type="application/json",
            headers={"authorization": f"Bearer {jwt(user or str(self.owner.user_id))}"},
        )

    def invite(self, email=DRIVER_EMAIL, **extra):
        return self.owner_post("/api/fleet/driver-invites", {
            "email": email, "licenseId": str(self.license.id), "label": "Anna", **extra,
        })

    def claim(self, *, user=None, email=DRIVER_EMAIL, installation="install-anna-0001", body=None):
        return self.client.post(
            "/api/fleet/driver-invites/claim",
            data=json.dumps({"installation_id": installation, "platform": "android", **(body or {})}),
            content_type="application/json",
            headers={"authorization": f"Bearer {jwt(user or self.driver_user, email)}"},
        )

    # --- skapa ---------------------------------------------------------------

    def test_the_owner_invites_a_driver_and_an_email_is_queued(self):
        response = self.invite("Anna@Forare.TEST")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()["invite"]
        self.assertEqual(body["email"], DRIVER_EMAIL)
        self.assertEqual(body["vehicleId"], str(self.vehicle.id))

        invite = DriverInvite.objects.get()
        self.assertEqual(invite.status, DriverInvite.Status.PENDING)
        self.assertEqual(str(invite.auth_user_id), self.driver_user)
        self.assertEqual(invite.send_count, 1)
        self.assertAlmostEqual(
            (invite.expires_at - timezone.now()).total_seconds(), 7 * 86400, delta=60
        )
        self.link.assert_called_once_with(DRIVER_EMAIL, "https://taxitips.se/forare")

        mail = OutboxMessage.objects.get(category="driver_invite")
        self.assertEqual(mail.to_address, DRIVER_EMAIL)
        self.assertIn("https://auth.test/verify", mail.body)
        self.assertIn("Jag är förare", mail.body)
        self.assertIn("EPO123", mail.body)
        # Utan avsändare skickas inget -- raden väntar.
        self.assertEqual(mail.status, OutboxMessage.Status.PENDING)
        self.assertTrue(AuditEvent.objects.filter(action="driver_invited").exists())

    def test_the_overview_shows_pending_invites_and_that_email_invites_are_on(self):
        self.invite()
        overview = self.client.get(
            "/api/fleet/company",
            headers={"authorization": f"Bearer {jwt(str(self.owner.user_id))}"},
        ).json()
        self.assertTrue(overview["driverInvites"]["enabled"])
        row = next(r for r in overview["licenses"] if r["licenseId"] == str(self.license.id))
        self.assertEqual([i["email"] for i in row["pendingInvites"]], [DRIVER_EMAIL])

    def test_a_new_invite_to_the_same_address_replaces_the_old(self):
        self.invite()
        self.invite()
        statuses = sorted(DriverInvite.objects.values_list("status", flat=True))
        self.assertEqual(statuses, ["pending", "revoked"])

    def test_an_invalid_address_is_refused(self):
        response = self.invite("inte-en-adress")
        self.assertEqual(response.json()["reason"], "invalid_email")
        self.assertFalse(DriverInvite.objects.exists())

    def test_without_the_service_key_email_invites_are_off(self):
        with override_settings(SUPABASE_SERVICE_ROLE_KEY=""):
            response = self.invite()
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json()["reason"], "invites_disabled")
            overview = self.client.get(
                "/api/fleet/company",
                headers={"authorization": f"Bearer {jwt(str(self.owner.user_id))}"},
            ).json()
            self.assertFalse(overview["driverInvites"]["enabled"])
        self.assertFalse(DriverInvite.objects.exists())

    def test_when_supabase_auth_fails_no_invite_is_left_behind(self):
        self.invite()
        self.link.side_effect = auth_admin.AuthAdminError("nere")
        response = self.invite()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["reason"], "invite_unavailable")
        # Ingen ny rad, och den tidigare väntande inbjudan är kvar orörd.
        self.assertEqual(
            list(DriverInvite.objects.values_list("status", flat=True)), ["pending"]
        )
        self.assertEqual(OutboxMessage.objects.filter(category="driver_invite").count(), 1)

    # --- behörighet ----------------------------------------------------------

    def test_inviting_requires_login(self):
        response = self.client.post(
            "/api/fleet/driver-invites",
            data=json.dumps({"email": DRIVER_EMAIL, "licenseId": str(self.license.id)}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_a_role_without_manage_devices_cannot_invite_or_list(self):
        finance = self.make_owner(self.company, role="finance")
        response = self.owner_post(
            "/api/fleet/driver-invites",
            {"email": DRIVER_EMAIL, "licenseId": str(self.license.id)},
            user=str(finance.user_id),
        )
        self.assertEqual(response.status_code, 403, response.content)
        listing = self.client.get(
            "/api/fleet/driver-invites",
            headers={"authorization": f"Bearer {jwt(str(finance.user_id))}"},
        )
        self.assertEqual(listing.status_code, 403)
        self.assertFalse(DriverInvite.objects.exists())

    def test_another_companys_license_is_not_found(self):
        other = self.make_company(name="Annat Taxi AB", org_number="5599887766")
        _vehicle, other_license = self.make_license(other, plate="ANN111")
        response = self.owner_post("/api/fleet/driver-invites", {
            "email": DRIVER_EMAIL, "licenseId": str(other_license.id),
        })
        self.assertEqual(response.status_code, 404)
        self.assertFalse(DriverInvite.objects.exists())

    def test_another_company_cannot_revoke_or_resend(self):
        self.invite()
        invite = DriverInvite.objects.get()
        other = self.make_company(name="Annat Taxi AB", org_number="5599887766")
        stranger = self.make_owner(other)
        for action in ("revoke", "resend"):
            response = self.owner_post(
                f"/api/fleet/driver-invites/{invite.id}/{action}", user=str(stranger.user_id)
            )
            self.assertEqual(response.status_code, 404, action)
        self.assertEqual(DriverInvite.objects.get().status, DriverInvite.Status.PENDING)

    # --- inlösen -------------------------------------------------------------

    def test_the_invited_driver_logs_in_and_the_phone_is_approved_for_the_car(self):
        self.invite()
        response = self.claim()
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertTrue(body["deviceToken"])
        self.assertEqual(body["licenseId"], str(self.license.id))
        self.assertEqual(body["plate"], "EPO123")

        approval = DeviceApproval.objects.get(id=body["approvalId"])
        self.assertEqual(approval.status, DeviceApproval.Status.ACTIVE)
        self.assertEqual(approval.label, "Anna")
        invite = DriverInvite.objects.get()
        self.assertEqual(invite.status, DriverInvite.Status.CONSUMED)
        self.assertEqual(str(invite.consumed_by_user), self.driver_user)
        self.assertEqual(str(invite.consumed_by_device), body["deviceId"])
        # Samma spår som engångskoden: risksignal och revision.
        self.assertTrue(RiskSignal.objects.filter(vehicle=self.vehicle).exists())
        approved = AuditEvent.objects.get(action="device_approved")
        self.assertEqual(approved.detail["via"], "email_invite")
        self.assertTrue(AuditEvent.objects.filter(action="driver_invite_claimed").exists())

        # Hemligheten fungerar som efter en kod.
        me = self.client.get("/api/fleet/me", headers={"X-Device-Token": body["deviceToken"]})
        self.assertEqual(me.status_code, 200, me.content)
        self.assertEqual([v["plate"] for v in me.json()["vehicles"]], ["EPO123"])

    def test_an_invite_is_single_use(self):
        self.invite()
        self.assertEqual(self.claim().status_code, 200)
        again = self.claim(installation="install-another-phone")
        self.assertEqual(again.status_code, 404)
        self.assertEqual(again.json()["reason"], "invite_used")
        self.assertEqual(DeviceApproval.objects.count(), 1)

    def test_another_address_gets_nothing(self):
        self.invite()
        response = self.claim(email="mallory@evil.test")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["reason"], "no_invite")
        self.assertFalse(DeviceApproval.objects.exists())
        self.assertEqual(DriverInvite.objects.get().status, DriverInvite.Status.PENDING)

    def test_the_address_in_the_request_body_is_ignored(self):
        self.invite()
        response = self.claim(email="mallory@evil.test", body={"email": DRIVER_EMAIL})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(DeviceApproval.objects.exists())

    def test_the_same_address_on_another_account_gets_nothing(self):
        """Någon som skapat ett eget konto med förarens adress löser inte in inbjudan."""
        self.invite()
        response = self.claim(user=str(uuid.uuid4()))
        self.assertEqual(response.status_code, 404)
        self.assertFalse(DeviceApproval.objects.exists())

    def test_claiming_requires_login(self):
        self.invite()
        response = self.client.post(
            "/api/fleet/driver-invites/claim",
            data=json.dumps({"installation_id": "install-anna-0001"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_an_expired_invite_is_refused(self):
        self.invite()
        DriverInvite.objects.update(expires_at=timezone.now() - timedelta(minutes=1))
        response = self.claim()
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()["reason"], "invite_expired")
        self.assertFalse(DeviceApproval.objects.exists())

    def test_a_revoked_invite_cannot_be_claimed(self):
        self.invite()
        invite = DriverInvite.objects.get()
        response = self.owner_post(f"/api/fleet/driver-invites/{invite.id}/revoke")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(DriverInvite.objects.get().status, DriverInvite.Status.REVOKED)
        claim = self.claim()
        self.assertEqual(claim.status_code, 404)
        self.assertFalse(DeviceApproval.objects.exists())

    def test_a_canceled_license_is_not_paired_through_an_old_invite(self):
        from fleet.models import License

        self.invite()
        License.objects.filter(id=self.license.id).update(status=License.Status.CANCELED)
        response = self.claim()
        self.assertEqual(response.json()["reason"], "license_inactive")
        self.assertEqual(DriverInvite.objects.get().status, DriverInvite.Status.PENDING)
        self.assertFalse(DeviceApproval.objects.exists())

    def test_claims_are_rate_limited_per_account(self):
        for _ in range(10):
            self.claim(email="ingen@inbjudan.test")
        response = self.claim(email="ingen@inbjudan.test")
        self.assertEqual(response.json()["reason"], "rate_limited")

    # --- skicka igen ---------------------------------------------------------

    def test_resend_gives_a_new_link_and_seven_new_days(self):
        self.invite()
        invite = DriverInvite.objects.get()
        DriverInvite.objects.update(expires_at=timezone.now() - timedelta(hours=1))
        response = self.owner_post(f"/api/fleet/driver-invites/{invite.id}/resend")
        self.assertEqual(response.status_code, 200, response.content)
        invite.refresh_from_db()
        self.assertEqual(invite.send_count, 2)
        self.assertGreater(invite.expires_at, timezone.now() + timedelta(days=6))
        self.assertEqual(OutboxMessage.objects.filter(category="driver_invite").count(), 2)
        self.assertEqual(self.claim().status_code, 200)

    def test_a_used_invite_is_not_resent(self):
        self.invite()
        self.claim()
        invite = DriverInvite.objects.get()
        response = self.owner_post(f"/api/fleet/driver-invites/{invite.id}/resend")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(OutboxMessage.objects.filter(category="driver_invite").count(), 1)

    def test_the_list_shows_pending_invites(self):
        self.invite()
        listing = self.client.get(
            "/api/fleet/driver-invites",
            headers={"authorization": f"Bearer {jwt(str(self.owner.user_id))}"},
        ).json()
        self.assertTrue(listing["enabled"])
        self.assertEqual([i["email"] for i in listing["invites"]], [DRIVER_EMAIL])


@override_settings(SUPABASE_URL="http://auth.test", SUPABASE_SERVICE_ROLE_KEY="svc")
class AuthAdminTests(FleetTestCase):
    """Länken från Supabase Auth: ny användare, eller en som redan finns."""

    def response(self, status, payload):
        res = requests.Response()
        res.status_code = status
        res._content = json.dumps(payload).encode()
        return res

    def test_a_new_address_gets_an_invite_link(self):
        with mock.patch("fleet.auth_admin.requests.post", return_value=self.response(
            200, {"id": "u-1", "email": "a@b.test", "action_link": "https://x/verify?type=invite"}
        )) as post:
            link = auth_admin.invite_link("a@b.test", "https://taxitips.se/forare")
        self.assertEqual((link.url, link.user_id, link.kind), ("https://x/verify?type=invite", "u-1", "invite"))
        url = post.call_args.args[0]
        self.assertEqual(url, "http://auth.test/auth/v1/admin/generate_link")
        self.assertEqual(post.call_args.kwargs["json"]["redirect_to"], "https://taxitips.se/forare")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer svc")

    def test_an_existing_account_gets_a_recovery_link(self):
        responses = [
            self.response(422, {"code": 422, "error_code": "email_exists",
                                "msg": "A user with this email address has already been registered"}),
            self.response(200, {"properties": {"action_link": "https://x/verify?type=recovery"},
                                "user": {"id": "u-2"}}),
        ]
        with mock.patch("fleet.auth_admin.requests.post", side_effect=responses) as post:
            link = auth_admin.invite_link("a@b.test", "https://taxitips.se/forare")
        self.assertEqual((link.user_id, link.kind), ("u-2", "recovery"))
        self.assertEqual(post.call_args.kwargs["json"]["type"], "recovery")

    def test_other_errors_are_raised(self):
        with mock.patch("fleet.auth_admin.requests.post", return_value=self.response(500, {"msg": "x"})):
            with self.assertRaises(auth_admin.AuthAdminError):
                auth_admin.invite_link("a@b.test", "https://taxitips.se/forare")

    def test_without_a_key_nothing_is_called(self):
        with override_settings(SUPABASE_SERVICE_ROLE_KEY=""):
            with mock.patch("fleet.auth_admin.requests.post") as post:
                with self.assertRaises(auth_admin.AuthAdminError):
                    auth_admin.invite_link("a@b.test", "https://taxitips.se/forare")
            post.assert_not_called()
