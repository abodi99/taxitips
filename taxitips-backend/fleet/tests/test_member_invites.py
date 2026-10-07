"""
Inbjudan av inloggningar: ägaren bjuder in en kollega, Taxi Tips bjuder in
kundens ägare -- och mejlet har logga, knapp och en text som går att läsa utan
HTML.
"""

from __future__ import annotations

import json
import uuid
from unittest import mock

from django.test import Client, override_settings

from billing.models import CompanyMember
from fleet import auth_admin, email_layout
from fleet.models import AuditEvent, OutboxMessage, OwnerInvite, StaffRole
from fleet.tests.base import FleetTestCase
from fleet.tests.test_support import SECRET, jwt

LINK = "https://api.taxitips.se/auth/v1/verify?token=abc&type=invite&redirect_to=https://taxitips.se/portal"


def fake_link(email, redirect_to):
    return auth_admin.AuthLink(url=LINK, user_id=str(uuid.uuid4()), kind="invite")


@override_settings(SUPABASE_JWT_SECRET=SECRET, SUPABASE_SERVICE_ROLE_KEY="test-service-role")
class MemberInviteTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.company = self.make_company(name="Taxi Demo AB")
        self.owner = self.make_owner(self.company)
        self.make_subscription(self.company)
        patcher = mock.patch("fleet.auth_admin.invite_link", side_effect=fake_link)
        self.link = patcher.start()
        self.addCleanup(patcher.stop)

    def call(self, method, path, body=None, user=None, email=""):
        headers = {"authorization": f"Bearer {jwt(str(user or self.owner.user_id), email)}"}
        if method == "get":
            return self.client.get(path, headers=headers)
        return self.client.post(
            path, data=json.dumps(body or {}), content_type="application/json", headers=headers
        )

    def test_the_owner_invites_a_colleague_who_joins_with_that_role(self):
        response = self.call("post", "/api/fleet/members/invite", {"email": "Bo@Demo.se", "role": "finance"})
        self.assertEqual(response.status_code, 200, response.content)

        invite = OwnerInvite.objects.get()
        self.assertEqual((invite.email, invite.role), ("bo@demo.se", "finance"))
        mail = OutboxMessage.objects.get(category="member_invite")
        self.assertEqual(mail.to_address, "bo@demo.se")
        self.assertIn("Taxi Demo AB", mail.subject)
        self.assertIn(LINK, mail.body)
        self.assertEqual(mail.payload["button"]["url"], LINK)

        listing = self.call("get", "/api/fleet/members").json()
        self.assertTrue(listing["canManage"])
        self.assertEqual(listing["invites"][0]["email"], "bo@demo.se")

        colleague = str(uuid.uuid4())
        claimed = self.call("post", "/api/fleet/claim-invite", user=colleague, email="bo@demo.se")
        self.assertEqual(claimed.status_code, 200, claimed.content)
        self.assertEqual(CompanyMember.objects.get(user_id=colleague).role, "finance")

    def test_a_colleague_cannot_be_invited_as_owner(self):
        response = self.call("post", "/api/fleet/members/invite", {"email": "bo@demo.se", "role": "company_owner"})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(OwnerInvite.objects.exists())

    def test_only_someone_who_manages_members_can_invite(self):
        finance = self.make_owner(self.company, role="finance")
        response = self.call("post", "/api/fleet/members/invite", {"email": "bo@demo.se"}, user=finance.user_id)
        self.assertEqual(response.status_code, 403)
        # Men listan får hen se.
        self.assertEqual(self.call("get", "/api/fleet/members", user=finance.user_id).status_code, 200)

    def test_without_a_link_the_invite_is_withdrawn(self):
        self.link.side_effect = auth_admin.AuthAdminError("nere")
        response = self.call("post", "/api/fleet/members/invite", {"email": "bo@demo.se"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(OwnerInvite.objects.get().status, OwnerInvite.Status.REVOKED)

    def test_the_owner_can_revoke_an_invite(self):
        self.call("post", "/api/fleet/members/invite", {"email": "bo@demo.se"})
        invite = OwnerInvite.objects.get()
        response = self.call("post", f"/api/fleet/members/invites/{invite.id}/revoke")
        self.assertEqual(response.status_code, 200)
        invite.refresh_from_db()
        self.assertEqual(invite.status, OwnerInvite.Status.REVOKED)
        self.assertTrue(AuditEvent.objects.filter(action="owner_invite_revoked").exists())

    def test_staff_invites_the_owner_and_the_server_sends_the_mail(self):
        staff = str(uuid.uuid4())
        StaffRole.objects.create(user_id=staff, role=StaffRole.Role.PLATFORM_ADMIN)
        response = self.call(
            "post", f"/api/admin/companies/{self.company.id}/owner-invite", {"email": "ny@demo.se"}, user=staff,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["mailSent"])
        self.assertEqual(OwnerInvite.objects.get().role, "company_owner")
        self.assertIn("Taxi Tips har bjudit in dig", OutboxMessage.objects.get(category="member_invite").body)

    @override_settings(SUPABASE_SERVICE_ROLE_KEY="")
    def test_without_the_service_key_staff_are_told_no_mail_was_sent(self):
        staff = str(uuid.uuid4())
        StaffRole.objects.create(user_id=staff, role=StaffRole.Role.PLATFORM_ADMIN)
        response = self.call(
            "post", f"/api/admin/companies/{self.company.id}/owner-invite", {"email": "ny@demo.se"}, user=staff,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.json()["mailSent"])
        self.assertFalse(OutboxMessage.objects.filter(category="member_invite").exists())


class EmailLayoutTests(FleetTestCase):
    def test_the_html_has_logo_button_and_no_bare_link_line(self):
        body = "Hej!\n\nTryck här:\nhttps://x.se/a?b=1&c=2\n\nMer <text>.\n\nFrågor? Svara på det här mejlet eller chatta"
        out = email_layout.from_text(
            "Rubrik", body, {"button": {"url": "https://x.se/a?b=1&c=2", "label": "Öppna"}},
        )
        self.assertIn("/email/logo.png", out)
        self.assertIn('href="https://x.se/a?b=1&amp;c=2"', out)
        self.assertIn(">Öppna</a>", out)
        self.assertIn("Mer &lt;text&gt;.", out)
        # Länken står bara i knappen, och signaturen blir sidfot.
        self.assertEqual(out.count("https://x.se/a?b=1&amp;c=2"), 1)
        self.assertNotIn("Svara på det här mejlet eller chatta<", out.split("</h1>")[1].split("</td>")[0])

    def test_a_code_gets_its_own_box(self):
        out = email_layout.from_text("Din kod", "Skriv koden i appen.", {"code": "123456"})
        self.assertIn("letter-spacing:6px", out)
        self.assertIn("123456", out)


class AuthTemplateTests(FleetTestCase):
    def test_the_auth_templates_keep_gotrues_placeholders(self):
        import tempfile
        from pathlib import Path

        from django.core.management import call_command

        with tempfile.TemporaryDirectory() as out:
            call_command("build_auth_email_templates", out=out, stdout=open("/dev/null", "w"))
            confirmation = (Path(out) / "confirmation.html").read_text()
            recovery = (Path(out) / "recovery.html").read_text()
        # Registreringen bekräftas med länken -- ingen engångskod i mejlet.
        self.assertNotIn("{{ .Token }}", confirmation)
        self.assertIn('href="{{ .ConfirmationURL }}"', confirmation)
        self.assertIn("/email/logo.png", confirmation)
        # Återställningen är bara en länk: appen ber inte om någon kod där.
        self.assertNotIn("{{ .Token }}", recovery)
