"""
Spärrar, självregistrering och kontohantering i adminwebben.

Det viktigaste testas först: en spärr ska bita på ALLA vägar in -- förarens
telefon, den inloggade ägaren och administratörsbehörigheten -- och en hävd
spärr ska återställa exakt det som fanns.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid

from django.test import Client, RequestFactory, override_settings

from billing.models import Company, CompanyMember
from fleet import access, accounts
from fleet.models import (
    AccountBlock,
    AuditEvent,
    CompanyProfile,
    KnownAccount,
    License,
    StaffRole,
    Trial,
)
from fleet.tests.base import FleetTestCase

SECRET = "accounts-test-secret-at-least-32-characters!"


def jwt(sub: str, email: str = "", aal: str = "aal1") -> str:
    def seg(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    head = seg({"alg": "HS256", "typ": "JWT"})
    claims = {"sub": sub, "exp": int(time.time()) + 3600, "aal": aal}
    if email:
        claims["email"] = email
    body = seg(claims)
    sig = hmac.new(SECRET.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"


class _Base(FleetTestCase):
    def setUp(self):
        super().setUp()
        accounts._seen_cache.clear()
        self.client = Client()
        self.admin_id = str(uuid.uuid4())
        StaffRole.objects.create(user_id=self.admin_id, role=StaffRole.Role.PLATFORM_ADMIN)

    def call(self, method, path, user_id, body=None, email=""):
        headers = {"authorization": f"Bearer {jwt(user_id, email)}"}
        if method == "get":
            return self.client.get(path, headers=headers)
        return self.client.post(
            path, data=json.dumps(body or {}), content_type="application/json", headers=headers,
        )

    def driver_access(self, secret):
        request = RequestFactory().get("/api/alerts", headers={"X-Device-Token": secret})
        return access.resolve(request)


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class SuspensionTests(_Base):
    def test_a_suspended_company_loses_driver_and_owner_access_and_gets_it_back(self):
        data = self.full_setup()
        owner = str(data["owner"].user_id)
        before = self.driver_access(data["secret"]).reason
        self.assertNotEqual(before, "company_suspended")

        response = self.call("post", "/api/admin/blocks/new", self.admin_id, {
            "kind": "company", "value": str(data["company"].id), "reason": "Obetalda fakturor",
        })
        self.assertEqual(response.status_code, 201, response.content)

        driver = self.driver_access(data["secret"])
        self.assertFalse(driver.ok)
        self.assertEqual(driver.reason, "company_suspended")
        overview = self.call("get", "/api/fleet/company", owner).json()
        self.assertFalse(overview["access"]["ok"])
        self.assertTrue(overview["company"]["suspended"])
        # Ägaren ser läget men kan inte ändra något.
        denied = self.call("post", "/api/fleet/vehicles", owner, {"plate": "NEW123"})
        self.assertEqual(denied.status_code, 403)

        block_id = response.json()["block"]["id"]
        lifted = self.call("post", f"/api/admin/blocks/{block_id}/lift", self.admin_id, {"note": "Betalt"})
        self.assertEqual(lifted.status_code, 200, lifted.content)
        self.assertEqual(self.driver_access(data["secret"]).reason, before)
        # Inget raderades: licensen och spärrens historik finns kvar.
        self.assertTrue(License.objects.filter(id=data["license"].id).exists())
        self.assertIsNotNone(AccountBlock.objects.get(id=block_id).lifted_at)
        self.assertTrue(AuditEvent.objects.filter(action="admin_block_company").exists())
        self.assertTrue(AuditEvent.objects.filter(action="admin_unblock_company").exists())

    def test_a_block_needs_a_reason_and_only_one_can_be_active(self):
        data = self.full_setup()
        body = {"kind": "company", "value": str(data["company"].id)}
        self.assertEqual(self.call("post", "/api/admin/blocks/new", self.admin_id, body).status_code, 400)
        body["reason"] = "Test"
        self.assertEqual(self.call("post", "/api/admin/blocks/new", self.admin_id, body).status_code, 201)
        self.assertEqual(self.call("post", "/api/admin/blocks/new", self.admin_id, body).status_code, 409)

    def test_support_can_read_blocks_but_not_create_them(self):
        support = str(uuid.uuid4())
        StaffRole.objects.create(user_id=support, role=StaffRole.Role.SUPPORT)
        data = self.full_setup()
        self.assertEqual(self.call("get", "/api/admin/blocks", support).status_code, 200)
        response = self.call("post", "/api/admin/blocks/new", support, {
            "kind": "company", "value": str(data["company"].id), "reason": "x",
        })
        self.assertEqual(response.status_code, 403)


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class AccountBlockTests(_Base):
    def test_a_blocked_email_loses_member_access_and_admin_rights(self):
        data = self.full_setup()
        owner = str(data["owner"].user_id)
        email = "Agare@Example.test"
        self.assertEqual(self.call("get", "/api/fleet/company", owner, email=email).status_code, 200)
        # Katalogen fylldes ur den verifierade token, i gemener.
        self.assertEqual(KnownAccount.objects.get(user_id=owner).email, "agare@example.test")

        response = self.call("post", "/api/admin/blocks/new", self.admin_id, {
            "kind": "email", "value": "agare@example.test", "reason": "Bedrägeriförsök",
        })
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(self.call("get", "/api/fleet/company", owner, email=email).status_code, 403)
        request = RequestFactory().get("/", headers={"authorization": f"Bearer {jwt(owner, email)}"})
        self.assertEqual(access.resolve(request).reason, "account_blocked")

    def test_a_blocked_staff_account_is_not_staff(self):
        other_admin = str(uuid.uuid4())
        StaffRole.objects.create(user_id=other_admin, role=StaffRole.Role.PLATFORM_ADMIN)
        self.call("post", "/api/admin/blocks/new", self.admin_id, {
            "kind": "user", "value": other_admin, "reason": "Slutat",
        })
        self.assertEqual(self.call("get", "/api/admin/overview", other_admin).status_code, 403)

    def test_you_cannot_block_yourself(self):
        response = self.call("post", "/api/admin/blocks/new", self.admin_id, {
            "kind": "user", "value": self.admin_id, "reason": "oops",
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["reason"], "self_block")

    def test_account_search_finds_by_email_and_shows_memberships(self):
        data = self.full_setup()
        owner = str(data["owner"].user_id)
        self.call("get", "/api/fleet/company", owner, email="kund@example.test")
        rows = self.call("get", "/api/admin/accounts?q=kund@", self.admin_id).json()["accounts"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["memberships"][0]["companyName"], data["company"].name)

    def test_a_member_can_be_disabled_in_one_company(self):
        data = self.full_setup()
        owner = str(data["owner"].user_id)
        response = self.call(
            "post", f"/api/admin/companies/{data['company'].id}/members/{owner}",
            self.admin_id, {"status": "disabled"},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(CompanyMember.objects.get(user_id=owner).status, "disabled")
        self.assertEqual(self.call("get", "/api/fleet/company", owner).status_code, 403)


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class RegistrationTests(_Base):
    def register(self, user_id, email, **body):
        payload = {"orgNumber": "5560360793", "companyName": "Nya Taxi AB", **body}
        return self.call("post", "/api/fleet/register", user_id, payload, email=email)

    def test_registration_creates_owner_company_and_a_card_free_trial(self):
        user = str(uuid.uuid4())
        response = self.register(
            user, "ny@example.test", vehicles=[{"plate": "ABC123", "baseCounty": "12"}],
        )
        self.assertEqual(response.status_code, 201, response.content)
        body = response.json()
        company = Company.objects.get(id=body["companyId"])
        self.assertEqual(company.status, "inactive")
        self.assertEqual(CompanyMember.objects.get(user_id=user).role, "company_owner")
        profile = CompanyProfile.objects.get(company_id=company.id)
        # En e-post och ett orgnr bevisar inte behörighet (§7).
        self.assertEqual(profile.verification_status, "unverified")
        trial = Trial.objects.get(company_id=company.id)
        self.assertFalse(trial.requires_payment_method)
        self.assertEqual(body["trial"]["vehiclesUsed"], 1)
        # Provklockan har inte startat: första telefonen startar den.
        self.assertIsNone(trial.started_at)

    def test_registering_twice_returns_the_same_company(self):
        user = str(uuid.uuid4())
        first = self.register(user, "ny@example.test").json()
        again = self.register(user, "ny@example.test")
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.json()["companyId"], first["companyId"])
        self.assertEqual(Company.objects.count(), 1)

    def test_an_existing_org_number_is_not_taken_over(self):
        self.make_company(org_number="5560360793")
        response = self.register(str(uuid.uuid4()), "ny@example.test")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["reason"], "company_exists")

    def test_a_blocked_email_cannot_register(self):
        accounts.block(kind="email", value="spam@example.test", reason="Spam", actor_user_id=self.admin_id)
        response = self.register(str(uuid.uuid4()), "spam@example.test")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Company.objects.count(), 0)

    def test_registration_requires_login(self):
        response = self.client.post(
            "/api/fleet/register", data=json.dumps({"orgNumber": "5560360793"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_an_admin_can_verify_a_self_registered_company(self):
        company_id = self.register(str(uuid.uuid4()), "ny@example.test").json()["companyId"]
        refused = self.call(
            "post", f"/api/admin/companies/{company_id}/verification", self.admin_id,
            {"status": "verified"},
        )
        self.assertEqual(refused.status_code, 400)
        response = self.call(
            "post", f"/api/admin/companies/{company_id}/verification", self.admin_id,
            {"status": "verified", "note": "Ringde växeln, bekräftat av VD"},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(CompanyProfile.objects.get(company_id=company_id).verification_status, "verified")


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class StaffTests(_Base):
    def test_a_role_is_given_by_email_once_the_account_has_logged_in(self):
        colleague = str(uuid.uuid4())
        response = self.call("post", "/api/admin/staff/set", self.admin_id, {
            "email": "saljare@example.test", "role": "sales",
        })
        self.assertEqual(response.status_code, 404)
        # Personen loggar in en gång (vilket anrop som helst med token).
        self.call("get", "/api/admin/overview", colleague, email="saljare@example.test")
        response = self.call("post", "/api/admin/staff/set", self.admin_id, {
            "email": "saljare@example.test", "role": "sales",
        })
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.call("get", "/api/admin/overview", colleague).status_code, 200)
        self.call("post", "/api/admin/staff/set", self.admin_id, {
            "email": "saljare@example.test", "role": "",
        })
        self.assertEqual(self.call("get", "/api/admin/overview", colleague).status_code, 403)


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class TrialVehicleTests(_Base):
    def test_an_owner_adds_trial_cars_up_to_the_limit_and_no_further(self):
        user = str(uuid.uuid4())
        self.call("post", "/api/fleet/register", user, {
            "orgNumber": "5560360793", "companyName": "Nya Taxi AB",
            "vehicles": [{"plate": "AAA111", "baseCounty": "12"}],
        }, email="ny@example.test")
        response = self.call("post", "/api/fleet/trial/vehicles", user, {
            "vehicles": [{"plate": "BBB222", "baseCounty": "12"}, {"plate": "CCC333", "baseCounty": "13"}],
        })
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["vehiclesUsed"], 3)
        refused = self.call("post", "/api/fleet/trial/vehicles", user, {
            "vehicles": [{"plate": "DDD444", "baseCounty": "12"}],
        })
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["reason"], "trial_vehicle_limit")
        overview = self.call("get", "/api/fleet/company", user).json()
        self.assertEqual(len(overview["licenses"]), 3)
        # Provbilarna finns, men provet har inte startat: ingen telefon än.
        self.assertFalse(overview["access"]["ok"])


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class LegacyCompanyOverviewTests(_Base):
    def test_opening_the_overview_does_not_lock_out_a_legacy_company(self):
        """
        Företagsöversikten skapar en tom abonnemangsrad. För ett företag från
        före licensmodellen fick det förarna att tappa åtkomsten (2026-09-24).
        """
        from fleet.models import Subscription

        company = self.make_company(status="active")
        owner = self.make_owner(company)
        self.assertEqual(access.company_window(company.id).reason, "legacy_company_status")
        overview = self.call("get", "/api/fleet/company", str(owner.user_id)).json()
        self.assertTrue(Subscription.objects.filter(company_id=company.id).exists())
        self.assertTrue(overview["access"]["ok"], overview["access"])
        self.assertTrue(access.company_window(company.id).ok)

    def test_an_inactive_legacy_company_stays_closed(self):
        company = self.make_company(status="inactive")
        owner = self.make_owner(company)
        self.call("get", "/api/fleet/company", str(owner.user_id))
        self.assertFalse(access.company_window(company.id).ok)


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class AdminVehicleTests(_Base):
    def trial_company(self):
        user = str(uuid.uuid4())
        self.call("post", "/api/fleet/register", user, {
            "orgNumber": "5560360793", "companyName": "Prov AB",
            "vehicles": [{"plate": "AAA111", "baseCounty": "12"}],
        }, email="prov@example.test")
        return License.objects.get()

    def test_a_trial_car_gets_new_plate_counties_and_can_be_removed(self):
        lic = self.trial_company()
        r = self.call("post", f"/api/admin/licenses/{lic.id}/vehicle", self.admin_id, {"plate": "bbb 222"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(r.json()["plate"], "BBB222")
        r = self.call("post", f"/api/admin/licenses/{lic.id}/counties", self.admin_id,
                      {"base": "13", "extras": ["12", "13"]})
        self.assertEqual(r.json(), {"ok": True, "base": "13", "extras": ["12"]})
        self.assertEqual(sorted(access.license_counties(lic.id)), ["12", "13"])
        self.assertEqual(self.call("post", f"/api/admin/licenses/{lic.id}/remove", self.admin_id, {}).status_code, 400)
        r = self.call("post", f"/api/admin/licenses/{lic.id}/remove", self.admin_id, {"reason": "Fel bil"})
        self.assertEqual(r.status_code, 200, r.content)
        lic.refresh_from_db()
        self.assertEqual(lic.status, License.Status.CANCELED)

    def test_a_paid_car_is_changed_through_the_order_not_directly(self):
        data = self.full_setup()
        lic = data["license"]
        r = self.call("post", f"/api/admin/licenses/{lic.id}/counties", self.admin_id, {"base": "13"})
        self.assertEqual(r.json()["reason"], "paid_license")
        sales_id = str(uuid.uuid4())
        StaffRole.objects.create(user_id=sales_id, role=StaffRole.Role.SALES)
        r = self.call("post", f"/api/admin/licenses/{lic.id}/remove", sales_id, {"reason": "x"})
        self.assertEqual(r.status_code, 403)

    def test_a_stripe_billed_car_is_not_removed_directly(self):
        from fleet.models import Subscription

        data = self.full_setup()
        Subscription.objects.filter(company_id=data["company"].id).update(stripe_subscription_id="sub_1")
        r = self.call("post", f"/api/admin/licenses/{data['license'].id}/remove", self.admin_id, {"reason": "x"})
        self.assertEqual(r.json()["reason"], "stripe_billed")
        r = self.call("post", f"/api/admin/licenses/{data['license'].id}/remove", self.admin_id, {"reason": "x"})
        Subscription.objects.filter(company_id=data["company"].id).update(stripe_subscription_id="")
        r = self.call("post", f"/api/admin/licenses/{data['license'].id}/remove", self.admin_id, {"reason": "Betalt utanför Stripe, kunden sålde bilen"})
        self.assertEqual(r.status_code, 200, r.content)
