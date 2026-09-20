"""
Beställningar, uppgraderingar, minskningar, uppsägning och betalningsfrist.

Varje test här motsvarar en punkt i uppdragets §11 -- de fall där ett fel
antingen ger en kund gratis åtkomst eller debiterar någon två gånger.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from fleet import access, licensing, orders, pricing
from fleet.models import (
    License,
    LicenseCounty,
    Order,
    PendingChange,
    Subscription,
    SubscriptionStatus,
    VehicleSession,
)
from fleet.tests.base import FleetTestCase, price_version


class UpgradePaymentTests(FleetTestCase):
    """§8: uppgradering ger nya rättigheter först när betalningen lyckats."""

    def setUp(self):
        super().setUp()
        self.data = self.full_setup(county="12")
        self.company = self.data["company"]
        self.license = self.data["license"]

    def _order_extra_county(self, county="01"):
        plan = orders.plan_change(
            self.company.id,
            add_counties=[{"licenseId": str(self.license.id), "county": county}],
        )
        return plan, orders.create_order(self.company.id, plan)

    def test_pending_payment_grants_nothing(self):
        plan, order = self._order_extra_county()
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)
        self.assertGreater(order.total_now_ore, 0)
        self.assertEqual(access.license_counties(self.license.id), ("12",))

    def test_failed_payment_grants_nothing_and_takes_nothing(self):
        _plan, order = self._order_extra_county()
        orders.mark_order_failed(order, reason="card_declined")

        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.FAILED)
        self.assertEqual(access.license_counties(self.license.id), ("12",))
        # Den befintliga betalda åtkomsten är orörd.
        self.assertEqual(
            access.company_window(self.company.id).reason, "paid_period"
        )

    def test_successful_payment_activates_the_county(self):
        _plan, order = self._order_extra_county()
        orders.mark_order_paid(order)
        self.assertEqual(access.license_counties(self.license.id), ("01", "12"))

    def test_paying_twice_does_not_apply_twice(self):
        """§11: en lyckad betalning debiteras inte dubbelt vid återförsök."""
        _plan, order = self._order_extra_county()
        orders.mark_order_paid(order)
        orders.mark_order_paid(order)
        orders.mark_order_paid(order)

        self.assertEqual(
            LicenseCounty.objects.filter(
                license=self.license, county_code="01", active_to__isnull=True
            ).count(),
            1,
        )

    def test_identical_orders_in_the_same_minute_are_one_order(self):
        plan_a, order_a = self._order_extra_county()
        _plan_b, order_b = self._order_extra_county()
        self.assertEqual(str(order_a.id), str(order_b.id))
        self.assertEqual(Order.objects.filter(company_id=self.company.id).count(), 1)


class VolumeBoundaryOrderTests(FleetTestCase):
    """§11: volymändring 9 <-> 10 ger rätt åtkomst, belopp och ikraftträdande."""

    def setUp(self):
        super().setUp()
        self.company = self.make_company()
        self.make_subscription(self.company, days_left=15)
        self.licenses = []
        for i in range(9):
            _vehicle, license = self.make_license(self.company, plate=f"AAA{i:03d}")
            self.licenses.append(license)

    def test_adding_the_tenth_charges_the_difference_not_the_full_price(self):
        plan = orders.plan_change(
            self.company.id,
            add_vehicles=[orders.VehicleSpec(plate="ZZZ999", base_county="12")],
        )
        self.assertEqual(plan.current_licenses, 9)
        self.assertEqual(plan.new_licenses, 10)
        self.assertEqual(plan.quote.next_period.amount_ore, 10 * 74900)
        # Hälften av perioden kvar; mellanskillnaden är 299 kr/mån.
        self.assertLess(plan.quote.now.amount_ore, 74900)

        order = orders.create_order(self.company.id, plan)
        orders.mark_order_paid(order)
        self.assertEqual(licensing.billable_license_count(self.company.id), 10)

    def test_dropping_to_nine_takes_effect_at_the_next_renewal(self):
        _vehicle, tenth = self.make_license(self.company, plate="ZZZ999")
        self.assertEqual(licensing.billable_license_count(self.company.id), 10)

        plan = orders.plan_change(self.company.id, cancel_license_ids=[str(tenth.id)])
        self.assertFalse(plan.immediate)
        self.assertEqual(plan.quote.now.total_ore, 0)
        self.assertEqual(plan.quote.next_period.amount_ore, 9 * 79900)

        order = orders.create_order(self.company.id, plan)
        self.assertEqual(order.status, Order.Status.SCHEDULED)

        # Licensen fungerar till periodens slut.
        tenth.refresh_from_db()
        self.assertEqual(tenth.status, License.Status.PENDING_CANCEL)
        self.assertEqual(licensing.billable_license_count(self.company.id), 10)

        subscription = Subscription.objects.get(company_id=self.company.id)
        after = subscription.current_period_end + timedelta(minutes=1)
        orders.apply_pending_changes(self.company.id, now=after)

        tenth.refresh_from_db()
        self.assertEqual(tenth.status, License.Status.CANCELED)
        self.assertEqual(licensing.billable_license_count(self.company.id), 9)


class BaseCountyChangeTests(FleetTestCase):
    """§5: byte av baslän gäller nästa förnyelse; behövs länet nu köps ett tillägg."""

    def setUp(self):
        super().setUp()
        self.data = self.full_setup(county="12")
        self.company = self.data["company"]
        self.license = self.data["license"]

    def test_immediate_need_buys_an_extra_and_schedules_the_change(self):
        plan = orders.plan_change(
            self.company.id,
            base_county_changes=[
                {"licenseId": str(self.license.id), "county": "01", "immediate": True}
            ],
        )
        self.assertTrue(plan.immediate)
        self.assertGreater(plan.quote.now.total_ore, 0)

        order = orders.create_order(self.company.id, plan)
        orders.mark_order_paid(order)

        # Nu: båda länen, eftersom tillägget är betalt.
        self.assertEqual(access.license_counties(self.license.id), ("01", "12"))
        self.license.refresh_from_db()
        self.assertEqual(self.license.scheduled_base_county, "01")

    def test_at_renewal_the_redundant_extra_is_removed(self):
        """Ingen ska betala för samma län två gånger efter bytet (§5)."""
        plan = orders.plan_change(
            self.company.id,
            base_county_changes=[
                {"licenseId": str(self.license.id), "county": "01", "immediate": True}
            ],
        )
        orders.mark_order_paid(orders.create_order(self.company.id, plan))

        subscription = Subscription.objects.get(company_id=self.company.id)
        after = subscription.current_period_end + timedelta(minutes=1)
        orders.apply_pending_changes(self.company.id, now=after)

        self.license.refresh_from_db()
        self.assertEqual(self.license.base_county, "01")
        self.assertEqual(self.license.scheduled_base_county, "")
        # Bara EN aktiv rad för 01, och den är baslänet.
        rows = LicenseCounty.objects.filter(
            license=self.license, county_code="01"
        ).exclude(active_to__lte=after)
        self.assertEqual(rows.count(), 1)
        self.assertEqual(rows.first().kind, LicenseCounty.Kind.BASE)
        self.assertEqual(licensing.extra_county_count(self.company.id, after), 0)

    def test_removing_an_extra_county_takes_effect_at_the_next_renewal(self):
        licensing.activate_extra_county(license=self.license, county_code="01")
        self.assertEqual(access.license_counties(self.license.id), ("01", "12"))

        plan = orders.plan_change(
            self.company.id,
            remove_counties=[{"licenseId": str(self.license.id), "county": "01"}],
        )
        orders.create_order(self.company.id, plan)

        # Kvar till periodens slut.
        self.assertEqual(access.license_counties(self.license.id), ("01", "12"))

        subscription = Subscription.objects.get(company_id=self.company.id)
        after = subscription.current_period_end + timedelta(minutes=1)
        self.assertEqual(access.license_counties(self.license.id, after), ("12",))


class CancellationTests(FleetTestCase):
    """§8: uppsägning stoppar nästa period men behåller betald åtkomst."""

    def setUp(self):
        super().setUp()
        self.data = self.full_setup()
        self.company = self.data["company"]
        self.subscription = self.data["subscription"]

    def test_access_survives_until_the_paid_period_ends(self):
        change = orders.cancel_subscription(self.company.id)
        self.subscription.refresh_from_db()
        self.assertTrue(self.subscription.cancel_at_period_end)
        self.assertEqual(self.subscription.access_until, self.subscription.current_period_end)
        self.assertEqual(change.effective_at, self.subscription.current_period_end)

        window = access.company_window(self.company.id)
        self.assertTrue(window.ok)

    def test_no_extra_grace_after_the_period(self):
        """Ingen ytterligare 30-dagarsfrist, inget obligatoriskt supportsamtal."""
        orders.cancel_subscription(self.company.id)
        self.subscription.refresh_from_db()
        after = self.subscription.current_period_end + timedelta(minutes=1)
        orders.apply_pending_changes(self.company.id, now=after)
        self.assertFalse(access.company_window(self.company.id, after).ok)

    def test_cancellation_supersedes_other_scheduled_changes(self):
        """§9: en uppsägning får inte lämna en annan schemalagd förnyelse aktiv."""
        _vehicle, second = self.make_license(self.company, plate="BBB222")
        plan = orders.plan_change(self.company.id, cancel_license_ids=[str(second.id)])
        orders.create_order(self.company.id, plan)
        self.assertEqual(
            PendingChange.objects.filter(status=PendingChange.Status.PENDING).count(), 1
        )

        orders.cancel_subscription(self.company.id)
        self.assertEqual(
            PendingChange.objects.filter(
                status=PendingChange.Status.PENDING,
                kind=PendingChange.Kind.CANCEL_SUBSCRIPTION,
            ).count(),
            1,
        )
        self.assertEqual(
            PendingChange.objects.filter(
                status=PendingChange.Status.PENDING,
            ).exclude(kind=PendingChange.Kind.CANCEL_SUBSCRIPTION).count(),
            0,
        )

    def test_cancellation_works_during_the_intro_period(self):
        now = timezone.now()
        Subscription.objects.filter(id=self.subscription.id).update(
            intro_started_at=now - timedelta(days=10), intro_ends_at=now + timedelta(days=80)
        )
        change = orders.cancel_subscription(self.company.id)
        self.assertIsNotNone(change)
        self.subscription.refresh_from_db()
        # Introduktionshistoriken behålls.
        self.assertIsNotNone(self.subscription.intro_started_at)

    def test_undo_restores_the_subscription_and_keeps_history(self):
        now = timezone.now()
        Subscription.objects.filter(id=self.subscription.id).update(
            intro_started_at=now - timedelta(days=10), intro_ends_at=now + timedelta(days=80)
        )
        orders.cancel_subscription(self.company.id)
        orders.undo_cancellation(self.company.id)

        self.subscription.refresh_from_db()
        self.assertFalse(self.subscription.cancel_at_period_end)
        self.assertIsNone(self.subscription.access_until)
        self.assertIsNotNone(self.subscription.intro_started_at)
        self.assertEqual(
            PendingChange.objects.filter(status=PendingChange.Status.PENDING).count(), 0
        )

    def test_undo_after_the_end_date_is_refused(self):
        orders.cancel_subscription(self.company.id)
        Subscription.objects.filter(id=self.subscription.id).update(
            access_until=timezone.now() - timedelta(days=1)
        )
        self.subscription.refresh_from_db()
        with self.assertRaises(orders.OrderError) as caught:
            orders.undo_cancellation(self.company.id)
        self.assertEqual(caught.exception.reason, "cancellation_final")

    def test_applied_cancellation_ends_driver_sessions(self):
        from fleet import sessions

        sessions.start_session(
            device_id=self.data["device"].id, license_id=self.data["license"].id
        )
        orders.cancel_subscription(self.company.id)
        self.subscription.refresh_from_db()
        after = self.subscription.current_period_end + timedelta(minutes=1)
        orders.apply_pending_changes(self.company.id, now=after)

        self.assertFalse(
            VehicleSession.objects.filter(
                license=self.data["license"], ended_at__isnull=True
            ).exists()
        )


class GracePeriodTests(FleetTestCase):
    """§8: högst sju dagar, från ursprunglig förfallotid, aldrig förlängd."""

    def setUp(self):
        super().setUp()
        self.company = self.make_company()
        self.subscription = self.make_subscription(self.company, days_left=-1)

    def test_a_previous_payer_gets_seven_days_from_the_original_due_time(self):
        due = self.subscription.current_period_end
        orders.start_grace(self.subscription, due_at=due)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.grace_origin, due)
        self.assertEqual(self.subscription.grace_until, due + timedelta(days=orders.GRACE_DAYS))

    def test_retries_never_extend_the_grace(self):
        due = self.subscription.current_period_end
        orders.start_grace(self.subscription, due_at=due)
        self.subscription.refresh_from_db()
        first = self.subscription.grace_until

        for days in (1, 2, 3):
            later = timezone.now() + timedelta(days=days)
            orders.start_grace(self.subscription, due_at=later, now=later)
            self.subscription.refresh_from_db()
            self.assertEqual(self.subscription.grace_until, first)

    def test_first_failure_after_a_free_trial_gets_no_grace_at_all(self):
        Subscription.objects.filter(id=self.subscription.id).update(
            had_successful_payment=False
        )
        self.subscription.refresh_from_db()
        orders.start_grace(self.subscription, due_at=self.subscription.current_period_end)
        self.subscription.refresh_from_db()
        self.assertIsNone(self.subscription.grace_until)
        self.assertEqual(self.subscription.status, SubscriptionStatus.PAST_DUE)
        self.assertFalse(access.company_window(self.company.id).ok)

    def test_access_survives_during_the_grace_and_stops_after(self):
        due = self.subscription.current_period_end
        orders.start_grace(self.subscription, due_at=due)
        self.subscription.refresh_from_db()

        during = due + timedelta(days=3)
        self.assertTrue(access.company_window(self.company.id, during).ok)
        after = due + timedelta(days=orders.GRACE_DAYS, minutes=1)
        self.assertFalse(access.company_window(self.company.id, after).ok)

    def test_renewal_is_stopped_after_the_grace_expires(self):
        """§8: nya månadsfordringar ska inte fortsätta växa efter avstängning."""
        due = self.subscription.current_period_end
        orders.start_grace(self.subscription, due_at=due)
        self.subscription.refresh_from_db()

        from django.core.management import call_command
        from io import StringIO

        Subscription.objects.filter(id=self.subscription.id).update(
            grace_until=timezone.now() - timedelta(hours=1)
        )
        out = StringIO()
        call_command("fleet_tick", stdout=out)
        self.subscription.refresh_from_db()
        self.assertIsNotNone(self.subscription.renewal_stopped_at)
        self.assertTrue(self.subscription.cancel_at_period_end)


class IntroContinuityTests(FleetTestCase):
    """§6: senare tillagda bilar får bara företagets återstående introduktionstid."""

    def test_a_later_vehicle_shares_the_company_intro_window(self):
        now = timezone.now()
        company = self.make_company()
        subscription = self.make_subscription(company, days_left=15)
        Subscription.objects.filter(id=subscription.id).update(
            intro_started_at=now - timedelta(days=60), intro_ends_at=now + timedelta(days=30)
        )
        subscription.refresh_from_db()
        self.make_license(company, plate="AAA111")

        plan = orders.plan_change(
            company.id, add_vehicles=[orders.VehicleSpec(plate="BBB222", base_county="12")]
        )
        # Introduktionspriset gäller båda bilarna och tar slut samtidigt.
        self.assertTrue(pricing.intro_active(subscription, now))
        self.assertEqual(plan.quote.next_period.amount_ore, 2 * 69900)

        after_intro = subscription.intro_ends_at + timedelta(days=1)
        self.assertFalse(pricing.intro_active(subscription, after_intro))

    def test_cancelling_and_returning_does_not_restart_the_campaign(self):
        now = timezone.now()
        company = self.make_company()
        subscription = self.make_subscription(company)
        Subscription.objects.filter(id=subscription.id).update(
            intro_started_at=now - timedelta(days=50), intro_ends_at=now + timedelta(days=40)
        )
        subscription.refresh_from_db()
        original_end = subscription.intro_ends_at

        orders.cancel_subscription(company.id)
        orders.undo_cancellation(company.id)
        # En ny lyckad betalning rör inte ett redan satt fönster.
        orders.record_successful_payment(
            subscription, period_start=now, period_end=now + timedelta(days=30), now=now
        )
        subscription.refresh_from_db()
        self.assertEqual(subscription.intro_ends_at, original_end)
