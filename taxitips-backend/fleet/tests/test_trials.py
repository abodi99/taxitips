"""
Provperioden och skyddet mot upprepade gratiskonton (§7).

Spärren räknar på organisationsnumret. Testerna här provar just det som ett
nytt konto, en ny telefon eller en ny e-postadress skulle kunna användas för
att kringgå.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.utils import timezone

from fleet import licensing, orders, orgnr, trials
from fleet.models import License, SalesInvite, Trial
from fleet.tests.base import FleetTestCase


class OrgNumberTests(FleetTestCase):
    def test_all_spellings_normalize_to_one_key(self):
        variants = ["556677-8899", "5566778899", "165566778899", " 556677 - 8899 "]
        keys = {orgnr.org_key("SE", v) for v in variants}
        self.assertEqual(len(keys), 1, keys)

    def test_luhn_rejects_a_typo(self):
        self.assertTrue(orgnr.is_valid("556677-8899"))
        self.assertFalse(orgnr.is_valid("556677-8898"))

    def test_garbage_normalizes_to_nothing(self):
        self.assertEqual(orgnr.normalize("inte ett nummer"), "")
        self.assertFalse(orgnr.is_valid(""))


class TrialEligibilityTests(FleetTestCase):
    ORG = "556677-8899"

    def test_a_first_trial_is_allowed(self):
        self.assertTrue(trials.eligibility(country="SE", org_number=self.ORG).ok)

    def test_a_new_company_account_with_the_same_org_number_gets_nothing(self):
        """§7: ny administratör, ny e-post eller nytt konto återställer inte provet."""
        first = self.make_company(org_number=orgnr.normalize(self.ORG))
        trial = trials.create_trial(
            company_id=first.id, country="SE", org_number=self.ORG,
            source=Trial.Source.SELF_SIGNUP,
        )
        trials.start_trial(trial)
        trials.end_trial(trial, reason="period_over")

        second = self.make_company(name="Nytt Bolag AB", org_number=orgnr.normalize(self.ORG))
        check = trials.eligibility(country="SE", org_number=self.ORG)
        self.assertFalse(check.ok)
        self.assertEqual(check.reason, "trial_used_recently")
        with self.assertRaises(trials.TrialError):
            trials.create_trial(
                company_id=second.id, country="SE", org_number=self.ORG,
                source=Trial.Source.SELF_SIGNUP,
            )

    def test_after_twenty_four_months_a_new_trial_is_allowed(self):
        company = self.make_company(org_number=orgnr.normalize(self.ORG))
        trial = trials.create_trial(
            company_id=company.id, country="SE", org_number=self.ORG,
            source=Trial.Source.SELF_SIGNUP,
        )
        long_ago = timezone.now() - timedelta(days=25 * 30)
        Trial.objects.filter(id=trial.id).update(
            started_at=long_ago, created_at=long_ago, status=Trial.Status.ENDED
        )
        self.assertTrue(trials.eligibility(country="SE", org_number=self.ORG).ok)

    def test_two_simultaneous_registrations_give_one_trial(self):
        """§7: hantera dubbla samtidiga registreringar."""
        company = self.make_company(org_number=orgnr.normalize(self.ORG))
        trials.create_trial(
            company_id=company.id, country="SE", org_number=self.ORG,
            source=Trial.Source.SELF_SIGNUP,
        )
        with self.assertRaises(trials.TrialError) as caught:
            trials.create_trial(
                company_id=company.id, country="SE", org_number=self.ORG,
                source=Trial.Source.SELF_SIGNUP,
            )
        self.assertEqual(caught.exception.reason, "trial_in_progress")
        self.assertEqual(Trial.objects.filter(company_id=company.id).count(), 1)


class TrialClockTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.company = self.make_company()
        self.trial = trials.create_trial(
            company_id=self.company.id, country="SE", org_number="5566778899",
            source=Trial.Source.SELF_SIGNUP,
        )

    def test_the_clock_starts_at_the_first_phone_activation_not_at_signup(self):
        self.assertEqual(self.trial.status, Trial.Status.PENDING)
        self.assertIsNone(self.trial.started_at)

        trials.start_trial(self.trial)
        self.trial.refresh_from_db()
        self.assertEqual(self.trial.status, Trial.Status.ACTIVE)
        self.assertIsNotNone(self.trial.started_at)
        self.assertAlmostEqual(
            (self.trial.ends_at - self.trial.started_at).days, trials.TRIAL_DAYS, delta=1
        )

    def test_starting_twice_does_not_move_the_end_date(self):
        trials.start_trial(self.trial)
        self.trial.refresh_from_db()
        first_end = self.trial.ends_at

        trials.start_trial(self.trial)
        self.trial.refresh_from_db()
        self.assertEqual(self.trial.ends_at, first_end)

    def test_every_trial_vehicle_shares_the_same_end_date(self):
        trials.start_trial(self.trial)
        self.trial.refresh_from_db()
        for index in range(3):
            vehicle = licensing.create_vehicle(
                company_id=self.company.id, plate=f"TRI{index:03d}"
            )
            licensing.create_license(
                company_id=self.company.id, vehicle=vehicle, base_county="12",
                status=License.Status.TRIAL, trial=self.trial,
            )
        ends = {
            license.trial.ends_at
            for license in License.objects.filter(trial=self.trial).select_related("trial")
        }
        self.assertEqual(len(ends), 1)

    def test_the_vehicle_limit_is_three(self):
        trials.start_trial(self.trial)
        for index in range(3):
            vehicle = licensing.create_vehicle(
                company_id=self.company.id, plate=f"TRI{index:03d}"
            )
            trials.assert_can_add_trial_vehicle(self.trial)
            licensing.create_license(
                company_id=self.company.id, vehicle=vehicle, base_county="12",
                status=License.Status.TRIAL, trial=self.trial,
            )
        with self.assertRaises(trials.TrialError) as caught:
            trials.assert_can_add_trial_vehicle(self.trial)
        self.assertEqual(caught.exception.reason, "trial_vehicle_limit")

    def test_reinstalling_the_app_does_not_restart_the_trial(self):
        """§2: ominstallation kräver nytt godkännande men återställer inte provtid."""
        trials.start_trial(self.trial)
        self.trial.refresh_from_db()
        first_end = self.trial.ends_at

        # Ominstallation = ny hemlighet på samma enhet. Provet rörs inte.
        trials.start_trial(self.trial)
        self.trial.refresh_from_db()
        self.assertEqual(self.trial.ends_at, first_end)


class TrialToPaymentTests(FleetTestCase):
    """§7: tre provbilar blir inte tre debiterade licenser utan beställning."""

    def setUp(self):
        super().setUp()
        self.company = self.make_company()
        self.make_subscription(self.company)
        self.trial = trials.create_trial(
            company_id=self.company.id, country="SE", org_number="5566778899",
            source=Trial.Source.SELF_SIGNUP,
        )
        trials.start_trial(self.trial)
        self.trial.refresh_from_db()
        self.plates = ["TRI001", "TRI002", "TRI003"]
        for plate in self.plates:
            vehicle = licensing.create_vehicle(company_id=self.company.id, plate=plate)
            licensing.create_license(
                company_id=self.company.id, vehicle=vehicle, base_county="12",
                status=License.Status.TRIAL, trial=self.trial,
            )

    def test_trial_vehicles_are_not_billable(self):
        self.assertEqual(trials.trial_vehicle_count(self.trial), 3)
        self.assertEqual(licensing.billable_license_count(self.company.id), 0)

    def test_an_ended_trial_without_an_order_charges_nothing(self):
        trials.end_trial(self.trial, reason="period_over", converted=False)
        self.assertEqual(licensing.billable_license_count(self.company.id), 0)
        self.assertEqual(
            License.objects.filter(status=License.Status.CANCELED).count(), 3
        )

    def test_the_customer_chooses_which_vehicles_continue(self):
        plan = orders.plan_change(
            self.company.id,
            add_vehicles=[orders.VehicleSpec(plate="TRI001", base_county="12")],
        )
        self.assertEqual(plan.new_licenses, 1)
        order = orders.create_order(self.company.id, plan)
        orders.mark_order_paid(order)

        self.assertEqual(licensing.billable_license_count(self.company.id), 1)
        self.trial.refresh_from_db()
        self.assertEqual(self.trial.status, Trial.Status.CONVERTED)

    def test_trial_vehicles_that_were_not_ordered_stop_at_the_conversion(self):
        """
        Annars hade de två bortvalda provbilarna fått gratis åtkomst så länge
        bolaget betalar för den tredje: provlicenser släpps igenom av
        åtkomstkontrollen, och en betald period finns ju.
        """
        plan = orders.plan_change(
            self.company.id,
            add_vehicles=[orders.VehicleSpec(plate="TRI001", base_county="12")],
        )
        orders.mark_order_paid(orders.create_order(self.company.id, plan))
        statuses = dict(
            License.objects.filter(company_id=self.company.id)
            .values_list("assignments__vehicle__plate", "status")
        )
        self.assertEqual(statuses["TRI001"], License.Status.ACTIVE)
        self.assertEqual(
            sorted(s for p, s in statuses.items() if p != "TRI001"),
            [License.Status.CANCELED, License.Status.CANCELED],
        )

    def test_cancelling_during_the_trial_ends_it_without_charge(self):
        """§8: uppsagt prov med tidigare betalningsgodkännande debiterar inte."""
        orders.cancel_subscription(self.company.id)
        self.trial.refresh_from_db()
        self.assertEqual(self.trial.status, Trial.Status.ENDED)
        self.assertEqual(licensing.billable_license_count(self.company.id), 0)


class SalesInviteTests(FleetTestCase):
    def test_an_invite_requires_a_documented_verified_contact(self):
        with self.assertRaises(trials.TrialError) as caught:
            trials.create_invite(
                created_by=uuid.uuid4(), country="SE", org_number="5566778899",
                company_name="Taxi AB", contact_name="Anna", contact_email="a@example.test",
                contact_phone="", verification_note="   ",
            )
        self.assertEqual(caught.exception.reason, "verification_note_required")

    def test_a_valid_invite_can_be_redeemed_once(self):
        invite, code = trials.create_invite(
            created_by=uuid.uuid4(), country="SE", org_number="5566778899",
            company_name="Taxi AB", contact_name="Anna", contact_email="a@example.test",
            contact_phone="0700000000", verification_note="Ringde växeln, bekräftat av VD.",
        )
        found = trials.find_invite(code)
        self.assertEqual(str(found.id), str(invite.id))

        company = self.make_company()
        trials.consume_invite(found, company_id=company.id)
        with self.assertRaises(trials.TrialError):
            trials.find_invite(code)

    def test_an_expired_invite_is_refused(self):
        _invite, code = trials.create_invite(
            created_by=uuid.uuid4(), country="SE", org_number="5566778899",
            company_name="Taxi AB", contact_name="Anna", contact_email="a@example.test",
            contact_phone="", verification_note="Bekräftat per telefon.",
        )
        SalesInvite.objects.all().update(expires_at=timezone.now() - timedelta(hours=1))
        with self.assertRaises(trials.TrialError) as caught:
            trials.find_invite(code)
        self.assertEqual(caught.exception.reason, "invite_expired")

    def test_the_invite_code_is_stored_hashed(self):
        _invite, code = trials.create_invite(
            created_by=uuid.uuid4(), country="SE", org_number="5566778899",
            company_name="Taxi AB", contact_name="Anna", contact_email="a@example.test",
            contact_phone="", verification_note="Bekräftat per telefon.",
        )
        self.assertFalse(SalesInvite.objects.filter(code_hash=code).exists())
        self.assertEqual(SalesInvite.objects.count(), 1)

    def test_a_card_free_trial_does_not_require_a_payment_method(self):
        invite, _code = trials.create_invite(
            created_by=uuid.uuid4(), country="SE", org_number="5566778899",
            company_name="Taxi AB", contact_name="Anna", contact_email="a@example.test",
            contact_phone="", verification_note="Bekräftat per telefon.",
        )
        company = self.make_company()
        trial = trials.create_trial(
            company_id=company.id, country="SE", org_number="5566778899",
            source=Trial.Source.SALES_INVITE, invite=invite, requires_payment_method=False,
        )
        self.assertFalse(trial.requires_payment_method)
