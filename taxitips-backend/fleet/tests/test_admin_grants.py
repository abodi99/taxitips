"""
Adminwebbens vägar för beviljanden och personbaserade medlemskap
(fleet/admin_api.py).

Gränsen som vaktas: att ge någon allt utan betalning är ADMIN_MANAGE -- en
säljare får sälja, men aldrig flytta rättigheter utan pengar (samma gräns som
kuponger och direkt avslut, fleet/roles.py). Och att varje anrop lämnar spår.
"""

from __future__ import annotations

import json
import uuid

from django.test import Client, override_settings

from fleet.models import (
    AuditEvent,
    License,
    MembershipGrant,
    StaffRole,
    VehicleAssignment,
)
from fleet.tests.base import FleetTestCase
# jwt() och SECRET hör ihop: hjälpfunktionen signerar med sin egen fils
# hemlighet, så båda importeras från test_admin (override_settings nedan
# sätter samma hemlighet som verify_supabase_jwt läser).
from fleet.tests.test_admin import SECRET, jwt


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class AdminGrantEndpointTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.data = self.full_setup(county="12")
        self.company = self.data["company"]
        self.admin_id = str(uuid.uuid4())
        StaffRole.objects.create(user_id=self.admin_id, role=StaffRole.Role.PLATFORM_ADMIN)
        self.sales_id = str(uuid.uuid4())
        StaffRole.objects.create(user_id=self.sales_id, role=StaffRole.Role.SALES)

    def post(self, path, user_id, body, aal="aal1"):
        return self.client.post(
            path, data=json.dumps(body), content_type="application/json",
            headers={"authorization": f"Bearer {jwt(user_id, aal)}"},
        )

    def get(self, path, user_id):
        return self.client.get(path, headers={"authorization": f"Bearer {jwt(user_id)}"})

    def test_platform_admin_grants_and_the_detail_carries_the_grant(self):
        person = str(uuid.uuid4())
        r = self.post(
            f"/api/admin/companies/{self.company.id}/grant", self.admin_id,
            {"userId": person, "reason": "Avtal med branschorganisation", "endsAt": "2027-01-01"},
        )
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()["grant"]
        self.assertEqual(body["userId"], person)
        self.assertTrue(body["allCounties"])
        self.assertTrue(body["active"])
        self.assertTrue(body["licenseCreated"])

        detail = self.get(f"/api/admin/companies/{self.company.id}", self.admin_id).json()
        self.assertEqual([g["id"] for g in detail["grants"]], [body["id"]])
        self.assertEqual(detail["access"]["reason"], "free_grant")
        self.assertTrue(detail["access"]["ok"])

    def test_grant_requires_a_reason(self):
        r = self.post(
            f"/api/admin/companies/{self.company.id}/grant", self.admin_id,
            {"userId": str(uuid.uuid4()), "reason": ""},
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["reason"], "reason_required")
        self.assertEqual(MembershipGrant.objects.count(), 0)

    def test_sales_may_not_grant_or_revoke(self):
        r = self.post(
            f"/api/admin/companies/{self.company.id}/grant", self.sales_id,
            {"userId": str(uuid.uuid4()), "reason": "Säljaren tycker det"},
        )
        self.assertEqual(r.status_code, 403)
        self.assertEqual(MembershipGrant.objects.count(), 0)

        granted = self.post(
            f"/api/admin/companies/{self.company.id}/grant", self.admin_id,
            {"userId": str(uuid.uuid4()), "reason": "OK"},
        ).json()["grant"]
        r = self.post(
            f"/api/admin/grants/{granted['id']}/revoke", self.sales_id, {"reason": "Ångra"},
        )
        self.assertEqual(r.status_code, 403)
        self.assertIsNone(MembershipGrant.objects.get(id=granted["id"]).revoked_at)

    def test_revoke_endpoint_closes_the_grant_and_logs(self):
        granted = self.post(
            f"/api/admin/companies/{self.company.id}/grant", self.admin_id,
            {"email": "forare@taxi.test", "reason": "Goodwill efter driftstörning"},
        ).json()["grant"]
        # E-postadressen är okänd: raden väntar på inloggningen.
        self.assertIsNone(granted["userId"])
        self.assertEqual(granted["email"], "forare@taxi.test")

        r = self.post(
            f"/api/admin/grants/{granted['id']}/revoke", self.admin_id,
            {"reason": "Kunden ville inte ha det"},
        )
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()["grant"]
        self.assertTrue(body["revokedAt"])
        self.assertEqual(body["revokeReason"], "Kunden ville inte ha det")
        self.assertTrue(AuditEvent.objects.filter(
            action="membership_grant_revoked", company_id=self.company.id
        ).exists())

    def test_revoke_of_unknown_grant_is_a_404(self):
        r = self.post(f"/api/admin/grants/{uuid.uuid4()}/revoke", self.admin_id, {"reason": "x"})
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.json()["reason"], "unknown_grant")

    # --- personbaserat medlemskap utan bil ---------------------------------

    def test_create_membership_needs_no_vehicle(self):
        r = self.post(
            f"/api/admin/companies/{self.company.id}/memberships", self.admin_id,
            {"email": "kontor@taxi.test", "baseCounty": "12"},
        )
        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()["membership"]
        self.assertEqual(body["assigneeEmail"], "kontor@taxi.test")
        self.assertEqual(body["baseCounty"], "12")
        license = License.objects.get(id=body["licenseId"])
        self.assertEqual(license.status, License.Status.ACTIVE)
        # Ingen bil är kopplad till platsen.
        self.assertFalse(VehicleAssignment.objects.filter(license=license).exists())
        self.assertTrue(AuditEvent.objects.filter(
            action="membership_created", company_id=self.company.id
        ).exists())

    def test_create_membership_requires_a_person(self):
        r = self.post(
            f"/api/admin/companies/{self.company.id}/memberships", self.admin_id,
            {"baseCounty": "12"},
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["reason"], "person_required")