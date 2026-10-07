"""
Radera mitt konto i appen (Apple 5.1.1(v)) -- fleet/account_deletion.py.

Det som provas: att kontot faktiskt försvinner (Supabase Auth, medlemskap,
katalog, telefonens koppling), att föraren kan radera utan Supabase-session,
och de två vägranden som skyddar någon annan: enda ägaren med ett medlemskap
som förnyas, och ett ägarkonto som bara bevisas med en förartelefon.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from unittest.mock import patch

from django.test import Client, RequestFactory, override_settings
from django.utils import timezone

from billing.models import CompanyMember, Device
from core.models import DevicePresence, OpportunityFavorite
from fleet import access, accounts, auth_admin, licensing, sessions, trials
from fleet.models import (
    AuditEvent,
    ClientActivity,
    CompanyProfile,
    DeviceApproval,
    DeviceCredential,
    DriverInvite,
    KnownAccount,
    License,
    StaffRole,
    Subscription,
    Trial,
    VehicleSession,
)
from fleet.tests.base import FleetTestCase
from fleet.tests.test_accounts import SECRET, jwt

URL = "/api/fleet/account/delete"
CONFIRM = {"confirm": "radera"}


@override_settings(
    SUPABASE_JWT_SECRET=SECRET,
    SUPABASE_SERVICE_ROLE_KEY="test-service-role",
    SUPABASE_URL="http://supabase.test",
)
class AccountDeletionTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        accounts._seen_cache.clear()
        self.client = Client()

    def post(self, body=None, *, user_id=None, email="", device_token=None):
        headers = {}
        if user_id:
            headers["authorization"] = f"Bearer {jwt(str(user_id), email)}"
        if device_token:
            headers["X-Device-Token"] = device_token
        return self.client.post(
            URL, data=json.dumps(body if body is not None else CONFIRM),
            content_type="application/json", headers=headers,
        )

    def driver_access(self, secret):
        request = RequestFactory().get("/api/alerts", headers={"X-Device-Token": secret})
        return access.resolve(request)

    def seen(self, user_id, email):
        """Kontot har anropat servern: katalograden finns (fleet/accounts.py:seen)."""
        self.client.get(
            "/api/fleet/company", headers={"authorization": f"Bearer {jwt(str(user_id), email)}"},
        )
        self.assertTrue(KnownAccount.objects.filter(user_id=user_id).exists())

    # -- Inloggat konto --------------------------------------------------------

    def test_without_confirmation_nothing_happens(self):
        data = self.full_setup()
        owner = data["owner"].user_id
        with patch("fleet.auth_admin.delete_user") as delete_user:
            response = self.post({}, user_id=owner)
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()["reason"], "confirm_required")
        delete_user.assert_not_called()
        self.assertTrue(CompanyMember.objects.filter(user_id=owner).exists())

    def test_without_login_or_phone_it_is_refused(self):
        response = self.post()
        self.assertEqual(response.status_code, 401, response.content)
        self.assertEqual(response.json()["reason"], "login_required")

    def test_the_sole_owner_with_a_renewing_membership_pauses_and_archives(self):
        # Ägaren raderar sitt konto: medlemskapet pausas (förnyelsen stoppas)
        # och företaget arkiveras, i stället för att vägra (ägarens beslut
        # 2026-10-07). Kontot tas bort och företaget lämnas inte föräldralöst.
        data = self.full_setup()
        owner = data["owner"].user_id
        with patch("fleet.auth_admin.delete_user") as delete_user:
            response = self.post(user_id=owner)
        self.assertEqual(response.status_code, 200, response.content)
        delete_user.assert_called_once()
        self.assertFalse(
            CompanyMember.objects.filter(user_id=owner, status="active").exists()
        )
        profile = CompanyProfile.objects.get(company_id=data["company"].id)
        self.assertIsNotNone(profile.archived_at)
        subscription = Subscription.objects.get(id=data["subscription"].id)
        self.assertIsNotNone(subscription.renewal_stopped_at)

    def test_after_closing_the_company_account_the_owner_can_delete(self):
        data = self.full_setup()
        owner = data["owner"].user_id
        self.seen(owner, "agare@example.test")
        Subscription.objects.filter(id=data["subscription"].id).update(
            cancel_at_period_end=True, renewal_stopped_at=timezone.now(),
        )
        with patch("fleet.auth_admin.delete_user") as delete_user:
            response = self.post(user_id=owner, email="agare@example.test")
        self.assertEqual(response.status_code, 200, response.content)
        delete_user.assert_called_once_with(str(owner))
        self.assertFalse(CompanyMember.objects.filter(user_id=owner).exists())
        self.assertFalse(KnownAccount.objects.filter(user_id=owner).exists())
        self.assertFalse(ClientActivity.objects.filter(subject_id=owner).exists())
        event = AuditEvent.objects.get(action="account_deleted_by_user")
        self.assertEqual(str(event.company_id), str(data["company"].id))
        self.assertEqual(event.detail["via"], "app")

    def test_a_card_free_trial_does_not_stop_the_deletion_and_ends(self):
        company = self.make_company()
        owner = self.make_owner(company)
        trial = trials.create_trial(
            company_id=company.id, country="SE", org_number="5566778899",
            source=Trial.Source.SELF_SIGNUP,
        )
        trials.start_trial(trial)
        vehicle = licensing.create_vehicle(company_id=company.id, plate="PRV001")
        license = licensing.create_license(
            company_id=company.id, vehicle=vehicle, base_county="12",
            status=License.Status.TRIAL, trial=trial,
        )
        with patch("fleet.auth_admin.delete_user") as delete_user:
            response = self.post(user_id=owner.user_id)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["trialsEnded"], 1)
        delete_user.assert_called_once()
        trial.refresh_from_db()
        license.refresh_from_db()
        self.assertEqual(trial.status, Trial.Status.ENDED)
        self.assertEqual(trial.ended_reason, "owner_account_deleted")
        self.assertEqual(license.status, License.Status.CANCELED)

    def test_a_colleague_can_delete_while_the_owner_keeps_the_company(self):
        data = self.full_setup()
        colleague = self.make_owner(data["company"], role="fleet_admin")
        with patch("fleet.auth_admin.delete_user") as delete_user:
            response = self.post(user_id=colleague.user_id)
        self.assertEqual(response.status_code, 200, response.content)
        delete_user.assert_called_once_with(str(colleague.user_id))
        self.assertFalse(CompanyMember.objects.filter(user_id=colleague.user_id).exists())
        self.assertTrue(
            CompanyMember.objects.filter(user_id=data["owner"].user_id, status="active").exists()
        )

    def test_one_of_two_owners_can_delete_even_when_the_membership_renews(self):
        data = self.full_setup()
        second = self.make_owner(data["company"])
        with patch("fleet.auth_admin.delete_user"):
            response = self.post(user_id=second.user_id)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(CompanyMember.objects.filter(user_id=data["owner"].user_id).exists())

    def test_a_staff_account_is_not_deleted_from_the_app(self):
        staff = str(uuid.uuid4())
        StaffRole.objects.create(user_id=staff, role=StaffRole.Role.PLATFORM_ADMIN)
        with patch("fleet.auth_admin.delete_user") as delete_user:
            response = self.post(user_id=staff)
        self.assertEqual(response.status_code, 409, response.content)
        self.assertEqual(response.json()["reason"], "staff_account")
        delete_user.assert_not_called()

    @override_settings(SUPABASE_SERVICE_ROLE_KEY="")
    def test_without_the_auth_key_nothing_is_removed(self):
        data = self.full_setup()
        colleague = self.make_owner(data["company"], role="fleet_admin")
        response = self.post(user_id=colleague.user_id)
        self.assertEqual(response.status_code, 503, response.content)
        self.assertEqual(response.json()["reason"], "auth_not_configured")
        self.assertTrue(CompanyMember.objects.filter(user_id=colleague.user_id).exists())

    def test_when_auth_fails_everything_is_rolled_back(self):
        data = self.full_setup()
        colleague = self.make_owner(data["company"], role="fleet_admin")
        with patch(
            "fleet.auth_admin.delete_user", side_effect=auth_admin.AuthAdminError("nere"),
        ):
            response = self.post(user_id=colleague.user_id)
        self.assertEqual(response.status_code, 502, response.content)
        self.assertEqual(response.json()["reason"], "auth_delete_failed")
        self.assertTrue(CompanyMember.objects.filter(user_id=colleague.user_id).exists())
        self.assertFalse(AuditEvent.objects.filter(action="account_deleted_by_user").exists())

    def test_an_owner_who_drives_also_releases_the_phone(self):
        data = self.full_setup()
        Subscription.objects.filter(id=data["subscription"].id).update(cancel_at_period_end=True)
        owner = data["owner"].user_id
        Device.objects.filter(id=data["device"].id).update(push_token="fcm-1")
        with patch("fleet.auth_admin.delete_user"):
            response = self.post(user_id=owner, device_token=data["secret"])
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["phonesReleased"], 1)
        self.assertFalse(self.driver_access(data["secret"]).ok)
        self.assertIsNone(Device.objects.get(id=data["device"].id).push_token)

    # -- Förarens telefon ------------------------------------------------------

    def driver_with_invite(self, *, auth_user_id=None):
        data = self.full_setup()
        auth_user_id = auth_user_id or uuid.uuid4()
        now = timezone.now()
        DriverInvite.objects.create(
            company_id=data["company"].id, license=data["license"], vehicle=data["vehicle"],
            email="forare@example.test", status=DriverInvite.Status.CONSUMED,
            expires_at=now + timedelta(days=7), auth_user_id=auth_user_id,
            consumed_at=now, consumed_by_user=auth_user_id,
            consumed_by_device=data["device"].id,
        )
        sessions.start_session(device_id=data["device"].id, license_id=data["license"].id)
        Device.objects.filter(id=data["device"].id).update(
            push_token="fcm-driver", notify_prefs={"counties": ["12"]},
        )
        OpportunityFavorite.objects.create(
            owner_key=f"device:{data['device'].id}", opportunity_external_id="x-1",
        )
        DevicePresence.objects.create(
            device_id=data["device"].id, cell_lat=55.6, cell_lon=13.0,
            updated_at=now, expires_at=now + timedelta(minutes=30),
        )
        return data, str(auth_user_id)

    def test_a_driver_deletes_the_account_and_the_phone_link_without_a_session(self):
        data, driver = self.driver_with_invite()
        self.assertTrue(self.driver_access(data["secret"]).ok)
        with patch("fleet.auth_admin.delete_user") as delete_user:
            response = self.post(device_token=data["secret"])
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["accountsDeleted"], 1)
        delete_user.assert_called_once_with(driver)

        # Telefonen har ingen åtkomst längre, och inget pekar på föraren.
        self.assertFalse(self.driver_access(data["secret"]).ok)
        approval = DeviceApproval.objects.get(id=data["approval"].id)
        self.assertEqual(approval.status, DeviceApproval.Status.REPLACED)
        self.assertEqual(approval.revoke_reason, "account_deleted")
        self.assertFalse(
            DeviceCredential.objects.filter(device_id=data["device"].id, revoked_at__isnull=True).exists()
        )
        self.assertFalse(
            VehicleSession.objects.filter(device_id=data["device"].id, ended_at__isnull=True).exists()
        )
        device = Device.objects.get(id=data["device"].id)
        self.assertIsNone(device.push_token)
        self.assertEqual(device.notify_prefs, {})
        self.assertEqual(device.label, "Raderad")
        self.assertFalse(OpportunityFavorite.objects.filter(owner_key=f"device:{device.id}").exists())
        self.assertFalse(DevicePresence.objects.filter(device_id=device.id).exists())
        # Företaget och ägaren rörs inte.
        self.assertTrue(CompanyMember.objects.filter(user_id=data["owner"].user_id).exists())
        self.assertTrue(AuditEvent.objects.filter(action="account_deleted_by_user").exists())

    def test_a_driver_login_that_is_also_an_owner_keeps_the_owner_account(self):
        data = self.full_setup()
        owner = data["owner"].user_id
        now = timezone.now()
        DriverInvite.objects.create(
            company_id=data["company"].id, license=data["license"], vehicle=data["vehicle"],
            email="agare@example.test", status=DriverInvite.Status.CONSUMED,
            expires_at=now + timedelta(days=7), auth_user_id=owner,
            consumed_at=now, consumed_by_user=owner, consumed_by_device=data["device"].id,
        )
        with patch("fleet.auth_admin.delete_user") as delete_user:
            response = self.post(device_token=data["secret"])
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["accountsDeleted"], 0)
        self.assertEqual(body["accountsKept"], 1)
        self.assertIn("logga in", body["message"])
        delete_user.assert_not_called()
        self.assertTrue(CompanyMember.objects.filter(user_id=owner, status="active").exists())
        self.assertFalse(self.driver_access(data["secret"]).ok)

    @override_settings(SUPABASE_SERVICE_ROLE_KEY="")
    def test_a_phone_without_a_driver_account_is_released_without_the_auth_key(self):
        data = self.full_setup()
        response = self.post(device_token=data["secret"])
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["accountsDeleted"], 0)
        self.assertFalse(self.driver_access(data["secret"]).ok)

    def test_an_unknown_phone_token_is_refused(self):
        response = self.post(device_token="inte-en-token")
        self.assertEqual(response.status_code, 401, response.content)
