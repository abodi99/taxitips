"""
Registrering och återställning med BankID (fleet/bankid.py, fleet/registration.py).

Proxyn och Supabase Auth mockas. Det viktiga: klienten kan aldrig själv
påstå vem den är (bara en biljett från en order som startades här), en
person får ett konto och ett prov, personnumret sparas inte, och ett konto
utan organisationsnummer kan inte beställa förrän numret är angivet.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from unittest import mock

from django.core import signing
from django.test import Client, override_settings
from django.utils import timezone

from billing.models import Company, CompanyMember
from fleet import accounts, auth_admin, bankid
from fleet.models import (
    AuditEvent,
    BankIdIdentity,
    BankIdOrder,
    CompanyProfile,
    KnownAccount,
    OutboxMessage,
    Trial,
)
from fleet.tests.base import FleetTestCase
from fleet.tests.test_accounts import SECRET, jwt

PNR = "198001011234"


class _Response:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body)
        self.content = self.text.encode()

    def json(self):
        return self._body


def proxy(*, collect_status="complete", pnr=PNR, name="Anna Andersson", order=None):
    """Fejkad BankID-proxy: svarar på /auth, /collect och /cancel."""
    calls = []
    order = order or f"order-{uuid.uuid4().hex}"

    def post(url, json=None, headers=None, timeout=None):
        calls.append((url, json, headers))
        if url.endswith("/auth"):
            return _Response(200, {"orderRef": order, "autoStartToken": "auto", "qrStartToken": "q", "qrStartSecret": "s"})
        if url.endswith("/collect"):
            if collect_status == "pending":
                return _Response(200, {"orderRef": order, "status": "pending", "hintCode": "userSign"})
            if collect_status == "failed":
                return _Response(200, {"orderRef": order, "status": "failed", "hintCode": "userCancel"})
            return _Response(200, {
                "orderRef": order, "status": "complete",
                "completionData": {"user": {"personalNumber": pnr, "name": name, "givenName": name.split()[0]}},
            })
        return _Response(200, {})

    return post, calls


@override_settings(
    BANKID_PROXY_URL="https://bankid-proxy.test",
    BANKID_PROXY_SECRET="proxy-secret",
    BANKID_PNR_PEPPER="pepper-for-tests",
    SUPABASE_JWT_SECRET=SECRET,
    SUPABASE_SERVICE_ROLE_KEY="test-service-role",
)
class BankIdTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        accounts._seen_cache.clear()
        self.client = Client()
        self.created_users = []

        def create_user(email, password, app_metadata=None):
            user_id = str(uuid.uuid4())
            self.created_users.append((user_id, email, password, app_metadata))
            return user_id

        patcher = mock.patch("fleet.auth_admin.create_user", side_effect=create_user)
        self.create_user = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch("fleet.auth_admin.delete_user")
        self.delete_user = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch("fleet.auth_admin.update_user")
        self.update_user = patcher.start()
        self.addCleanup(patcher.stop)

    # -- hjälp -------------------------------------------------------------

    def post(self, path, body, user=None):
        headers = {"authorization": f"Bearer {jwt(user)}"} if user else {}
        return self.client.post(path, data=json.dumps(body), content_type="application/json", headers=headers)

    def ticket(self, purpose="register", **kwargs):
        fake, _calls = proxy(**kwargs)
        with mock.patch("fleet.bankid.requests.post", side_effect=fake):
            start = self.post("/api/fleet/bankid/start", {"purpose": purpose})
            self.assertEqual(start.status_code, 200, start.content)
            collect = self.post("/api/fleet/bankid/collect", {"orderRef": start.json()["orderRef"]})
        self.assertEqual(collect.status_code, 200, collect.content)
        return collect.json()["ticket"]

    def register(self, ticket=None, **overrides):
        body = {
            "ticket": ticket or self.ticket(),
            "email": "anna@exempeltaxi.se", "password": "hemligt123",
            "contactPhone": "070-812 34 91", "companyName": "Annas Taxi",
        }
        body.update(overrides)
        return self.post("/api/fleet/bankid/register", body)

    # -- BankID-ordern -----------------------------------------------------

    def test_start_sends_visible_text_and_server_decides_production(self):
        fake, calls = proxy()
        with mock.patch("fleet.bankid.requests.post", side_effect=fake):
            res = self.post("/api/fleet/bankid/start", {"purpose": "register", "useProduction": True})
        self.assertEqual(res.status_code, 200, res.content)
        url, body, headers = calls[0]
        self.assertTrue(url.endswith("/auth"))
        self.assertFalse(body["useProduction"])  # styrs av servern, inte anropet
        self.assertIn("userVisibleData", body)
        self.assertEqual(headers["Authorization"], "Bearer proxy-secret")
        self.assertEqual(res.json()["autoStartToken"], "auto")

    def test_pending_returns_swedish_hint_and_no_ticket(self):
        fake, _ = proxy(collect_status="pending")
        with mock.patch("fleet.bankid.requests.post", side_effect=fake):
            ref = self.post("/api/fleet/bankid/start", {"purpose": "register"}).json()["orderRef"]
            res = self.post("/api/fleet/bankid/collect", {"orderRef": ref}).json()
        self.assertEqual(res["status"], "pending")
        self.assertIn("säkerhetskod", res["message"])
        self.assertNotIn("ticket", res)

    def test_order_not_started_here_gives_no_ticket(self):
        fake, _ = proxy()
        with mock.patch("fleet.bankid.requests.post", side_effect=fake):
            res = self.post("/api/fleet/bankid/collect", {"orderRef": "volontera-order"})
        self.assertEqual(res.status_code, 404)

    def test_one_order_gives_one_ticket(self):
        fake, _ = proxy()
        with mock.patch("fleet.bankid.requests.post", side_effect=fake):
            ref = self.post("/api/fleet/bankid/start", {"purpose": "register"}).json()["orderRef"]
            self.assertEqual(self.post("/api/fleet/bankid/collect", {"orderRef": ref}).status_code, 200)
            again = self.post("/api/fleet/bankid/collect", {"orderRef": ref})
        self.assertEqual(again.status_code, 409)

    def test_collect_response_has_no_personal_number(self):
        fake, _ = proxy()
        with mock.patch("fleet.bankid.requests.post", side_effect=fake):
            ref = self.post("/api/fleet/bankid/start", {"purpose": "register"}).json()["orderRef"]
            res = self.post("/api/fleet/bankid/collect", {"orderRef": ref})
        self.assertNotIn(PNR, res.content.decode())
        self.assertEqual(res.json()["givenName"], "Anna")

    def test_proxy_down_is_a_clear_503(self):
        import requests

        with mock.patch("fleet.bankid.requests.post", side_effect=requests.ConnectionError()):
            res = self.post("/api/fleet/bankid/start", {"purpose": "register"})
        self.assertEqual(res.status_code, 503)
        self.assertEqual(res.json()["reason"], "bankid_unavailable")

    # -- Biljetten ---------------------------------------------------------

    def test_forged_and_expired_tickets_are_rejected(self):
        forged = signing.dumps({"k": "x", "p": "register"}, salt="något annat")
        self.assertEqual(self.register(ticket=forged).status_code, 401)
        ticket = self.ticket()
        with mock.patch("django.core.signing.time.time", return_value=timezone.now().timestamp() + 16 * 60):
            res = self.register(ticket=ticket)
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.json()["reason"], "ticket_expired")

    def test_register_ticket_cannot_be_used_to_recover(self):
        res = self.post("/api/fleet/bankid/recover", {"ticket": self.ticket("register"), "newPassword": "nyttlosen1"})
        self.assertEqual(res.status_code, 401)

    # -- Registrering ------------------------------------------------------

    def test_register_creates_confirmed_account_company_and_trial_without_org_number(self):
        res = self.register()
        self.assertEqual(res.status_code, 201, res.content)
        data = res.json()
        user_id, email, password, meta = self.created_users[0]
        self.assertEqual((email, password, meta), ("anna@exempeltaxi.se", "hemligt123", {"bankid": True}))

        company = Company.objects.get(id=data["companyId"])
        self.assertEqual(company.name, "Annas Taxi")
        self.assertFalse(company.org_number)
        profile = CompanyProfile.objects.get(company_id=company.id)
        self.assertEqual(profile.org_number, "")
        self.assertEqual(profile.contact_name, "Anna Andersson")  # från BankID
        self.assertEqual(profile.contact_phone, "+46708123491")
        self.assertTrue(CompanyMember.objects.filter(user_id=user_id, role="company_owner").exists())

        trial = Trial.objects.get(company_id=company.id)
        self.assertEqual(trial.status, Trial.Status.ACTIVE)
        self.assertTrue(trial.org_key.startswith("PNR:"))
        self.assertTrue(OutboxMessage.objects.filter(category="trial_started").exists())
        self.assertEqual(KnownAccount.objects.get(user_id=user_id).email, "anna@exempeltaxi.se")

        # Personnumret finns ingenstans i klartext.
        identity = BankIdIdentity.objects.get(user_id=user_id)
        self.assertNotIn(PNR, identity.pnr_key)
        self.assertNotIn(PNR, json.dumps(list(AuditEvent.objects.values("detail")), default=str))

        # Uppföljningen säger varför numret saknas.
        from fleet import signup_checks

        self.assertIn("org_number_later", [f["code"] for f in signup_checks.flags(profile)])

    def test_same_person_cannot_register_twice(self):
        self.assertEqual(self.register().status_code, 201)
        res = self.register(email="annan@exempeltaxi.se", contactPhone="073-948 15 62", companyName="Ny AB")
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["reason"], "person_has_account")
        self.assertEqual(len(self.created_users), 1)  # inget andra Auth-konto

    def test_phone_used_by_another_trial_is_refused(self):
        self.assertEqual(self.register().status_code, 201)
        other = self.ticket(pnr="199002023456")
        res = self.register(ticket=other, email="b@exempeltaxi.se")
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["reason"], "phone_in_use")

    def test_email_taken_and_weak_password(self):
        self.assertEqual(self.register(password="kort").json()["reason"], "weak_password")
        self.create_user.side_effect = auth_admin.EmailTaken("x")
        res = self.register()
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["reason"], "email_taken")
        self.assertFalse(Company.objects.filter(name="Annas Taxi").exists())

    def test_database_failure_removes_the_auth_account(self):
        with mock.patch("fleet.registration.CompanyMember.objects.create", side_effect=RuntimeError("db")):
            res = self.register()
        self.assertEqual(res.status_code, 500)
        self.delete_user.assert_called_once_with(self.created_users[0][0])
        self.assertFalse(BankIdIdentity.objects.exists())

    def test_person_whose_trial_ended_gets_account_but_no_new_trial(self):
        Trial.objects.create(
            company_id=uuid.uuid4(), org_key=bankid.trial_key(bankid.pnr_key(PNR)),
            source=Trial.Source.SELF_SIGNUP, status=Trial.Status.ENDED,
            started_at=timezone.now() - timedelta(days=30),
        )
        res = self.register()
        self.assertEqual(res.status_code, 201, res.content)
        self.assertIsNone(res.json()["trial"])
        self.assertFalse(Trial.objects.filter(company_id=res.json()["companyId"]).exists())

    # -- Återställning -----------------------------------------------------

    def collect_recover(self, **kwargs):
        fake, _ = proxy(**kwargs)
        with mock.patch("fleet.bankid.requests.post", side_effect=fake):
            ref = self.post("/api/fleet/bankid/start", {"purpose": "recover"}).json()["orderRef"]
            return self.post("/api/fleet/bankid/collect", {"orderRef": ref}).json()

    def test_recover_collect_shows_the_account_email(self):
        self.register()
        data = self.collect_recover()
        self.assertEqual(data["accountEmail"], "anna@exempeltaxi.se")
        # Någon annans BankID ser inte kontot.
        self.assertIsNone(self.collect_recover(pnr="199002023456")["accountEmail"])

    def test_register_collect_does_not_reveal_emails(self):
        self.register()
        fake, _ = proxy()
        with mock.patch("fleet.bankid.requests.post", side_effect=fake):
            ref = self.post("/api/fleet/bankid/start", {"purpose": "register"}).json()["orderRef"]
            data = self.post("/api/fleet/bankid/collect", {"orderRef": ref}).json()
        self.assertNotIn("accountEmail", data)

    def test_recover_sets_password_and_email_and_tells_old_address(self):
        self.register()
        user_id = self.created_users[0][0]
        res = self.post("/api/fleet/bankid/recover", {
            "ticket": self.ticket("recover"), "newPassword": "nyttlosen1", "newEmail": "Ny@ExempelTaxi.se",
        })
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["email"], "ny@exempeltaxi.se")
        self.update_user.assert_called_once_with(user_id, password="nyttlosen1", email="ny@exempeltaxi.se")
        notice = OutboxMessage.objects.get(category="login_email_changed")
        self.assertEqual(notice.to_address, "anna@exempeltaxi.se")
        self.assertEqual(KnownAccount.objects.get(user_id=user_id).email, "ny@exempeltaxi.se")
        self.assertTrue(AuditEvent.objects.filter(action="bankid_recovered").exists())

    def test_recover_ticket_works_once(self):
        self.register()
        ticket = self.ticket("recover")
        self.assertEqual(self.post("/api/fleet/bankid/recover", {"ticket": ticket, "newPassword": "nyttlosen1"}).status_code, 200)
        again = self.post("/api/fleet/bankid/recover", {"ticket": ticket, "newPassword": "annatlosen1"})
        self.assertEqual(again.status_code, 409)

    def test_recover_without_bankid_account(self):
        res = self.post("/api/fleet/bankid/recover", {"ticket": self.ticket("recover"), "newPassword": "nyttlosen1"})
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["reason"], "no_bankid_account")
        self.update_user.assert_not_called()

    # -- Inloggning med BankID ---------------------------------------------

    def test_login_with_bankid_returns_a_one_time_token_for_the_own_account(self):
        self.register()
        with mock.patch("fleet.auth_admin.login_token", return_value="hash-123") as token:
            res = self.post("/api/fleet/bankid/login", {"ticket": self.ticket("login")})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["tokenHash"], "hash-123")
        self.assertEqual(res.json()["email"], "anna@exempeltaxi.se")
        token.assert_called_once_with("anna@exempeltaxi.se")
        self.assertTrue(AuditEvent.objects.filter(action="bankid_login").exists())

    def test_login_ticket_works_once_and_other_tickets_do_not_log_in(self):
        self.register()
        ticket = self.ticket("login")
        with mock.patch("fleet.auth_admin.login_token", return_value="h") as token:
            self.assertEqual(self.post("/api/fleet/bankid/login", {"ticket": ticket}).status_code, 200)
            self.assertEqual(self.post("/api/fleet/bankid/login", {"ticket": ticket}).status_code, 409)
            # En biljett för registrering eller återställning loggar inte in.
            for purpose in ("register", "recover"):
                res = self.post("/api/fleet/bankid/login", {"ticket": self.ticket(purpose)})
                self.assertEqual(res.status_code, 401, purpose)
        self.assertEqual(token.call_count, 1)

    def test_login_without_a_bankid_account(self):
        with mock.patch("fleet.auth_admin.login_token") as token:
            res = self.post("/api/fleet/bankid/login", {"ticket": self.ticket("login")})
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["reason"], "no_bankid_account")
        token.assert_not_called()

    def test_another_persons_bankid_cannot_log_in_to_the_account(self):
        self.register()
        with mock.patch("fleet.auth_admin.login_token") as token:
            res = self.post("/api/fleet/bankid/login", {"ticket": self.ticket("login", pnr="199002023456")})
        self.assertEqual(res.status_code, 404)
        token.assert_not_called()

    # -- Bli betalande -----------------------------------------------------

    def test_order_requires_org_number_then_it_can_be_added_once(self):
        company_id = self.register().json()["companyId"]
        owner = self.created_users[0][0]
        overview = self.client.get("/api/fleet/company", headers={"authorization": f"Bearer {jwt(owner)}"}).json()
        self.assertTrue(overview["company"]["details"]["needsOrgNumber"])

        for path in ("/api/fleet/orders", "/api/fleet/trial/commit"):
            res = self.post(path, {"accepted": True}, user=owner)
            self.assertEqual(res.status_code, 409, (path, res.content))
            self.assertEqual(res.json()["reason"], "company_details_required")

        res = self.post("/api/fleet/company/org-number", {"orgNumber": "556036-0793", "legalName": "Annas Taxi AB"}, user=owner)
        self.assertEqual(res.status_code, 200, res.content)
        profile = CompanyProfile.objects.get(company_id=company_id)
        self.assertEqual(profile.org_number, "5560360793")
        self.assertEqual(Company.objects.get(id=company_id).org_number, "5560360793")

        again = self.post("/api/fleet/company/org-number", {"orgNumber": "5566778899"}, user=owner)
        self.assertEqual(again.json()["reason"], "org_number_set")

        res = self.post("/api/fleet/orders", {"accepted": True}, user=owner)
        self.assertNotEqual(res.json().get("reason"), "company_details_required")

    def test_org_number_of_another_customer_is_refused(self):
        self.make_company(org_number="5560360793")
        self.register()
        owner = self.created_users[0][0]
        res = self.post("/api/fleet/company/org-number", {"orgNumber": "5560360793"}, user=owner)
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.json()["reason"], "company_exists")

    def test_existing_companies_with_org_number_are_not_blocked(self):
        company = self.make_company()
        owner = str(self.make_owner(company).user_id)
        res = self.post("/api/fleet/orders", {"accepted": True}, user=owner)
        self.assertNotEqual(res.json().get("reason"), "company_details_required")


class BankIdOrderTableTests(FleetTestCase):
    def test_tables_exist_with_expected_names(self):
        self.assertEqual(BankIdIdentity._meta.db_table, "fleet_bankid_identity")
        self.assertEqual(BankIdOrder._meta.db_table, "fleet_bankid_order")
