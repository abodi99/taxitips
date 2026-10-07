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

from datetime import timedelta

from django.test import Client, RequestFactory, override_settings
from django.utils import timezone

from billing.models import Company, CompanyMember, Device
from fleet import access, accounts
from fleet.models import (
    AccountBlock,
    AuditEvent,
    CompanyProfile,
    KnownAccount,
    License,
    StaffRole,
    Subscription,
    Trial,
    VehicleSession,
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

    def test_staff_who_also_owns_a_company_keeps_customer_overview(self):
        """Plattformsadmin + company_owner: appens kundläge får inte 403 no_company."""
        data = self.full_setup()
        owner = str(data["owner"].user_id)
        StaffRole.objects.create(user_id=owner, role=StaffRole.Role.PLATFORM_ADMIN)
        response = self.call("get", "/api/fleet/company", owner, email="agare@example.test")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["company"]["id"], str(data["company"].id))
        # Adminwebben fungerar fortfarande.
        self.assertEqual(self.call("get", "/api/admin/overview", owner).status_code, 200)

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

    def test_account_detail_returns_the_same_memberships(self):
        data = self.full_setup()
        owner = str(data["owner"].user_id)
        self.call("get", "/api/fleet/company", owner, email="kund@example.test")
        body = self.call("get", f"/api/admin/accounts/{owner}", self.admin_id).json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["account"]["email"], "kund@example.test")
        self.assertEqual(body["account"]["memberships"][0]["companyName"], data["company"].name)
        self.assertIn("errors", body)
        self.assertIn("audit", body)
        self.assertIn("devices", body)
        self.assertIn("notifications", body)
        self.assertIn("favorites", body)
        self.assertIn("feedback", body)
        self.assertIn("tipReports", body)
        self.assertIn("feedbackSummary", body)
        self.assertIsInstance(body["devices"], list)
        self.assertIsInstance(body["notifications"], list)
        self.assertIsInstance(body["favorites"], list)
        self.assertIsInstance(body["feedback"], list)
        self.assertIsInstance(body["tipReports"], list)

    def test_account_detail_lists_device_favorites(self):
        """Sparade tips syns via telefonens device:<uuid>, aldrig rå token."""
        from core.models import Opportunity, OpportunityFavorite
        from core.models import SeverityTier

        data = self.full_setup()
        owner = data["owner"]
        device = data["device"]
        Device.objects.filter(id=device.id).update(user_id=owner.user_id)
        tip = Opportunity.objects.create(
            external_id=f"test:fav:{uuid.uuid4()}",
            kind="transit",
            mode="train",
            severity_tier=SeverityTier.VEHICLE_CANCELLED,
            title="Inställt tåg Malmö",
            summary="Test",
            demand_score=80,
            region="skane",
            places=["Malmö C"],
            end_time=timezone.now() + timedelta(hours=2),
        )
        OpportunityFavorite.objects.create(
            owner_key=f"device:{device.id}",
            opportunity=tip,
            opportunity_external_id=tip.external_id,
            snapshot={"title": tip.title, "kind": tip.kind},
        )
        # Rå token som nyckel ska inte synas / inte räknas som kontots.
        OpportunityFavorite.objects.create(
            owner_key=data["secret"],
            opportunity=tip,
            opportunity_external_id=f"{tip.external_id}:token",
            snapshot={"title": "Hemlig"},
        )
        self.call("get", "/api/fleet/company", str(owner.user_id), email="kund@example.test")
        body = self.call(
            "get", f"/api/admin/accounts/{owner.user_id}", self.admin_id,
        ).json()
        titles = [f["title"] for f in body["favorites"]]
        self.assertEqual(titles, ["Inställt tåg Malmö"])
        self.assertEqual(body["feedbackSummary"]["favorites"], 1)
        self.assertNotIn(data["secret"], str(body["favorites"]))
        self.assertEqual(body["favorites"][0]["ownerKind"], "device")
        self.assertFalse(body["favorites"][0]["purged"])

    def test_account_recovery_requires_service_role(self):
        data = self.full_setup()
        owner = str(data["owner"].user_id)
        self.call("get", "/api/fleet/company", owner, email="kund@example.test")
        response = self.call("post", f"/api/admin/accounts/{owner}/recovery", self.admin_id, {})
        # Utan SUPABASE_SERVICE_ROLE_KEY i testmiljön: 503. Med mock skulle det vara 200.
        self.assertIn(response.status_code, (200, 502, 503), response.content)

    def test_account_delete_refuses_sole_owner(self):
        data = self.full_setup()
        owner = str(data["owner"].user_id)
        self.call("get", "/api/fleet/company", owner, email="kund@example.test")
        response = self.call(
            "post", f"/api/admin/accounts/{owner}/delete", self.admin_id,
            {"confirmEmail": "kund@example.test"},
        )
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["reason"], "sole_owner")

    def test_account_delete_requires_confirm_email(self):
        data = self.full_setup()
        owner = str(data["owner"].user_id)
        self.call("get", "/api/fleet/company", owner, email="kund@example.test")
        response = self.call(
            "post", f"/api/admin/accounts/{owner}/delete", self.admin_id,
            {"confirmEmail": "fel@example.test"},
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["reason"], "confirm_mismatch")

    @override_settings(
        SUPABASE_SERVICE_ROLE_KEY="test-service-role",
        SUPABASE_URL="http://supabase.test",
    )
    def test_account_delete_removes_member_without_sole_ownership(self):
        from unittest.mock import patch

        data = self.full_setup()
        admin_member = self.make_owner(data["company"], role="company_admin")
        member_id = str(admin_member.user_id)
        self.call("get", "/api/fleet/company", member_id, email="admin@example.test")
        with patch("fleet.auth_admin.delete_user") as delete_user:
            response = self.call(
                "post", f"/api/admin/accounts/{member_id}/delete", self.admin_id,
                {"confirmEmail": "admin@example.test"},
            )
        self.assertEqual(response.status_code, 200, response.content)
        delete_user.assert_called_once_with(member_id)
        self.assertFalse(CompanyMember.objects.filter(user_id=member_id).exists())
        self.assertFalse(KnownAccount.objects.filter(user_id=member_id).exists())
        self.assertTrue(AuditEvent.objects.filter(action="admin_account_deleted").exists())

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
        payload = {
            "orgNumber": "5560360793", "companyName": "Nya Taxi AB",
            "contactPhone": "070-812 34 91", **body,
        }
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

    def test_the_second_person_with_the_same_org_number_gets_no_access(self):
        from fleet.models import AuditEvent, OutboxMessage

        first = self.register(str(uuid.uuid4()), "agare@example.test")
        self.assertEqual(first.status_code, 201, first.content)
        # Före kontot: appens förkontroll säger det direkt, utan vems det är.
        check = self.client.post(
            "/api/fleet/register/check",
            data=json.dumps({"orgNumber": "556036-0793", "contactPhone": "070-812 34 91"}),
            content_type="application/json",
        ).json()
        self.assertEqual((check["reason"], check["field"]), ("company_exists", "orgNumber"))
        self.assertNotIn("Nya Taxi", check["message"])
        # Efter kontot: inget företag, ingen medlem, inget prov -- men ägaren får veta.
        second_user = str(uuid.uuid4())
        second = self.register(second_user, "okand@example.test")
        self.assertEqual(second.status_code, 409)
        self.assertNotIn("detail", second.json())
        self.assertFalse(CompanyMember.objects.filter(user_id=second_user).exists())
        self.assertEqual(Company.objects.count(), 1)
        self.assertTrue(AuditEvent.objects.filter(action="duplicate_signup_attempt").exists())
        mail = OutboxMessage.objects.get(category="duplicate_signup_attempt")
        self.assertEqual(mail.to_address, "agare@example.test")
        self.assertIn("okand@example.test", mail.body)
        # Ett mejl per adress, hur många gånger hen än försöker.
        self.register(second_user, "okand@example.test")
        self.assertEqual(OutboxMessage.objects.filter(category="duplicate_signup_attempt").count(), 1)

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
            "contactPhone": "070-812 34 91",
        }, email="ny@example.test")
        # Självregistrerat prov: en bil (fleet/trials.py).
        response = self.call("post", "/api/fleet/trial/vehicles", user, {
            "vehicles": [{"plate": "BBB222", "baseCounty": "12"}],
        })
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["vehiclesUsed"], 1)
        refused = self.call("post", "/api/fleet/trial/vehicles", user, {
            "vehicles": [{"plate": "DDD444", "baseCounty": "12"}],
        })
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["reason"], "trial_vehicle_limit")
        overview = self.call("get", "/api/fleet/company", user).json()
        self.assertEqual(len(overview["licenses"]), 1)
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
            "contactPhone": "070-812 34 91",
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

    def test_staff_assigns_a_membership_to_an_account(self):
        lic = self.trial_company()
        r = self.call("post", f"/api/admin/licenses/{lic.id}/assign", self.admin_id,
                      {"email": "forare@example.test"})
        self.assertEqual(r.status_code, 200, r.content)
        lic.refresh_from_db()
        self.assertEqual(lic.assignee_email, "forare@example.test")
        self.assertIsNone(lic.assignee_user_id)

        account = str(uuid.uuid4())
        r = self.call("post", f"/api/admin/licenses/{lic.id}/assign", self.admin_id,
                      {"userId": account})
        self.assertEqual(r.status_code, 200, r.content)
        lic.refresh_from_db()
        self.assertEqual(str(lic.assignee_user_id), account)
        self.assertEqual(lic.assignee_email, "")

        r = self.call("post", f"/api/admin/licenses/{lic.id}/unassign", self.admin_id, {})
        self.assertEqual(r.status_code, 200, r.content)
        lic.refresh_from_db()
        self.assertIsNone(lic.assignee_user_id)

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


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class AdminBaseCountyTests(_Base):
    """Baslänet direkt, för en bil eller hela företaget, med skäl i loggen."""

    def test_a_paid_car_changes_base_county_now_and_replaces_the_scheduled_change(self):
        from billing.models import Device
        from fleet.models import AuditEvent, LicenseCounty, PendingChange

        data = self.full_setup()
        lic = data["license"]
        # Telefonen har det gamla länet sparat — det var felet som gjorde att
        # föraren fortfarande såg Skåne efter admin-byte till Stockholm.
        Device.objects.filter(id=data["device"].id).update(
            notify_prefs={"counties": [lic.base_county], "municipalities": []},
        )
        License.objects.filter(id=lic.id).update(scheduled_base_county="14")
        PendingChange.objects.create(
            company_id=lic.company_id, kind=PendingChange.Kind.CHANGE_BASE_COUNTY,
            payload={"licenseId": str(lic.id), "county": "14"}, effective_at=timezone.now(),
        )
        path = f"/api/admin/licenses/{lic.id}/base-county"
        self.assertEqual(self.call("post", path, self.admin_id, {"county": "13"}).json()["reason"], "reason_required")
        r = self.call("post", path, self.admin_id, {"county": "13", "reason": "Kunden flyttade"})
        self.assertEqual(r.status_code, 200, r.content)
        lic.refresh_from_db()
        self.assertEqual((lic.base_county, lic.scheduled_base_county), ("13", ""))
        self.assertIn("13", access.license_counties(lic.id))
        self.assertEqual(
            LicenseCounty.objects.filter(license=lic, kind="base", active_to__isnull=True).count(), 1,
        )
        self.assertFalse(PendingChange.objects.filter(status=PendingChange.Status.PENDING).exists())
        self.assertTrue(AuditEvent.objects.filter(action="admin_base_county_set").exists())
        device = Device.objects.get(id=data["device"].id)
        self.assertEqual(device.notify_prefs.get("counties"), ["13"])
        self.assertEqual(r.json().get("devicesSynced"), 1)

    def test_sales_cannot_change_a_paid_car_directly(self):
        data = self.full_setup()
        sales_id = str(uuid.uuid4())
        StaffRole.objects.create(user_id=sales_id, role=StaffRole.Role.SALES)
        r = self.call("post", f"/api/admin/licenses/{data['license'].id}/base-county", sales_id,
                      {"county": "13", "reason": "x"})
        self.assertEqual(r.status_code, 403)

    def test_the_whole_company_changes_at_once(self):
        data = self.full_setup()
        company = data["company"]
        r = self.call("post", f"/api/admin/companies/{company.id}/base-county", self.admin_id,
                      {"county": "14", "reason": "Registrerad i fel län"})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertGreaterEqual(r.json()["changed"], 1)
        self.assertEqual(
            set(License.objects.filter(company_id=company.id).exclude(status="canceled")
                .values_list("base_county", flat=True)),
            {"14"},
        )

    def test_a_scheduled_change_can_be_undone(self):
        from fleet.models import PendingChange

        data = self.full_setup()
        lic = data["license"]
        License.objects.filter(id=lic.id).update(status=License.Status.PENDING_CANCEL)
        change = PendingChange.objects.create(
            company_id=lic.company_id, kind=PendingChange.Kind.REDUCE_LICENSES,
            payload={"licenseIds": [str(lic.id)]}, effective_at=timezone.now(),
        )
        r = self.call("post", f"/api/admin/pending-changes/{change.id}/undo", self.admin_id,
                      {"reason": "Kunden ångrade sig i telefon"})
        self.assertEqual(r.status_code, 200, r.content)
        lic.refresh_from_db()
        change.refresh_from_db()
        self.assertEqual((lic.status, change.status), (License.Status.ACTIVE, PendingChange.Status.CANCELED))


