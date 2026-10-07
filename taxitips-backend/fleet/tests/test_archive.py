"""
Avslutade bolag: arkivera, återställ och radera (fleet/archive.py).
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from unittest import mock

from django.test import Client, override_settings
from django.utils import timezone

from billing.models import Company, CompanyMember, Device
from fleet import archive, commerce, orders, sessions, trials
from fleet.models import (
    AuditEvent, CompanyProfile, License, Order, SalesFollowUp, Subscription, Trial, Vehicle,
    VehicleSession,
)
from fleet.tests.base import FleetTestCase


class ArchiveTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.staff = uuid.uuid4()
        self.company = self.make_company(name="Avslutad AB", org_number="5566778899", status="inactive")
        self.owner = self.make_owner(self.company)
        self.trial = trials.create_trial(
            company_id=self.company.id, country="SE", org_number="5566778899",
            source=Trial.Source.SELF_SIGNUP, requires_payment_method=False,
        )
        now = timezone.now()
        Trial.objects.filter(id=self.trial.id).update(
            status=Trial.Status.ACTIVE, started_at=now - timedelta(days=3), ends_at=now + timedelta(days=11),
        )
        orders.get_or_create_subscription(self.company.id)
        vehicle, self.license = self.make_license(self.company, plate="AVS123")
        License.objects.filter(id=self.license.id).update(status=License.Status.TRIAL, trial=self.trial)
        device = self.make_device(self.company)
        self.approve(self.company, self.license, vehicle, device)
        sessions.start_session(device_id=device.id, license_id=self.license.id)
        SalesFollowUp.objects.create(company_id=self.company.id, note="Ringde")

    def as_staff(self):
        return mock.patch("fleet.admin_api._staff", return_value=mock.Mock(user_id=self.staff))

    def post(self, path, body):
        with self.as_staff():
            return self.client.post(path, json.dumps(body), content_type="application/json")

    def terminate(self):
        commerce.terminate_now(self.company.id, actor_user_id=self.staff, reason="Kunden ville avsluta")

    def list_names(self, **params):
        with self.as_staff():
            body = self.client.get("/api/admin/companies", params).json()
        return [c["name"] for c in body["companies"]]

    def test_a_company_with_access_is_not_archived(self):
        response = self.post(f"/api/admin/companies/{self.company.id}/archive", {})
        self.assertEqual(response.status_code, 409)
        self.assertIn("Avsluta", response.json()["message"])

    def test_a_terminated_company_leaves_the_lists_and_can_come_back(self):
        self.terminate()
        self.assertEqual(self.post(f"/api/admin/companies/{self.company.id}/archive", {}).status_code, 200)
        self.assertNotIn("Avslutad AB", self.list_names())
        self.assertEqual(self.list_names(archived="1"), ["Avslutad AB"])
        self.post(f"/api/admin/companies/{self.company.id}/archive", {"archived": False})
        self.assertIn("Avslutad AB", self.list_names())

    def test_delete_needs_archive_and_the_exact_name(self):
        self.terminate()
        response = self.post(f"/api/admin/companies/{self.company.id}/delete", {"confirmName": "Avslutad AB"})
        self.assertEqual(response.json()["reason"], "cannot_delete")
        archive.archive(self.company.id, actor_user_id=self.staff)
        response = self.post(f"/api/admin/companies/{self.company.id}/delete", {"confirmName": "avslutad"})
        self.assertEqual(response.json()["reason"], "confirm_name_mismatch")
        self.assertTrue(Company.objects.filter(id=self.company.id).exists())

    def test_delete_removes_everything_but_the_trial_history(self):
        self.terminate()
        archive.archive(self.company.id, actor_user_id=self.staff)
        response = self.post(f"/api/admin/companies/{self.company.id}/delete", {"confirmName": "Avslutad AB"})
        self.assertEqual(response.status_code, 200, response.content)
        cid = self.company.id
        self.assertFalse(Company.objects.filter(id=cid).exists())
        self.assertFalse(Device.objects.filter(company_id=cid).exists())
        self.assertFalse(CompanyMember.objects.filter(company_id=cid).exists())
        self.assertFalse(CompanyProfile.objects.filter(company_id=cid).exists())
        self.assertFalse(Vehicle.objects.filter(company_id=cid).exists())
        self.assertFalse(VehicleSession.objects.filter(company_id=cid).exists())
        self.assertFalse(Subscription.objects.filter(company_id=cid).exists())
        self.assertFalse(SalesFollowUp.objects.filter(company_id=cid).exists())
        # Provhistoriken finns kvar: samma orgnr får inget nytt gratisprov.
        self.assertTrue(Trial.objects.filter(company_id=cid).exists())
        self.assertFalse(trials.eligibility(country="SE", org_number="5566778899").ok)
        deleted = AuditEvent.objects.get(action="company_deleted", company_id=cid)
        self.assertNotIn("Avslutad", json.dumps(deleted.detail))

    @override_settings(
        SUPABASE_SERVICE_ROLE_KEY="test-service-role", SUPABASE_URL="http://supabase.test",
    )
    def test_delete_removes_the_members_auth_accounts(self):
        # Kontot hör till bolaget: raderas bolaget ska inloggningen bort också,
        # annars kan den fortsätta logga in och e-posten går inte att använda
        # igen (se fleet/archive.py:_delete_auth_accounts).
        colleague = self.make_owner(self.company, role="fleet_admin")
        self.terminate()
        archive.archive(self.company.id, actor_user_id=self.staff)
        with mock.patch("fleet.auth_admin.delete_user") as delete_user:
            response = self.post(
                f"/api/admin/companies/{self.company.id}/delete", {"confirmName": "Avslutad AB"}
            )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            {call.args[0] for call in delete_user.call_args_list},
            {str(self.owner.user_id), str(colleague.user_id)},
        )
        self.assertEqual(response.json()["deleted"]["inloggningar"], 2)

    def test_a_company_that_paid_is_only_archived(self):
        self.terminate()
        Subscription.objects.filter(company_id=self.company.id).update(had_successful_payment=True)
        archive.archive(self.company.id, actor_user_id=self.staff)
        state = archive.state(self.company.id)
        self.assertFalse(state.can_delete)
        self.assertIn("sju år", state.delete_blocker)
        response = self.post(f"/api/admin/companies/{self.company.id}/delete", {"confirmName": "Avslutad AB"})
        self.assertEqual(response.status_code, 409)
        self.assertTrue(Company.objects.filter(id=self.company.id).exists())

    def test_a_pending_order_blocks_archiving(self):
        self.terminate()
        Order.objects.create(
            company_id=self.company.id, status=Order.Status.PENDING_PAYMENT,
            price_version=Subscription.objects.get(company_id=self.company.id).price_version,
        )
        self.assertIn("beställning", archive.state(self.company.id).archive_blocker)
