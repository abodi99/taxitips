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

    def test_commit_creates_checkout_with_trial_end_and_keeps_order_pending(self):
        stripe, sessions, creates = self._fake_checkout()
        with mock.patch("fleet.stripe_sync._client", return_value=stripe):
            order, info = commerce.commit_trial_continuation(
                self.company.id, self._plan(),
                created_by=self.owner.user_id,
                success_url="https://taxitips.se/portal?ok=1",
                cancel_url="https://taxitips.se/portal?cancel=1",
            )
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)
        self.assertTrue((order.request or {}).get("trial_commit"))
        self.assertTrue(info["paymentUrl"].startswith("https://checkout.stripe.test/"))
        session = list(sessions.values())[0]
        self.assertEqual(session["metadata"]["kind"], "trial_commit")
        self.assertTrue(order.stripe_checkout_session_id)
        sub_data = creates[0].get("subscription_data") or {}
        self.assertEqual(sub_data.get("trial_end"), int(self.trial.ends_at.timestamp()))

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