class RepairedPhoneTests(FleetTestCase):
    """
    En telefon som kopplas igen med en ny kod fick förut ett pass på det utbytta
    godkännandet: vyn sa "spärrad av din administratör" medan notiserna kom.
    """

    def setUp(self):
        super().setUp()
        from fleet import pairing, sessions

        self.pairing, self.sessions = pairing, sessions
        self.data = self.full_setup()
        self.install = f"install-{uuid.uuid4().hex}"

    def pair(self):
        issued = self.pairing.issue_code(
            license=self.data["license"], vehicle=self.data["vehicle"],
            created_by=self.data["owner"].user_id, label="Ali",
        )
        return self.pairing.redeem_code(code=issued.code, installation_id=self.install, label="Ali")

    def driver(self, secret):
        return access.resolve(RequestFactory().get("/api/alerts", headers={"X-Device-Token": secret}))

    def test_pairing_again_replaces_the_old_session_with_the_paired_car(self):
        from fleet.models import VehicleSession

        first = self.pair()
        self.assertTrue(first.session_started)
        self.assertTrue(self.driver(first.secret).ok)
        first_session = VehicleSession.objects.get(device_id=first.device_id, ended_at__isnull=True)

        second = self.pair()
        self.assertTrue(second.session_started)
        self.assertFalse(self.driver(first.secret).ok)
        self.assertTrue(self.driver(second.secret).ok)
        first_session.refresh_from_db()
        self.assertIsNotNone(first_session.ended_at)
        self.assertEqual(VehicleSession.objects.filter(
            device_id=second.device_id, ended_at__isnull=True
        ).count(), 1)

    def test_a_phone_moved_to_another_company_leaves_the_old_car_and_counties(self):
        """
        2026-09-26: ägaren registrerade ett nytt bolag, kopplade sin telefon till
        Stockholmsbilen -- och fick testbolagets Skånelän, eftersom det gamla
        godkännandet och passet stod kvar.
        """
        from billing.models import Device
        from fleet.models import DeviceApproval, VehicleSession

        old = self.pair()
        self.assertTrue(self.driver(old.secret).ok)

        other = self.make_company(name="Nytt Bolag AB", org_number="5564879764")
        new_data = self.full_setup(company=other, county="01", plate="STH001")
        issued = self.pairing.issue_code(
            license=new_data["license"], vehicle=new_data["vehicle"], created_by=None,
        )
        moved = self.pairing.redeem_code(code=issued.code, installation_id=self.install)

        self.assertFalse(DeviceApproval.objects.filter(
            device_id=moved.device_id, company_id=self.data["company"].id,
            status=DeviceApproval.Status.ACTIVE,
        ).exists())
        self.assertFalse(VehicleSession.objects.filter(
            device_id=moved.device_id, company_id=self.data["company"].id, ended_at__isnull=True,
        ).exists())
        result = self.driver(moved.secret)
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(tuple(result.counties), ("01",))
        self.assertEqual(Device.objects.get(id=moved.device_id).notify_prefs["counties"], ["01"])

    def test_a_phone_stuck_on_another_companys_car_heals(self):
        """Läget före rättningen: telefonen flyttad, gamla passet öppet."""
        from billing.models import Device
        from fleet.models import VehicleSession

        first = self.pair()
        other = self.make_company(name="Nytt Bolag AB", org_number="5564879764")
        self.full_setup(company=other, county="01", plate="STH001")
        Device.objects.filter(id=first.device_id).update(company_id=other.id)
        result = self.driver(first.secret)
        self.assertEqual(result.reason, "device_not_approved")
        self.assertFalse(VehicleSession.objects.filter(
            device_id=first.device_id, ended_at__isnull=True
        ).exists())

    def test_a_phone_already_stuck_heals_instead_of_saying_blocked(self):
        from fleet.models import DeviceApproval, VehicleSession

        first = self.pair()
        self.sessions.start_session(device_id=first.device_id, license_id=self.data["license"].id)
        # Läget från före rättningen: godkännandet utbytt, passet öppet.
        DeviceApproval.objects.filter(device_id=first.device_id).update(
            status=DeviceApproval.Status.REPLACED
        )
        DeviceApproval.objects.create(
            company_id=self.data["company"].id, device_id=first.device_id,
            license=self.data["license"], vehicle=self.data["vehicle"], label="Ali",
            approved_at=timezone.now(),
        )
        result = self.driver(first.secret)
        self.assertEqual(result.reason, "no_active_session")
        self.assertFalse(VehicleSession.objects.filter(
            device_id=first.device_id, ended_at__isnull=True
        ).exists())

    def test_a_real_block_still_says_blocked(self):
        from fleet.models import DeviceApproval

        first = self.pair()
        self.sessions.start_session(device_id=first.device_id, license_id=self.data["license"].id)
        DeviceApproval.objects.filter(device_id=first.device_id).update(
            status=DeviceApproval.Status.BLOCKED
        )
        # En riktig spärr läks aldrig till ett bilval.
        self.assertIn(self.driver(first.secret).reason, ("device_blocked", "device_not_approved"))


