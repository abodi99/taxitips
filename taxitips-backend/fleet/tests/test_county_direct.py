"""
Direkt länbyte för ALLA platser (ägarens beslut 2026-11-10) och admins
"Ny kund" utan organisationsnummer.

Priset är detsamma oavsett län, så en betald plats byter län direkt: ingen
beställning, inget Stripe-anrop. Två byten per plats och kalendermånad gäller
för prov och betalt.
"""

from __future__ import annotations

import uuid
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from billing.models import Company
from fleet import county_changes
from fleet.models import (
    AuditEvent,
    CompanyProfile,
    CountyChange,
    License,
    LicenseCounty,
    Order,
    PendingChange,
    StaffRole,
    Trial,
)
from fleet.tests.test_county_changes import _ApiCase
from fleet.tests.test_sales import ORG, SalesTestCase
from fleet.tests.test_admin import SECRET as ADMIN_SECRET
from fleet.tests.test_support import SECRET


def _no_stripe():
    """Stripe får inte röras av ett länbyte: varje anrop fäller testet."""
    return mock.patch(
        "fleet.stripe_sync.available", side_effect=AssertionError("Stripe anropades"),
    )


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class PaidSeatDirectChangeTests(_ApiCase):
    def setUp(self):
        super().setUp()
        self.data = self.full_setup(county="12", plate="BET001")
        self.license = self.data["license"]
        self.owner = str(self.data["owner"].user_id)
        self.assertEqual(self.license.status, License.Status.ACTIVE)

    def change(self, county, **extra):
        return self.post(
            f"/api/fleet/memberships/{self.license.id}/county", {"base": county, **extra},
        )

    def test_a_paid_seat_changes_county_now_without_an_order_or_stripe(self):
        orders_before = Order.objects.count()
        with _no_stripe():
            response = self.change("01")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual((body["ok"], body["base"], body["extras"]), (True, "01", []))
        self.assertEqual(body["membership"]["baseCounty"], "01")
        self.assertEqual(Order.objects.count(), orders_before)
        self.license.refresh_from_db()
        self.assertEqual(self.license.base_county, "01")
        self.assertEqual(self.active(self.license), [("base", "01")])
        ended = LicenseCounty.objects.get(license=self.license, county_code="12", kind="base")
        self.assertIsNotNone(ended.active_to)
        row = CountyChange.objects.get(license_id=self.license.id)
        self.assertEqual((row.via, row.from_county, row.to_county), ("direct", "12", "01"))
        self.assertTrue(AuditEvent.objects.filter(action="seat_county_changed").exists())

    def test_the_trial_vehicle_route_also_changes_a_paid_seat(self):
        response = self.trial_county(self.license, "14")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["base"], "14")
        self.assertTrue(response.json()["counted"])

    def test_two_changes_a_month_then_the_limit_and_an_admin_grant_gives_one_more(self):
        self.assertEqual(self.change("01").status_code, 200)
        self.assertEqual(self.change("14").status_code, 200)
        refused = self.change("03")
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(refused.json()["reason"], "county_change_limit")
        self.assertIn("plats", refused.json()["message"].lower())

        county_changes.grant_extra_change(self.license, actor_user_id=uuid.uuid4())
        self.assertEqual(self.change("03").status_code, 200)
        self.assertEqual(self.change("12").status_code, 403)

    def test_the_same_county_is_a_no_op_that_costs_no_change(self):
        response = self.change("12")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(county_changes.summary_for(self.license.id)["used"], 0)
        self.assertEqual(CountyChange.objects.count(), 0)
        self.assertEqual(self.active(self.license), [("base", "12")])

    def test_a_pending_base_change_from_the_old_flow_is_cancelled(self):
        License.objects.filter(id=self.license.id).update(scheduled_base_county="14")
        pending = PendingChange.objects.create(
            company_id=self.license.company_id, kind=PendingChange.Kind.CHANGE_BASE_COUNTY,
            payload={"licenseId": str(self.license.id), "county": "14"},
            effective_at=timezone.now(),
        )
        self.assertEqual(self.change("01").status_code, 200)
        pending.refresh_from_db()
        self.assertEqual(pending.status, PendingChange.Status.SUPERSEDED)
        self.license.refresh_from_db()
        self.assertEqual((self.license.base_county, self.license.scheduled_base_county), ("01", ""))

    def test_extra_county_rows_are_left_alone(self):
        LicenseCounty.objects.create(
            license=self.license, county_code="14", kind=LicenseCounty.Kind.EXTRA,
            active_from=self.license.created_at,
        )
        self.assertEqual(self.change("01").status_code, 200)
        self.assertEqual(self.active(self.license), [("base", "01"), ("extra", "14")])
        # Samma län som ett extra län går inte: man betalade för det redan.
        refused = self.change("14")
        self.assertEqual(refused.status_code, 400, refused.content)
        self.assertEqual(refused.json()["reason"], "county_already_extra")
        self.assertIn("extra län", refused.json()["message"])
        self.assertEqual(self.active(self.license), [("base", "01"), ("extra", "14")])

    def test_adding_extra_counties_is_refused(self):
        refused = self.change("12", extras=["01"])
        self.assertEqual(refused.json()["reason"], "extra_counties_not_sold")

    def test_the_old_order_route_still_works_and_is_replaced_by_a_direct_change(self):
        order = self.post("/api/fleet/orders", {
            "accepted": True,
            "baseCountyChanges": [{"licenseId": str(self.license.id), "county": "14"}],
        })
        self.assertEqual(order.status_code, 200, order.content)
        self.license.refresh_from_db()
        self.assertEqual(self.license.scheduled_base_county, "14")
        self.assertEqual(self.change("01").status_code, 200)
        self.license.refresh_from_db()
        self.assertEqual((self.license.base_county, self.license.scheduled_base_county), ("01", ""))

    def test_a_canceled_seat_cannot_change(self):
        License.objects.filter(id=self.license.id).update(status=License.Status.CANCELED)
        self.assertEqual(self.change("01").status_code, 400)


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class TrialSeatResponseShapeTests(_ApiCase):
    def test_a_trial_seat_keeps_the_same_response_shape(self):
        data = self.full_setup(county="01", plate="PROV01")
        License.objects.filter(id=data["license"].id).update(status=License.Status.TRIAL)
        self.owner = str(data["owner"].user_id)
        lic = License.objects.get(id=data["license"].id)

        direct = self.post(f"/api/fleet/trial/vehicles/{lic.id}/county", {"base": "12"}).json()
        self.assertEqual(set(direct), {"ok", "base", "extras", "counted", "countyChanges"})
        self.assertEqual(direct["countyChanges"]["remaining"], 1)

        member = self.post(f"/api/fleet/memberships/{lic.id}/county", {"base": "14"}).json()
        self.assertEqual(set(member), {"ok", "base", "extras", "membership"})
        self.assertEqual(member["base"], "14")
        self.assertTrue(member["membership"]["trial"])
        self.assertTrue(AuditEvent.objects.filter(action="trial_counties_set").exists())


