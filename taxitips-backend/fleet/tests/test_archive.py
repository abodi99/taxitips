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
    AuditEvent, CompanyProfile, DriverInvite, License, Order, SalesFollowUp, Subscription, Trial,
    Vehicle, VehicleSession,
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

    def test_the_blocker_says_what_to_do(self):
        state = archive.state(self.company.id)
        self.assertEqual(state.archive_blocked_by, "access")
        self.assertIn("Avsluta direkt", state.archive_blocker)
        self.assertEqual(state.as_dict()["archiveBlockedBy"], "access")

    def test_terminate_now_revokes_a_granted_membership_so_the_company_can_be_archived(self):
        """Förut höll ett beviljande fönstret öppet efter "Avsluta direkt" (2026-10-11)."""
        from fleet import grants
        from fleet.models import MembershipGrant

        grant = grants.grant_membership(
            company_id=self.company.id, email="forare@example.se", reason="goodwill",
        )
        self.terminate()
        self.assertIsNotNone(MembershipGrant.objects.get(id=grant.id).revoked_at)
        state = archive.state(self.company.id)
        self.assertTrue(state.can_archive, state.archive_blocker)
        self.assertEqual(self.post(f"/api/admin/companies/{self.company.id}/archive", {}).status_code, 200)

    def test_delete_needs_archive_and_the_exact_name(self):
        self.terminate()
        response = self.post(f"/api/admin/companies/{self.company.id}/delete", {"confirmName": "Avslutad AB"})
        self.assertEqual(response.json()["reason"], "cannot_delete")
        archive.archive(self.company.id, actor_user_id=self.staff)
        response = self.post(f"/api/admin/companies/{self.company.id}/delete", {"confirmName": "avslutad"})
        self.assertEqual(response.json()["reason"], "confirm_name_mismatch")
        self.assertTrue(Company.objects.filter(id=self.company.id).exists())

    def test_delete_removes_everything_and_the_company_may_try_again(self):
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
        # Ägarens beslut 2026-10-11: permanent raderat = får prova igen.
        self.assertFalse(Trial.objects.filter(company_id=cid).exists())
        self.assertTrue(trials.eligibility(country="SE", org_number="5566778899").ok)
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

    def test_an_archived_company_keeps_the_trial_block(self):
        self.terminate()
        archive.archive(self.company.id, actor_user_id=self.staff)
        self.assertFalse(trials.eligibility(country="SE", org_number="5566778899").ok)

    def test_delete_spares_the_trial_of_another_company_that_still_exists(self):
        """Samma orgnr i ett annat bolag (t.ex. arkiverat): dess spärr står kvar."""
        twin = self.make_company(name="Tvilling AB", org_number="5566778899")
        twin_trial = Trial.objects.create(
            company_id=twin.id, org_key="SE:5566778899", source=Trial.Source.SALES,
            requires_payment_method=False, status=Trial.Status.ENDED,
        )
        self.terminate()
        archive.archive(self.company.id, actor_user_id=self.staff)
        self.post(f"/api/admin/companies/{self.company.id}/delete", {"confirmName": "Avslutad AB"})
        self.assertTrue(Trial.objects.filter(id=twin_trial.id).exists())
        self.assertFalse(Trial.objects.filter(company_id=self.company.id).exists())

    @override_settings(
        SUPABASE_SERVICE_ROLE_KEY="test-service-role", SUPABASE_URL="http://supabase.test",
    )
    def test_auth_is_asked_only_after_the_company_rows_are_gone(self):
        """Inne i transaktionen väntade Auth på våra lås och svarade 504 (prod 2026-10-11)."""
        self.terminate()
        archive.archive(self.company.id, actor_user_id=self.staff)
        seen = []

        def delete_user(user_id):
            seen.append(Company.objects.filter(id=self.company.id).exists())

        with mock.patch("fleet.auth_admin.delete_user", side_effect=delete_user):
            response = self.post(
                f"/api/admin/companies/{self.company.id}/delete", {"confirmName": "Avslutad AB"}
            )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(seen, [False])

    @override_settings(
        SUPABASE_SERVICE_ROLE_KEY="test-service-role", SUPABASE_URL="http://supabase.test",
    )
    def test_a_failed_auth_delete_is_counted_and_the_ids_are_kept(self):
        from fleet import auth_admin

        self.terminate()
        archive.archive(self.company.id, actor_user_id=self.staff)
        with mock.patch("fleet.auth_admin.delete_user", side_effect=auth_admin.AuthAdminError("504")):
            response = self.post(
                f"/api/admin/companies/{self.company.id}/delete", {"confirmName": "Avslutad AB"}
            )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["deleted"]["inloggningar kvar"], 1)
        event = AuditEvent.objects.filter(action="company_deleted").latest("created_at")
        self.assertEqual(event.detail["account_ids"], [str(self.owner.user_id)])

    def test_archiving_pauses_the_accounts_and_restoring_lifts_only_those(self):
        from fleet import accounts, grants
        from fleet.models import StaffRole

        seat_user = uuid.uuid4()
        other = self.make_company(name="Annat AB", org_number="5599001122")
        shared = self.make_owner(self.company, role="fleet_admin")
        self.make_owner(other).user_id  # en annan ägare i det andra bolaget
        CompanyMember.objects.create(
            id=uuid.uuid4(), company_id=other.id, user_id=shared.user_id, role="fleet_admin", status="active",
        )
        staff_member = self.make_owner(self.company, role="fleet_admin")
        StaffRole.objects.create(user_id=staff_member.user_id, role="platform_admin", is_active=True)
        grant = grants.grant_membership(company_id=self.company.id, user_id=seat_user, reason="test")
        # Pausad av personalen av ett annat skäl -- ska stå kvar efter återställningen.
        accounts.pause(scope="user", value=str(self.owner.user_id), reason="Obetalt",
                       actor_user_id=self.staff, actor_kind="platform_admin")

        self.terminate()
        self.assertIsNotNone(type(grant).objects.get(id=grant.id).revoked_at)
        archive.archive(self.company.id, actor_user_id=self.staff)
        self.assertIsNotNone(accounts.account_pause(str(seat_user)))
        self.assertIsNotNone(accounts.account_pause(str(self.owner.user_id)))
        self.assertIsNone(accounts.account_pause(str(shared.user_id)), "hör också till ett annat bolag")
        self.assertIsNone(accounts.account_pause(str(staff_member.user_id)), "personal pausas inte")

        archive.unarchive(self.company.id, actor_user_id=self.staff)
        self.assertIsNone(accounts.account_pause(str(seat_user)))
        self.assertEqual(accounts.account_pause(str(self.owner.user_id)).reason, "Obetalt")

    @override_settings(
        SUPABASE_SERVICE_ROLE_KEY="test-service-role", SUPABASE_URL="http://supabase.test",
    )
    def test_delete_removes_driver_auth_accounts_too(self):
        # Förarna som bjudits in med e-post är inte company_members, men deras
        # Auth-konton hör ändå till bolaget och ska bort med det.
        driver_user = uuid.uuid4()
        DriverInvite.objects.create(
            company_id=self.company.id,
            license=self.license,
            vehicle=Vehicle.objects.get(company_id=self.company.id),
            email="forare@example.test",
            status=DriverInvite.Status.CONSUMED,
            expires_at=timezone.now() + timedelta(days=7),
            auth_user_id=driver_user,
            consumed_at=timezone.now(),
            consumed_by_user=driver_user,
        )
        self.terminate()
        archive.archive(self.company.id, actor_user_id=self.staff)
        with mock.patch("fleet.auth_admin.delete_user") as delete_user:
            response = self.post(
                f"/api/admin/companies/{self.company.id}/delete", {"confirmName": "Avslutad AB"}
            )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn(
            str(driver_user),
            {call.args[0] for call in delete_user.call_args_list},
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
