"""
Prov → kort i portalen → auto-förnyelse (trial_commit).

Kort sparas via Checkout under Django-provet; debitering sker vid trial_end.
"""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.test import override_settings
from django.utils import timezone

from fleet import commerce, orders, stripe_sync, trials, webhook_events
from fleet.management.commands.fleet_tick import Command as FleetTick
from fleet.models import (
    CompanyProfile,
    License,
    Order,
    Subscription,
    SubscriptionStatus,
    Trial,
)
from fleet.tests.base import FleetTestCase


class Obj(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


@override_settings(STRIPE_SECRET_KEY="sk_test_x", STRIPE_ALLOW_LIVE="")
class TrialCommitTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.company = self.make_company(
            name="Prov Commit AB", org_number="5569999111", status="inactive",
        )
        self.owner = self.make_owner(self.company)
        self.trial = trials.create_trial(
            company_id=self.company.id, country="SE", org_number="5569999111",
            source=Trial.Source.SELF_SIGNUP, requires_payment_method=False,
        )
        vehicle, license = self.make_license(self.company, plate="COM123", county="12")
        License.objects.filter(id=license.id).update(
            status=License.Status.TRIAL, trial=self.trial,
        )
        now = timezone.now()
        Trial.objects.filter(id=self.trial.id).update(
            status=Trial.Status.ACTIVE,
            started_at=now - timedelta(days=7),
            ends_at=now + timedelta(days=7),
        )
        self.trial.refresh_from_db()
        orders.get_or_create_subscription(self.company.id)

    def _plan(self):
        return orders.plan_change(
            self.company.id,
            add_vehicles=[
                orders.VehicleSpec(plate="COM123", base_county="12", label="", extra_counties=[]),
            ],
        )

    def _fake_checkout(self):
        sessions = {}
        creates = []

        class Checkout:
            class Session:
                @staticmethod
                def create(**kw):
                    creates.append(kw)
                    sid = f"cs_{len(sessions) + 1}"
                    session = Obj(
                        id=sid,
                        url=f"https://checkout.stripe.test/{sid}",
                        customer=kw.get("customer"),
                        subscription=None,
                        payment_status="unpaid",
                        metadata=kw.get("metadata") or {},
                        object="checkout.session",
                    )
                    sessions[sid] = session
                    return session

        class Customer:
            @staticmethod
            def create(**kw):
                return Obj(id="cus_commit")

            @staticmethod
            def modify(*a, **kw):
                return Obj(id="cus_commit")

        class SubscriptionAPI:
            @staticmethod
            def retrieve(sub_id):
                return Obj(id=sub_id, status="trialing")

            @staticmethod
            def cancel(sub_id):
                return Obj(id=sub_id, status="canceled")

        stripe = mock.Mock()
        stripe.checkout = Checkout
        stripe.Customer = Customer
        stripe.Subscription = SubscriptionAPI
        return stripe, sessions, creates

    def test_commit_pays_now_in_checkout_without_a_stripe_trial(self):
        """Ägarens beslut 2026-10-11: en betalning via Stripe är aldrig ett prov."""
        stripe, sessions, creates = self._fake_checkout()
        with mock.patch("fleet.stripe_sync._client", return_value=stripe):
            order, info = commerce.commit_trial_continuation(
                self.company.id, self._plan(),
                created_by=self.owner.user_id,
                success_url="https://taxitips.se/portal?ok=1",
                cancel_url="https://taxitips.se/portal?cancel=1",
            )
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)
        self.assertFalse((order.request or {}).get("trial_commit"))
        self.assertTrue(info["paymentUrl"].startswith("https://checkout.stripe.test/"))
        self.assertIsNone(info["firstChargeAt"])
        session = list(sessions.values())[0]
        self.assertEqual(session["metadata"]["kind"], "subscription")
        self.assertTrue(order.stripe_checkout_session_id)
        sub_data = creates[0].get("subscription_data") or {}
        self.assertNotIn("trial_end", sub_data)
        # Kassan visar "Lägg till kampanjkod".
        self.assertIs(creates[0].get("allow_promotion_codes"), True)

    def test_an_old_unpaid_card_saving_checkout_is_replaced(self):
        stripe, sessions, creates = self._fake_checkout()
        old = self._commit_order()
        Order.objects.filter(id=old.id).update(
            stripe_checkout_session_id="cs_old", stripe_payment_url="https://checkout.stripe.test/cs_old",
        )
        stripe.checkout.Session.expire = mock.Mock()
        with mock.patch("fleet.stripe_sync._client", return_value=stripe):
            order, info = commerce.commit_trial_continuation(
                self.company.id, self._plan(), created_by=self.owner.user_id,
                success_url="https://taxitips.se/portal?ok=1",
                cancel_url="https://taxitips.se/portal?cancel=1",
            )
        old.refresh_from_db()
        self.assertEqual(old.status, Order.Status.CANCELED)
        stripe.checkout.Session.expire.assert_called_once_with("cs_old")
        self.assertNotEqual(info["paymentUrl"], "https://checkout.stripe.test/cs_old")

    def test_a_paid_checkout_applies_the_order_and_remembers_the_subscription(self):
        order = orders.create_order(
            self.company.id, self._plan(), created_by=self.owner.user_id, actor_kind="customer",
        )
        Order.objects.filter(id=order.id).update(stripe_checkout_session_id="cs_pay_1")
        session = {
            "object": "checkout.session", "id": "cs_pay_1", "payment_status": "paid",
            "customer": "cus_pay", "subscription": "sub_pay_1",
            "metadata": {"order_id": str(order.id), "company_id": str(self.company.id),
                         "kind": "subscription"},
        }
        with mock.patch("fleet.webhook_events._resync_amount"):
            result = webhook_events.handle("checkout.session.completed", session)
        self.assertEqual(result["action"], "payment_succeeded")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.APPLIED)
        sub = Subscription.objects.get(company_id=self.company.id)
        self.assertEqual((sub.stripe_subscription_id, sub.stripe_customer_id), ("sub_pay_1", "cus_pay"))
        self.trial.refresh_from_db()
        self.assertEqual(self.trial.status, Trial.Status.CONVERTED)

    def test_reconciling_a_paid_checkout_applies_the_order(self):
        """Webhooken kraschade i prod 2026-10-11: avstämningen ska kunna göra klart."""
        order = orders.create_order(
            self.company.id, self._plan(), created_by=self.owner.user_id, actor_kind="customer",
        )
        Order.objects.filter(id=order.id).update(stripe_checkout_session_id="cs_rec_1")
        order.refresh_from_db()
        session = {
            "object": "checkout.session", "id": "cs_rec_1", "status": "complete",
            "payment_status": "paid", "amount_total": 99875,
            "customer": "cus_rec", "subscription": "sub_rec_1",
            "metadata": {"order_id": str(order.id), "company_id": str(self.company.id)},
        }
        with mock.patch("fleet.stripe_sync.fetch_checkout_session", return_value=session), \
                mock.patch("fleet.webhook_events._resync_amount"):
            result = commerce.refresh_payment(order)
        self.assertEqual(result["orderStatus"], Order.Status.APPLIED)
        self.assertEqual(Subscription.objects.get(company_id=self.company.id).stripe_subscription_id, "sub_rec_1")
        self.trial.refresh_from_db()
        self.assertEqual(self.trial.status, Trial.Status.CONVERTED)

    def test_reconciling_a_paid_but_unapplied_order_finishes_it(self):
        order = orders.create_order(
            self.company.id, self._plan(), created_by=self.owner.user_id, actor_kind="customer",
        )
        Order.objects.filter(id=order.id).update(
            status=Order.Status.PAID, paid_at=timezone.now(), stripe_checkout_session_id="cs_rec_2",
        )
        order.refresh_from_db()
        session = {"object": "checkout.session", "id": "cs_rec_2", "status": "complete",
                   "payment_status": "paid", "metadata": {"order_id": str(order.id),
                                                           "company_id": str(self.company.id)}}
        with mock.patch("fleet.stripe_sync.fetch_checkout_session", return_value=session), \
                mock.patch("fleet.webhook_events._resync_amount"):
            result = commerce.refresh_payment(order)
        self.assertEqual(result["orderStatus"], Order.Status.APPLIED)

    def test_the_subscriptions_invoice_finds_the_order_through_its_metadata(self):
        order = orders.create_order(
            self.company.id, self._plan(), created_by=self.owner.user_id, actor_kind="customer",
        )
        Subscription.objects.filter(company_id=self.company.id).update(
            stripe_subscription_id="sub_meta", stripe_customer_id="cus_meta",
        )
        now = int(timezone.now().timestamp())
        invoice = {
            "object": "invoice", "id": "in_meta_1", "customer": "cus_meta", "subscription": "sub_meta",
            "amount_paid": 10000, "status": "paid", "billing_reason": "subscription_create",
            "metadata": {},
            "parent": {"subscription_details": {"metadata": {"order_id": str(order.id)}}},
            "lines": {"data": [{"type": "subscription", "subscription": "sub_meta",
                                "period": {"start": now, "end": now + 30 * 86400}}]},
        }
        with mock.patch("fleet.webhook_events._resync_amount"):
            webhook_events.handle("invoice.paid", invoice)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.APPLIED)

    def _commit_order(self):
        order = orders.create_order(
            self.company.id, self._plan(), created_by=self.owner.user_id, actor_kind="customer",
        )
        Order.objects.filter(id=order.id).update(
            request={**(order.request or {}), "trial_commit": True},
            status=Order.Status.PENDING_PAYMENT,
        )
        order.refresh_from_db()
        return order

    def _session(self, order, **extra):
        return {
            "object": "checkout.session", "id": "cs_disc_1",
            "payment_status": "no_payment_required", "customer": "cus_commit",
            "subscription": "sub_disc_1",
            "metadata": {"order_id": str(order.id), "company_id": str(self.company.id),
                         "kind": "trial_commit"},
            **extra,
        }

    def test_a_promotion_code_is_noted_and_stays_in_stripe(self):
        """
        Kupongen ligger kvar i Stripe, som sköter dess längd. I vår prismotor hade
        en kod på "3 månader" blivit för alltid: där räknas beloppet i Stripe inte
        om när en rabatt löper ut.
        """
        from fleet import discounts
        from fleet.models import AuditEvent

        order = self._commit_order()
        webhook_events.handle(
            "checkout.session.completed",
            self._session(order, total_details={"amount_discount": 5000},
                          discounts=[{"promotion_code": "promo_VAR20"}]),
        )
        self.assertIsNone(discounts.active_discount(self.company.id))
        event = AuditEvent.objects.get(action="promotion_code_used", company_id=self.company.id)
        self.assertEqual(event.detail["discount_ore"], 5000)
        self.assertEqual(event.detail["codes"], ["promo_VAR20"])

    def test_a_checkout_without_a_code_notes_nothing(self):
        from fleet.models import AuditEvent

        order = self._commit_order()
        webhook_events.handle("checkout.session.completed", self._session(order))
        self.assertFalse(AuditEvent.objects.filter(action="promotion_code_used").exists())

    def _zero_invoice(self, order, billing_reason):
        Subscription.objects.filter(company_id=self.company.id).update(
            stripe_subscription_id="sub_x", status=SubscriptionStatus.TRIALING,
            stripe_customer_id="cus_x",
        )
        now = int(timezone.now().timestamp())
        return {
            "object": "invoice", "id": f"in_zero_{billing_reason}", "customer": "cus_x",
            "subscription": "sub_x", "amount_paid": 0, "status": "paid",
            "billing_reason": billing_reason,
            "metadata": {"order_id": str(order.id), "company_id": str(self.company.id)},
            "lines": {"data": [{"type": "subscription", "subscription": "sub_x",
                                "period": {"start": now, "end": now + 30 * 86400}}]},
        }

    def test_the_trials_own_zero_invoice_activates_nothing(self):
        order = self._commit_order()
        result = webhook_events.handle("invoice.paid", self._zero_invoice(order, "subscription_create"))
        self.assertEqual(result["action"], "trial_commit_zero_invoice")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)

    def test_a_zero_invoice_after_the_trial_is_a_paid_period(self):
        """En kampanjkod på 100 %: fakturan efter provet är 0 kr men en riktig period."""
        order = self._commit_order()
        with mock.patch("fleet.webhook_events._resync_amount"):
            result = webhook_events.handle("invoice.paid", self._zero_invoice(order, "subscription_cycle"))
        self.assertEqual(result["action"], "payment_succeeded")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.APPLIED)

    def test_checkout_completed_saves_card_without_applying_order(self):
        order = orders.create_order(
            self.company.id, self._plan(), created_by=self.owner.user_id, actor_kind="customer",
        )
        Order.objects.filter(id=order.id).update(
            request={**(order.request or {}), "trial_commit": True},
            stripe_checkout_session_id="cs_test_1",
        )
        order.refresh_from_db()
        session = {
            "object": "checkout.session",
            "id": "cs_test_1",
            "payment_status": "no_payment_required",
            "customer": "cus_commit",
            "subscription": "sub_trialing_1",
            "metadata": {
                "order_id": str(order.id),
                "company_id": str(self.company.id),
                "kind": "trial_commit",
            },
        }
        result = webhook_events.handle("checkout.session.completed", session)
        self.assertEqual(result["action"], "trial_commit_card_saved")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)
        profile = CompanyProfile.objects.get(company_id=self.company.id)
        self.assertIsNotNone(profile.payment_method_verified_at)
        sub = Subscription.objects.get(company_id=self.company.id)
        self.assertEqual(sub.stripe_subscription_id, "sub_trialing_1")
        self.assertEqual(sub.status, SubscriptionStatus.TRIALING)

    def test_invoice_paid_after_trial_converts(self):
        order = orders.create_order(
            self.company.id, self._plan(), created_by=self.owner.user_id, actor_kind="customer",
        )
        Order.objects.filter(id=order.id).update(
            request={**(order.request or {}), "trial_commit": True},
            status=Order.Status.PENDING_PAYMENT,
        )
        Subscription.objects.filter(company_id=self.company.id).update(
            stripe_subscription_id="sub_x", status=SubscriptionStatus.TRIALING,
            stripe_customer_id="cus_x",
        )
        CompanyProfile.objects.filter(company_id=self.company.id).update(
            payment_method_verified_at=timezone.now(),
        )
        now = int(timezone.now().timestamp())
        invoice = {
            "object": "invoice",
            "id": "in_paid_1",
            "customer": "cus_x",
            "subscription": "sub_x",
            "amount_paid": order.next_period_amount_ore or order.amount_now_ore or 10000,
            "status": "paid",
            "metadata": {"order_id": str(order.id), "company_id": str(self.company.id)},
            "lines": {"data": [{
                "type": "subscription",
                "subscription": "sub_x",
                "period": {"start": now, "end": now + 30 * 86400},
            }]},
        }
        with mock.patch("fleet.webhook_events._resync_amount"):
            result = webhook_events.handle("invoice.paid", invoice)
        self.assertEqual(result["action"], "payment_succeeded")
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.APPLIED)
        self.trial.refresh_from_db()
        self.assertEqual(self.trial.status, Trial.Status.CONVERTED)
        lic = License.objects.get(trial=self.trial)
        self.assertEqual(lic.status, License.Status.ACTIVE)

    def test_tick_waits_when_card_on_file(self):
        order = orders.create_order(
            self.company.id, self._plan(), created_by=self.owner.user_id, actor_kind="customer",
        )
        Order.objects.filter(id=order.id).update(
            request={**(order.request or {}), "trial_commit": True},
        )
        Subscription.objects.filter(company_id=self.company.id).update(
            stripe_subscription_id="sub_wait", status=SubscriptionStatus.TRIALING,
        )
        CompanyProfile.objects.filter(company_id=self.company.id).update(
            payment_method_verified_at=timezone.now(),
        )
        Trial.objects.filter(id=self.trial.id).update(ends_at=timezone.now() - timedelta(hours=1))
        self.assertTrue(commerce.has_active_trial_commit(self.company.id))
        FleetTick().handle(dry_run=False)
        self.trial.refresh_from_db()
        self.assertEqual(self.trial.status, Trial.Status.ACTIVE)

    def test_tick_ends_without_charge_when_no_card(self):
        Trial.objects.filter(id=self.trial.id).update(ends_at=timezone.now() - timedelta(hours=1))
        FleetTick().handle(dry_run=False)
        self.trial.refresh_from_db()
        self.assertEqual(self.trial.status, Trial.Status.ENDED)

    def test_cancel_commit_clears_card_flag(self):
        order = orders.create_order(
            self.company.id, self._plan(), created_by=self.owner.user_id, actor_kind="customer",
        )
        Order.objects.filter(id=order.id).update(
            request={**(order.request or {}), "trial_commit": True},
        )
        Subscription.objects.filter(company_id=self.company.id).update(
            stripe_subscription_id="sub_c", status=SubscriptionStatus.TRIALING,
        )
        CompanyProfile.objects.filter(company_id=self.company.id).update(
            payment_method_verified_at=timezone.now(),
        )
        stripe, _, _ = self._fake_checkout()
        with mock.patch("fleet.stripe_sync._client", return_value=stripe):
            commerce.cancel_trial_commit(self.company.id, actor_user_id=self.owner.user_id)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.CANCELED)
        profile = CompanyProfile.objects.get(company_id=self.company.id)
        self.assertIsNone(profile.payment_method_verified_at)
