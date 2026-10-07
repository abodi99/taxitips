"""
Beställningar, uppgraderingar, minskningar, uppsägning och betalningsfrist.

Varje test här motsvarar en punkt i uppdragets §11 -- de fall där ett fel
antingen ger en kund gratis åtkomst eller debiterar någon två gånger.
"""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.utils import timezone

from fleet import access, commerce, licensing, orders, pricing, stripe_sync
from fleet.models import (
    AuditEvent,
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


class ReuseUnpaidOrderTests(FleetTestCase):
    """
    §11: en avbruten betalning är samma korg. Nästa försök ska ge tillbaka
    samma order -- inte en ny rad i portalen.

    Prod hade tre identiska obetalda `add_license`-ordrar för samma bolag
    (15:06, 19:01, 19:20): kunden avbröt betalningen i Stripe och försökte
    igen, och idempotensnyckeln bär minuten, så varje försök blev en egen
    order. Portalen visade en trave "väntar på betalning" för samma ändring.
    """

    def setUp(self):
        super().setUp()
        self.data = self.full_setup(county="12")
        self.company = self.data["company"]
        self.license = self.data["license"]

    def _plan(self, *, now=None):
        return orders.plan_change(
            self.company.id,
            add_counties=[{"licenseId": str(self.license.id), "county": "01"}],
            now=now,
        )

    def test_a_new_attempt_the_next_minute_reuses_the_unpaid_order(self):
        plan = self._plan()
        first = orders.create_order(self.company.id, plan)
        self.assertEqual(first.status, Order.Status.PENDING_PAYMENT)

        # Fem minuter senare är idempotensnyckeln en annan, så det är bara
        # återanvändningen som kan ge samma order tillbaka.
        later = timezone.now() + timedelta(minutes=5)
        with mock.patch("fleet.orders.timezone.now", return_value=later):
            second = orders.create_order(self.company.id, plan)

        self.assertEqual(str(first.id), str(second.id))
        self.assertEqual(Order.objects.filter(company_id=self.company.id).count(), 1)
        # Ordern skapades EN gång: revisionsloggen ska visa beställningen, inte
        # varje avbrutet försök (och portalen ska visa en betallänk, inte tre).
        self.assertEqual(
            AuditEvent.objects.filter(action="order_created", subject_id=first.id).count(), 1
        )

    def test_a_changed_amount_is_a_new_order(self):
        # Samma ändring, men proportioneringen -- och därmed beloppet -- har
        # ändrats. Att återanvända den gamla ordern hade debiterat fel summa,
        # så beloppet måste vara identiskt för att en order får återanvändas.
        first_plan = self._plan()
        first = orders.create_order(self.company.id, first_plan)

        later = timezone.now() + timedelta(minutes=5)
        # Planen räknas tio dygn in i perioden (annat belopp), men klockan som
        # create_order ser är fem minuter fram -- åldersfönstret är alltså inte
        # det som avgör, utan beloppet.
        second_plan = self._plan(now=later + timedelta(days=10))
        self.assertNotEqual(first_plan.quote.now.total_ore, second_plan.quote.now.total_ore)
        with mock.patch("fleet.orders.timezone.now", return_value=later):
            second = orders.create_order(self.company.id, second_plan)

        self.assertNotEqual(str(first.id), str(second.id))
        self.assertEqual(Order.objects.filter(company_id=self.company.id).count(), 2)

    def test_an_unpaid_order_older_than_a_day_is_not_reused(self):
        # En order från en tidigare period eller ett tidigare pris är inte
        # samma korg och ska inte tyst återuppstå.
        plan = self._plan()
        first = orders.create_order(self.company.id, plan)
        later = timezone.now() + timedelta(minutes=5)
        Order.objects.filter(id=first.id).update(
            created_at=later - orders.REUSE_PENDING_WITHIN - timedelta(minutes=1)
        )

        with mock.patch("fleet.orders.timezone.now", return_value=later):
            second = orders.create_order(self.company.id, plan)

        self.assertNotEqual(str(first.id), str(second.id))
        self.assertEqual(Order.objects.filter(company_id=self.company.id).count(), 2)

    def test_an_explicit_idempotency_key_is_never_reused(self):
        # En egen nyckel betyder "just det här försöket" -- anroparen har redan
        # bestämt vad som är samma beställning.
        plan = self._plan()
        first = orders.create_order(self.company.id, plan, idempotency="forsok-1")
        second = orders.create_order(self.company.id, plan, idempotency="forsok-2")

        self.assertNotEqual(str(first.id), str(second.id))
        self.assertEqual(Order.objects.filter(company_id=self.company.id).count(), 2)


class SupersededPendingOrderTests(FleetTestCase):
    """
    §11: en ny obetald order för samma ändring makulerar den äldre.

    Mätt i prod: portalen visade flera "väntar på betalning" för samma korg.
    Återanvändningen (find_reusable_order) räcker inte, för ett omedelbart
    tillägg mitt i en löpande period proportioneras per sekund -- två försök en
    minut isär får olika belopp, och då blir det en ny order varje gång.
    """

    def setUp(self):
        super().setUp()
        self.data = self.full_setup(county="12")
        self.company = self.data["company"]
        self.license = self.data["license"]

    def _place(self, company=None, license=None, *, now=None, clock=None):
        """
        Samma ändring via kundvägen (fleet/commerce.place_order).

        `now` går till prisberäkningen (proportioneringen), `clock` till
        idempotensnyckeln -- den bär minuten, så ett återförsök "en minut
        senare" måste flytta klockan för att bli ett nytt försök.
        """
        company = company or self.company
        license = license or self.license
        plan = orders.plan_change(
            company.id,
            add_counties=[{"licenseId": str(license.id), "county": "01"}],
            now=now,
        )
        # Stripe-nyckeln saknas i testmiljön; utan den vägrar place_order en
        # ändring som kostar något. Själva anropet faller sedan på att klienten
        # inte finns, vilket är samma läge som "Stripe svarade inte": ordern
        # ligger kvar som obetald, utan faktura.
        with mock.patch("fleet.commerce.stripe_sync.available", return_value=True), mock.patch(
            "fleet.orders.timezone.now", return_value=clock or timezone.now()
        ):
            return commerce.place_order(
                company.id, plan, created_by=self.data["owner"].user_id,
                actor_kind="customer",
            )

    def _pending(self):
        return Order.objects.filter(
            company_id=self.company.id, status=Order.Status.PENDING_PAYMENT
        )

    def test_a_new_order_with_another_amount_cancels_the_older(self):
        first, _ = self._place()
        self.assertEqual(first.status, Order.Status.PENDING_PAYMENT)
        self.assertGreater(first.total_now_ore, 0)

        # Tio dygn in i perioden är det mindre kvar att proportionera, alltså ett
        # annat belopp -- precis det som gjorde att den gamla ordern inte kunde
        # återanvändas.
        later = timezone.now() + timedelta(minutes=1)
        second, _ = self._place(now=later + timedelta(days=10), clock=later)

        self.assertNotEqual(str(first.id), str(second.id))
        self.assertEqual(second.status, Order.Status.PENDING_PAYMENT)
        self.assertNotEqual(first.total_now_ore, second.total_now_ore)

        first.refresh_from_db()
        self.assertEqual(first.status, Order.Status.CANCELED)
        self.assertIn("ersatt av en nyare beställning", first.failure_reason)
        # Exakt EN obetald order kvar för samma ändring: den nya.
        self.assertEqual(list(self._pending().values_list("id", flat=True)), [second.id])
        self.assertTrue(
            AuditEvent.objects.filter(action="order_canceled", subject_id=first.id).exists()
        )

    def test_a_reused_order_is_never_canceled_by_itself(self):
        """Samma belopp (ingen löpande period): återanvändningen ska stå kvar."""
        Subscription.objects.filter(company_id=self.company.id).update(
            current_period_start=None, current_period_end=None
        )
        first, _ = self._place()
        later = timezone.now() + timedelta(minutes=5)
        second, _ = self._place(clock=later)

        self.assertEqual(str(first.id), str(second.id))
        second.refresh_from_db()
        self.assertEqual(second.status, Order.Status.PENDING_PAYMENT)

    def test_a_stripe_failure_while_cancelling_does_not_block_the_new_order(self):
        first, _ = self._place()
        # En riktig faktura i Stripe, så att makuleringen faktiskt försöker
        # makulera något -- det är där felet uppstår.
        Order.objects.filter(id=first.id).update(stripe_invoice_id="in_supersede_1")

        later = timezone.now() + timedelta(minutes=1)
        with mock.patch(
            "fleet.commerce.stripe_sync.void_order_invoice",
            side_effect=stripe_sync.StripeUnavailable("Stripe svarar inte"),
        ):
            second, info = self._place(now=later + timedelta(days=10), clock=later)

        self.assertNotEqual(str(first.id), str(second.id))
        second.refresh_from_db()
        self.assertEqual(second.status, Order.Status.PENDING_PAYMENT)
        # Den gamla ligger kvar obetald -- support får makulera den för hand.
        first.refresh_from_db()
        self.assertEqual(first.status, Order.Status.PENDING_PAYMENT)
        self.assertTrue(
            AuditEvent.objects.filter(
                action="order_supersede_failed", subject_id=first.id
            ).exists()
        )
        # Den nya ordern hindrades inte av felet.
        self.assertIn(second.id, self._pending().values_list("id", flat=True))
        self.assertIn("stripeError", info)

    def test_a_paid_or_scheduled_order_is_never_touched(self):
        for status in (Order.Status.PAID, Order.Status.SCHEDULED):
            with self.subTest(status=status):
                # Eget bolag per varv: den gamla ordern skrivs om till en status
                # som inte är obetald och får sedan inte röras alls.
                data = self.full_setup(county="12", plate=f"SUP{status[:3]}")
                first, _ = self._place(data["company"], data["license"])
                Order.objects.filter(id=first.id).update(status=status)

                later = timezone.now() + timedelta(minutes=1)
                second, _ = self._place(
                    data["company"], data["license"],
                    now=later + timedelta(days=10), clock=later,
                )

                self.assertNotEqual(str(first.id), str(second.id))
                first.refresh_from_db()
                self.assertEqual(first.status, status)
                self.assertFalse(
                    AuditEvent.objects.filter(
                        action="order_canceled", subject_id=first.id
                    ).exists()
                )


