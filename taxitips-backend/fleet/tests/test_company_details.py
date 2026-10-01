"""
Kundens egna uppgifter i kundportalen (fleet/company_details.py).

Det viktigaste: varje område kräver sin behörighet, mobilnumret prövas som
vid registreringen, och organisationsnummer/namn går inte att ändra här.
"""

from __future__ import annotations

import json

from django.test import Client, override_settings

from fleet import accounts
from fleet.models import AuditEvent, CompanyProfile
from fleet.tests.base import FleetTestCase
from fleet.tests.test_accounts import SECRET, jwt

PATH = "/api/fleet/company/details"


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class CompanyDetailsTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        accounts._seen_cache.clear()
        self.client = Client()
        self.company = self.make_company()
        self.owner = str(self.make_owner(self.company).user_id)

    def post(self, user_id, body):
        return self.client.post(
            PATH, data=json.dumps(body), content_type="application/json",
            headers={"authorization": f"Bearer {jwt(user_id)}"},
        )

    def profile(self):
        return CompanyProfile.objects.get(company_id=self.company.id)

    def test_owner_updates_contact_and_billing(self):
        response = self.post(self.owner, {
            "contactName": "Anna Ägare",
            "contactPhone": "073-948 15 62",
            "billingEmail": "faktura@taxibolag.se",
            "billingReference": "Anna",
            "billingAddress": {"line1": "Storgatan 1", "postalCode": "252 75", "city": "Helsingborg"},
        })
        self.assertEqual(response.status_code, 200, response.content)
        profile = self.profile()
        self.assertEqual(profile.contact_name, "Anna Ägare")
        self.assertEqual(profile.contact_phone, "+46739481562")
        self.assertEqual(profile.billing_email, "faktura@taxibolag.se")
        self.assertEqual(profile.billing_address["city"], "Helsingborg")
        self.assertEqual(profile.billing_address["country"], "SE")
        event = AuditEvent.objects.get(action="company_details_updated")
        self.assertIn("contact_phone", event.detail["fields"])
        # Uppgifterna syns i översikten som portalen läser.
        overview = self.client.get(
            "/api/fleet/company", headers={"authorization": f"Bearer {jwt(self.owner)}"},
        ).json()
        self.assertEqual(overview["company"]["details"]["contactName"], "Anna Ägare")
        self.assertEqual(overview["company"]["details"]["billingAddress"]["postalCode"], "252 75")

    def test_made_up_phone_is_rejected_with_the_field(self):
        response = self.post(self.owner, {"contactPhone": "0701234567"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["field"], "contactPhone")
        self.assertEqual(self.profile().contact_phone, "")

    def test_a_new_phone_is_not_verified(self):
        profile = self.profile()
        profile.contact_phone = "+46739481562"
        profile.phone_verified_at = profile.created_at if hasattr(profile, "created_at") else None
        profile.save()
        self.post(self.owner, {"contactPhone": "0739 481 563"})
        self.assertIsNone(self.profile().phone_verified_at)

    def test_finance_can_change_billing_but_not_contact(self):
        finance = str(self.make_owner(self.company, role="finance").user_id)
        ok = self.post(finance, {"billingReference": "Ekonomi"})
        self.assertEqual(ok.status_code, 200, ok.content)
        denied = self.post(finance, {"contactName": "Någon annan"})
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.profile().contact_name, "")

    def test_fleet_admin_cannot_change_anything(self):
        admin = str(self.make_owner(self.company, role="fleet_admin").user_id)
        self.assertEqual(self.post(admin, {"billingReference": "x"}).status_code, 403)
        self.assertEqual(self.post(admin, {"contactName": "x"}).status_code, 403)

    def test_org_number_and_name_are_not_editable_here(self):
        before = self.profile()
        response = self.post(self.owner, {"orgNumber": "5590000000", "companyName": "Annat AB"})
        self.assertEqual(response.status_code, 400)
        after = self.profile()
        self.assertEqual(after.org_number, before.org_number)
        self.assertEqual(after.legal_name, before.legal_name)

    def test_bad_billing_values_point_at_the_field(self):
        response = self.post(self.owner, {"billingEmail": "inte-en-adress"})
        self.assertEqual(response.json()["detail"]["field"], "billingEmail")
        response = self.post(self.owner, {"billingAddress": {"line1": "Gatan 1", "postalCode": "12", "city": "Ort"}})
        self.assertEqual(response.json()["detail"]["field"], "billingAddress")

    def test_requires_login(self):
        response = self.client.post(PATH, data="{}", content_type="application/json")
        self.assertEqual(response.status_code, 401)