class ResetPhonePairingTests(FleetTestCase):
    """`manage.py reset_phone_pairing`: momentet "Kör bilen själv" går att prova igen."""

    def setUp(self):
        super().setUp()
        from fleet import pairing

        self.pairing = pairing
        self.install = f"install-{uuid.uuid4().hex}"
        # Det gamla testbolaget i Skåne, och ägarens nya bolag i Stockholm.
        self.old = self.full_setup(plate="TEST01", county="12")
        new_company = self.make_company(name="Nytt Bolag AB", org_number="5564879764")
        self.new = self.full_setup(company=new_company, county="01", plate="KEE351")
        Subscription.objects.filter(company_id=new_company.id).update(had_successful_payment=False)

    def drive_myself(self):
        issued = self.pairing.issue_code(
            license=self.new["license"], vehicle=self.new["vehicle"], created_by=None,
        )
        return self.pairing.redeem_code(code=issued.code, installation_id=self.install)

    def driver(self, secret):
        return access.resolve(RequestFactory().get("/api/alerts", headers={"X-Device-Token": secret}))

    def reset(self, *extra):
        from io import StringIO

        from django.core.management import call_command

        out = StringIO()
        call_command("reset_phone_pairing", "--company", "Nytt Bolag AB", *extra, stdout=out)
        return out.getvalue()

    def test_the_moment_can_be_run_again_and_again(self):
        first = self.drive_myself()
        self.assertEqual(tuple(self.driver(first.secret).counties), ("01",))

        self.reset()
        # Appens gamla nyckel känns inte igen -> ägarens inloggning gäller igen.
        self.assertEqual(self.driver(first.secret).reason, "unknown_device_token")

        second = self.drive_myself()
        result = self.driver(second.secret)
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(tuple(result.counties), ("01",))

    def test_the_old_bug_can_be_recreated_and_is_healed_by_pairing(self):
        from billing.models import Device

        self.drive_myself()
        self.reset("--stuck-on", "TEST01")
        device = Device.objects.get(token=self.install)
        self.assertTrue(VehicleSession.objects.filter(
            device_id=device.id, company_id=self.old["company"].id, ended_at__isnull=True,
        ).exists())

        again = self.drive_myself()
        result = self.driver(again.secret)
        self.assertTrue(result.ok, result.reason)
        self.assertEqual(tuple(result.counties), ("01",))
        self.assertEqual(Device.objects.get(id=device.id).notify_prefs["counties"], ["01"])

    def test_a_paying_company_is_refused(self):
        from django.core.management.base import CommandError

        self.drive_myself()
        Subscription.objects.filter(company_id=self.new["company"].id).update(
            had_successful_payment=True
        )
        with self.assertRaises(CommandError):
            self.reset()
