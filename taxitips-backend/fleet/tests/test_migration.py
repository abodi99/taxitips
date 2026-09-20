"""
Övergången för befintliga kunder, ägarbyte och kontostängning.

§11: befintliga kunder ska kunna migreras utan oväntad prisändring, borttappad
åtkomst eller fortsatt osäker bolagskodsväg -- och kontostängning eller
ägarbyte får inte lämna ett ägarlöst aktivt abonnemang.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.db import connection
from django.test import Client
from django.utils import timezone

from billing.models import Company, CompanyMember
from core.models import Opportunity, SeverityTier
from fleet import access, licensing, orders, ownership, pairing, roles, sessions
from fleet.models import (
    CompanyProfile,
    JoinRequest,
    License,
    Order,
    Subscription,
    SubscriptionStatus,
)
from fleet.tests.base import FleetTestCase

MALMO = {"lat": 55.6050, "lon": 13.0038}


def tip() -> Opportunity:
    now = timezone.now()
    return Opportunity.objects.create(
        external_id=f"test:{uuid.uuid4()}", kind="transit", mode="train",
        severity_tier=SeverityTier.LINE_PAUSED, title="Stopp", summary="Ingen trafik.",
        lat=MALMO["lat"], lon=MALMO["lon"], region="skane", area_codes=["12"],
        start_time=now - timedelta(minutes=10), end_time=now + timedelta(hours=1),
        demand_score=85, reasons=["stoppad linje"], rule_id="train.line_paused",
    )


class LegacyCompanyTests(FleetTestCase):
    """En kund som fanns före licensmodellen tappar inte åtkomsten av en deploy."""

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.company = Company.objects.create(
            id=uuid.uuid4(), name="Gamla Taxi AB", email="gammal@example.test",
            org_number="5566778899", join_code="OLD123", seats=3, status="active",
            created_at=timezone.now(), subscription_status="active",
        )
        self.device = self.make_device(self.company, label="Gammal telefon")

    def get_alerts(self, token):
        return self.client.get(
            "/api/alerts", MALMO, headers={"x-device-token": token}
        ).json()

    def test_an_unmigrated_company_keeps_working_after_the_deploy(self):
        tip()
        body = self.get_alerts(self.device.token)
        self.assertTrue(body["entitled"], body)
        self.assertEqual(len(body["alerts"]), 1)

    def test_enforcing_licenses_is_what_closes_the_old_path(self):
        tip()
        with self.settings(FLEET_ENFORCE_LICENSES="1"):
            body = self.get_alerts(self.device.token)
            self.assertFalse(body["entitled"])
            self.assertEqual(body["reason"], "device_not_approved")
        # Återställning: flaggan tillbaka, åtkomsten tillbaka. Ingen data rörd.
        self.assertTrue(self.get_alerts(self.device.token)["entitled"])

    def test_the_migration_command_opens_a_dated_window_without_touching_price(self):
        out = StringIO()
        call_command("migrate_legacy_fleet", "--days", "30", stdout=out)

        profile = CompanyProfile.objects.get(company_id=self.company.id)
        self.assertIsNotNone(profile.legacy_access_until)
        self.assertGreater(profile.legacy_access_until, timezone.now())

        subscription = Subscription.objects.get(company_id=self.company.id)
        self.assertEqual(subscription.status, SubscriptionStatus.ACTIVE)
        # Ingen period gissas, och inget belopp räknas om.
        self.assertIsNone(subscription.current_period_end)
        self.assertEqual(Order.objects.filter(company_id=self.company.id).count(), 0)

    def test_the_transition_window_keeps_old_phones_working_under_enforcement(self):
        tip()
        call_command("migrate_legacy_fleet", "--days", "30", stdout=StringIO())
        # Bolaget har nu en licens -> licensmodellen gäller, men fönstret bär den.
        licensing.create_license(
            company_id=self.company.id,
            vehicle=licensing.create_vehicle(company_id=self.company.id, plate="AAA111"),
            base_county="12",
        )
        with self.settings(FLEET_ENFORCE_LICENSES="1"):
            body = self.get_alerts(self.device.token)
            self.assertTrue(body["entitled"], body)
            self.assertEqual(len(body["alerts"]), 1)
            # Vilken väg åtkomsten kom genom syns inte i flödessvaret (det
            # bär bara `reason` vid ett nej), så den läses här.
            resolved = access.device_for_token(self.device.token)
            self.assertIsNotNone(resolved[0])

    def test_closing_the_window_ends_the_transition(self):
        call_command("migrate_legacy_fleet", "--days", "30", stdout=StringIO())
        licensing.create_license(
            company_id=self.company.id,
            vehicle=licensing.create_vehicle(company_id=self.company.id, plate="AAA111"),
            base_county="12",
        )
        call_command("migrate_legacy_fleet", "--close", stdout=StringIO())

        tip()
        with self.settings(FLEET_ENFORCE_LICENSES="1"):
            body = self.get_alerts(self.device.token)
            self.assertFalse(body["entitled"])

    def test_the_migration_does_not_guess_vehicles(self):
        """§: gissa inte bilkopplingar där underlag saknas."""
        call_command("migrate_legacy_fleet", "--days", "30", stdout=StringIO())
        self.assertEqual(License.objects.filter(company_id=self.company.id).count(), 0)

    def test_running_the_migration_twice_is_harmless(self):
        call_command("migrate_legacy_fleet", "--days", "30", stdout=StringIO())
        first = CompanyProfile.objects.get(company_id=self.company.id).legacy_access_until
        call_command("migrate_legacy_fleet", "--days", "30", stdout=StringIO())
        self.assertEqual(Subscription.objects.filter(company_id=self.company.id).count(), 1)
        self.assertIsNotNone(first)


class JoinCodeTests(FleetTestCase):
    """§2: en statisk bolagskod får bara hitta företaget eller skapa en ansökan."""

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.company = self.make_company()

    def test_the_join_code_creates_an_application_not_a_credential(self):
        response = self.client.post(
            "/api/fleet/join-request",
            data=(
                '{"join_code": "%s", "installation_id": "installation-1234567890"}'
                % self.company.join_code
            ),
            content_type="application/json",
        )
        body = response.json()
        self.assertTrue(body["ok"])
        self.assertNotIn("deviceToken", body)
        self.assertNotIn("token", body)

        self.assertEqual(JoinRequest.objects.filter(company_id=self.company.id).count(), 1)
        from fleet.models import DeviceApproval, DeviceCredential

        self.assertEqual(DeviceCredential.objects.count(), 0)
        self.assertEqual(DeviceApproval.objects.count(), 0)

    def test_an_unknown_code_is_indistinguishable_from_a_known_one(self):
        known = self.client.post(
            "/api/fleet/join-request",
            data=(
                '{"join_code": "%s", "installation_id": "installation-1234567890"}'
                % self.company.join_code
            ),
            content_type="application/json",
        ).json()
        unknown = self.client.post(
            "/api/fleet/join-request",
            data='{"join_code": "NOPE99", "installation_id": "installation-1234567890"}',
            content_type="application/json",
        ).json()
        self.assertEqual(known["ok"], unknown["ok"])
        self.assertEqual(known["message"], unknown["message"])

    def test_the_sql_function_no_longer_hands_out_devices(self):
        """
        Den produktionskopplade vägen är SQL-funktionen. Testdatabasen har
        Supabase-migrationerna, så funktionen finns bara om den körts här --
        testet hoppar över sig självt när den saknas, i stället för att ljuga
        om att hålet är stängt.
        """
        with connection.cursor() as cursor:
            cursor.execute(
                "select count(*) from pg_proc where proname = 'join_device'"
            )
            exists = cursor.fetchone()[0]
        if not exists:
            self.skipTest(
                "join_device finns inte i testdatabasen (Supabase-migrationerna "
                "körs inte av Djangos testrunner). Verifierad mot den lokala "
                "instansen i stället -- se docs/fleet-abonnemang.md."
            )
        with connection.cursor() as cursor:
            with self.assertRaises(Exception):
                cursor.execute("select public.join_device(%s, %s)", ["DEMO01", "Test"])


class OwnershipTests(FleetTestCase):
    """§10: ägarbyte och kontostängning lämnar inget ägarlöst abonnemang."""

    def setUp(self):
        super().setUp()
        self.company = self.make_company()
        self.subscription = self.make_subscription(self.company)
        self.owner = self.make_owner(self.company)
        self.admin = CompanyMember.objects.create(
            id=uuid.uuid4(), company_id=self.company.id, user_id=uuid.uuid4(),
            role=roles.FLEET_ADMIN, status="active", created_at=timezone.now(),
        )

    def _principal(self, member, aal="aal2"):
        return roles.Principal(
            user_id=str(member.user_id), company_id=str(self.company.id),
            role=member.role, aal=aal, permissions=roles.permissions_for(member.role),
        )

    def test_the_last_owner_cannot_be_removed_from_a_paying_company(self):
        with self.assertRaises(ownership.OwnershipError) as caught:
            ownership.remove_member(
                company_id=self.company.id, user_id=self.owner.user_id,
                actor_user_id=self.owner.user_id,
            )
        self.assertEqual(caught.exception.reason, "last_owner")
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.status, "active")

    def test_a_non_owner_can_be_removed(self):
        ownership.remove_member(
            company_id=self.company.id, user_id=self.admin.user_id,
            actor_user_id=self.owner.user_id,
        )
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.status, "removed")

    def test_transfer_needs_the_recipients_acceptance(self):
        transfer = ownership.request_transfer(
            company_id=self.company.id, from_principal=self._principal(self.owner),
            to_user_id=self.admin.user_id,
        )
        # Ingenting har bytt plats än.
        self.owner.refresh_from_db()
        self.admin.refresh_from_db()
        self.assertEqual(self.owner.role, roles.OWNER)
        self.assertEqual(self.admin.role, roles.FLEET_ADMIN)

        ownership.accept_transfer(transfer=transfer, by_user_id=self.admin.user_id)
        self.owner.refresh_from_db()
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, roles.OWNER)
        self.assertEqual(self.owner.role, roles.FLEET_ADMIN)
        # Företaget passerade aldrig ett läge utan ägare.
        self.assertEqual(len(ownership.owners(self.company.id)), 1)

    def test_only_the_recipient_can_accept(self):
        transfer = ownership.request_transfer(
            company_id=self.company.id, from_principal=self._principal(self.owner),
            to_user_id=self.admin.user_id,
        )
        with self.assertRaises(ownership.OwnershipError) as caught:
            ownership.accept_transfer(transfer=transfer, by_user_id=self.owner.user_id)
        self.assertEqual(caught.exception.reason, "not_recipient")

    def test_transfer_requires_two_factor_once_enforced(self):
        yesterday = (timezone.now() - timedelta(days=1)).isoformat()
        with self.settings(FLEET_TWO_FACTOR_REQUIRED_FROM=yesterday):
            with self.assertRaises(roles.PermissionDenied) as caught:
                ownership.request_transfer(
                    company_id=self.company.id,
                    from_principal=self._principal(self.owner, aal="aal1"),
                    to_user_id=self.admin.user_id,
                )
            self.assertEqual(caught.exception.reason, "two_factor_required")

    def test_closing_the_account_stops_renewal_and_explains_the_rest(self):
        result = ownership.close_account(
            company_id=self.company.id, actor_user_id=self.owner.user_id
        )
        self.subscription.refresh_from_db()
        self.assertIsNotNone(self.subscription.renewal_stopped_at)
        self.assertTrue(self.subscription.cancel_at_period_end)
        self.assertTrue(result["renewalStopped"])
        self.assertIn("Provhistoriken behålls", result["explanation"])
        # Åtkomsten gäller den betalda perioden ut.
        self.assertTrue(access.company_window(self.company.id).ok)

    def test_removing_a_driver_does_not_end_the_subscription(self):
        """§8: avinstallation och borttagning av förare avslutar inte abonnemanget."""
        data = self.full_setup()
        device = self.make_device(self.company)
        vehicle, license = self.make_license(self.company, plate="CCC333")
        approval, _secret = self.approve(self.company, license, vehicle, device)
        sessions.start_session(device_id=device.id, license_id=license.id)

        pairing.block_device(approval=approval, actor_user_id=self.owner.user_id)

        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, SubscriptionStatus.ACTIVE)
        self.assertFalse(self.subscription.cancel_at_period_end)
        self.assertTrue(access.company_window(self.company.id).ok)

    def test_changing_the_org_number_opens_a_review_and_gives_no_new_trial(self):
        from fleet import trials
        from fleet.models import Trial

        trial = trials.create_trial(
            company_id=self.company.id, country="SE", org_number="5566778899",
            source=Trial.Source.SELF_SIGNUP,
        )
        trials.start_trial(trial)
        trials.end_trial(trial, reason="period_over")

        review = ownership.change_contracting_party(
            company_id=self.company.id, country="SE", org_number="556016-0680",
            actor_user_id=self.owner.user_id, note="Verksamheten övertagen.",
        )
        self.assertEqual(review.status, review.Status.OPEN)
        # Den gamla provraden ligger kvar och spärren gäller fortfarande.
        self.assertFalse(trials.eligibility(country="SE", org_number="5566778899").ok)