@override_settings(SUPABASE_JWT_SECRET=ADMIN_SECRET)
class AdminNewCustomerWithoutOrgNumberTests(SalesTestCase):
    MINIMAL = {
        "name": "Anderssons Taxi", "contactName": "Anna Andersson",
        "contactEmail": "anna@anderssons.test", "contactPhone": "070-123 45 67",
    }

    def create_minimal(self, **overrides):
        return self.post("/api/admin/companies/new", {**self.MINIMAL, **overrides})

    def test_a_customer_with_only_contact_details_gets_a_trial_with_seats_and_no_vehicles(self):
        response = self.create_minimal()
        self.assertEqual(response.status_code, 200, response.content)
        company = Company.objects.get(id=response.json()["companyId"])
        self.assertFalse(company.org_number)
        profile = CompanyProfile.objects.get(company_id=company.id)
        self.assertEqual(profile.org_number, "")

        trial = self.post(f"/api/admin/companies/{company.id}/trial", {
            "vehicles": [{"plate": "", "baseCounty": "14"}, {"plate": "", "baseCounty": "14"}],
        })
        self.assertEqual(trial.status_code, 200, trial.content)
        licenses = License.objects.filter(company_id=company.id)
        self.assertEqual(licenses.count(), 2)
        self.assertEqual({lic.base_county for lic in licenses}, {"14"})
        self.assertEqual({lic.status for lic in licenses}, {License.Status.TRIAL})
        self.assertFalse(any(lic.assignments.exists() for lic in licenses))
        row = Trial.objects.get(company_id=company.id)
        self.assertEqual(row.org_key, "CONTACT:anna@anderssons.test")
        self.assertEqual(row.vehicle_limit, 2)

    def test_the_contact_email_allows_only_one_trial(self):
        first = self.create_minimal()
        company = Company.objects.get(id=first.json()["companyId"])
        self.post(f"/api/admin/companies/{company.id}/trial", {"vehicles": [{"plate": "", "baseCounty": "14"}]})
        Trial.objects.filter(company_id=company.id).update(status=Trial.Status.ACTIVE)
        other = self.create_minimal(name="Annat namn", contactPhone="073-987 65 43")
        other_company = Company.objects.get(id=other.json()["companyId"])
        again = self.post(
            f"/api/admin/companies/{other_company.id}/trial",
            {"vehicles": [{"plate": "", "baseCounty": "14"}]},
        )
        self.assertEqual(again.status_code, 400, again.content)
        self.assertEqual(again.json()["reason"], "trial_in_progress")

    def test_the_phone_number_cannot_start_a_second_trial_in_another_company(self):
        first = self.create_minimal()
        company = Company.objects.get(id=first.json()["companyId"])
        self.post(f"/api/admin/companies/{company.id}/trial", {"vehicles": [{"plate": "", "baseCounty": "14"}]})
        other = self.create_minimal(name="Annat", contactEmail="annan@anderssons.test")
        other_company = Company.objects.get(id=other.json()["companyId"])
        again = self.post(
            f"/api/admin/companies/{other_company.id}/trial",
            {"vehicles": [{"plate": "", "baseCounty": "14"}]},
        )
        self.assertEqual(again.json()["reason"], "phone_in_use")

    def test_with_an_org_number_the_registry_checks_still_run_and_the_note_is_required(self):
        with mock.patch("fleet.bolagsverket.try_lookup", return_value=None) as lookup:
            no_note = self.create_minimal(orgNumber=ORG)
            self.assertEqual(no_note.status_code, 400)
            self.assertEqual(no_note.json()["reason"], "verification_note_required")
            ok = self.create_minimal(orgNumber=ORG, verificationNote="Ringde växeln.")
            self.assertEqual(ok.status_code, 200, ok.content)
            lookup.assert_called()
            dup = self.create_minimal(orgNumber=ORG, verificationNote="Igen.", contactEmail="x@y.test")
            self.assertEqual(dup.json()["reason"], "company_exists")
        invalid = self.create_minimal(orgNumber="123", verificationNote="x")
        self.assertEqual(invalid.json()["reason"], "invalid_org_number")

    def test_extra_counties_are_refused_for_a_new_trial(self):
        company = Company.objects.get(id=self.create_minimal().json()["companyId"])
        response = self.post(f"/api/admin/companies/{company.id}/trial", {
            "vehicles": [{"plate": "", "baseCounty": "14", "extraCounties": ["01"]}],
        })
        self.assertEqual(response.json()["reason"], "extra_counties_not_sold")

    def test_an_admin_order_needs_the_org_number_first(self):
        company = Company.objects.get(id=self.create_minimal().json()["companyId"])
        order = self.post(f"/api/admin/companies/{company.id}/orders", {
            "accepted": True, "addVehicles": [{"plate": "", "baseCounty": "14"}],
        })
        self.assertEqual(order.status_code, 409, order.content)
        self.assertEqual(order.json()["reason"], "company_details_required")

    def test_the_org_number_can_be_added_by_sales_afterwards(self):
        company = Company.objects.get(id=self.create_minimal().json()["companyId"])
        with mock.patch("fleet.bolagsverket.try_lookup", return_value=None):
            response = self.post(
                f"/api/admin/companies/{company.id}/org-number",
                {"orgNumber": ORG, "legalName": "Anderssons Taxi AB"},
            )
        self.assertEqual(response.status_code, 200, response.content)
        company.refresh_from_db()
        self.assertTrue(company.org_number)
        again = self.post(f"/api/admin/companies/{company.id}/org-number", {"orgNumber": ORG})
        self.assertEqual(again.json()["reason"], "org_number_set")
