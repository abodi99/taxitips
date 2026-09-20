"""
Stripe-händelser: dubbletter, fel ordning, gamla fakturor och
success-redirects.

Ingen av de här händelserna kommer från en klient. Testerna matar
`fleet.webhook_events.handle` direkt -- signaturverifieringen och
idempotensen på händelse-id ligger i billing/webhooks.py och har egna tester
där.
"""

from __future__ import annotations

from datetime import timedelta

from django.test import Client
from django.utils import timezone

from fleet import access, licensing, orders, webhook_events
from fleet.models import LicenseCounty, Order, Subscription, SubscriptionStatus
from fleet.tests.base import FleetTestCase


def _epoch(dt) -> int:
    return int(dt.timestamp())


class SubscriptionSyncTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.company = self.make_company()
        self.subscription = self.make_subscription(self.company)
        Subscription.objects.filter(id=self.subscription.id).update(
            stripe_customer_id="cus_test_1", stripe_subscription_id="sub_test_1"
        )
        self.subscription.refresh_from_db()

    def _event(self, status="active", **extra):
        now = timezone.now()
        return {
            "object": "subscription", "id": "sub_test_1", "customer": "cus_test_1",
            "status": status,
            "current_period_start": _epoch(now - timedelta(days=5)),
            "current_period_end": _epoch(now + timedelta(days=25)),
            **extra,
        }

    def test_a_status_change_is_mirrored(self):
        result = webhook_events.handle(
            "customer.subscription.updated", self._event("past_due"),
            event_created=_epoch(timezone.now()),
        )
        self.assertEqual(result["action"], "subscription_synced")
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, SubscriptionStatus.PAST_DUE)

    def test_an_older_event_arriving_later_does_not_overwrite_a_newer_one(self):
        """§9: Stripe lovar ingen ordning."""
        now = timezone.now()
        webhook_events.handle(
            "customer.subscription.updated", self._event("active"),
            event_created=_epoch(now),
        )
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, SubscriptionStatus.ACTIVE)

        result = webhook_events.handle(
            "customer.subscription.updated", self._event("past_due"),
            event_created=_epoch(now - timedelta(minutes=10)),
        )
        self.assertEqual(result["action"], "ignored_out_of_order")
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, SubscriptionStatus.ACTIVE)

    def test_deletion_keeps_access_until_the_paid_period_ends(self):
        now = timezone.now()
        webhook_events.handle(
            "customer.subscription.deleted", self._event("canceled"),
            event_created=_epoch(now),
        )
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, SubscriptionStatus.CANCELED)
        # Slutdatumet kommer ur händelsen, inte ur vad vi trodde innan: det är
        # Stripe som vet vilken period kunden faktiskt betalat för.
        self.assertIsNotNone(self.subscription.access_until)
        self.assertTrue(access.company_window(self.company.id).ok)
        self.assertFalse(
            access.company_window(
                self.company.id, self.subscription.access_until + timedelta(minutes=1)
            ).ok
        )

    def test_an_unknown_status_never_becomes_active(self):
        webhook_events.handle(
            "customer.subscription.updated", self._event("paused"),
            event_created=_epoch(timezone.now()),
        )
        self.subscription.refresh_from_db()
        self.assertNotEqual(self.subscription.status, SubscriptionStatus.ACTIVE)


class OrderPaymentEventTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.data = self.full_setup(county="12")
        self.company = self.data["company"]
        self.license = self.data["license"]
        Subscription.objects.filter(company_id=self.company.id).update(
            stripe_customer_id="cus_test_1", stripe_subscription_id="sub_test_1"
        )
        plan = orders.plan_change(
            self.company.id,
            add_counties=[{"licenseId": str(self.license.id), "county": "01"}],
        )
        self.order = orders.create_order(self.company.id, plan)
        Order.objects.filter(id=self.order.id).update(stripe_invoice_id="in_test_1")
        self.order.refresh_from_db()

    def _invoice(self, **extra):
        now = timezone.now()
        return {
            "object": "invoice", "id": "in_test_1", "customer": "cus_test_1",
            "subscription": "sub_test_1",
            "metadata": {"order_id": str(self.order.id)},
            "period_start": _epoch(now),
            "period_end": _epoch(now + timedelta(days=30)),
            **extra,
        }

    def test_a_paid_invoice_activates_the_purchased_county(self):
        webhook_events.handle(
            "invoice.paid", self._invoice(), event_created=_epoch(timezone.now())
        )
        self.assertEqual(access.license_counties(self.license.id), ("01", "12"))

    def test_the_same_invoice_delivered_twice_activates_once(self):
        """§11: en lyckad betalning debiteras inte dubbelt vid återförsök."""
        for _ in range(3):
            webhook_events.handle(
                "invoice.paid", self._invoice(), event_created=_epoch(timezone.now())
            )
        self.assertEqual(
            LicenseCounty.objects.filter(
                license=self.license, county_code="01", active_to__isnull=True
            ).count(),
            1,
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.APPLIED)

    def test_a_failed_upgrade_invoice_grants_nothing(self):
        webhook_events.handle(
            "invoice.payment_failed", self._invoice(), event_created=_epoch(timezone.now())
        )
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, Order.Status.FAILED)
        self.assertEqual(access.license_counties(self.license.id), ("12",))
        # Den befintliga betalda åtkomsten är orörd.
        self.assertTrue(access.company_window(self.company.id).ok)

    def test_a_delayed_checkout_session_does_not_activate_before_payment(self):
        """§8: väntande bankgodkännande ger ingen extra åtkomst."""
        session = {
            "object": "checkout.session", "id": "cs_test_1", "customer": "cus_test_1",
            "subscription": "sub_test_1", "payment_status": "unpaid",
            "metadata": {"order_id": str(self.order.id), "company_id": str(self.company.id)},
        }
        result = webhook_events.handle(
            "checkout.session.completed", session, event_created=_epoch(timezone.now())
        )
        self.assertEqual(result["action"], "awaiting_payment")
        self.assertEqual(access.license_counties(self.license.id), ("12",))

        session["payment_status"] = "paid"
        webhook_events.handle(
            "checkout.session.async_payment_succeeded", session,
            event_created=_epoch(timezone.now()),
        )
        self.assertEqual(access.license_counties(self.license.id), ("01", "12"))


class StaleInvoiceTests(FleetTestCase):
    """§9: en äldre betald faktura får inte återöppna ett senare avslutat abonnemang."""

    def setUp(self):
        super().setUp()
        self.company = self.make_company()
        self.subscription = self.make_subscription(self.company)
        Subscription.objects.filter(id=self.subscription.id).update(
            stripe_customer_id="cus_test_1", stripe_subscription_id="sub_test_1"
        )
        self.subscription.refresh_from_db()

    def test_an_old_invoice_does_not_reactivate_a_cancelled_subscription(self):
        now = timezone.now()
        orders.cancel_subscription(self.company.id, now=now)
        self.subscription.refresh_from_db()
        after = (self.subscription.access_until or now) + timedelta(days=1)
        orders.apply_pending_changes(self.company.id, now=after)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, SubscriptionStatus.CANCELED)

        old_invoice = {
            "object": "invoice", "id": "in_old", "customer": "cus_test_1",
            "subscription": "sub_test_1",
            "period_start": _epoch(now - timedelta(days=40)),
            "period_end": _epoch(now - timedelta(days=10)),
        }
        result = webhook_events.handle(
            "invoice.paid", old_invoice, event_created=_epoch(now - timedelta(days=10))
        )
        self.assertEqual(result["action"], "ignored_stale_invoice")
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.status, SubscriptionStatus.CANCELED)
        self.assertFalse(access.company_window(self.company.id, after).ok)


class SuccessRedirectTests(FleetTestCase):
    """§9: aktivering får inte lita på klientens success-redirect."""

    def test_no_endpoint_activates_from_a_client_callback(self):
        from django.urls import get_resolver

        patterns = [str(p.pattern) for p in get_resolver().url_patterns]
        # Det finns ingen "betalningen lyckades"-väg att anropa från webbläsaren.
        self.assertNotIn("api/fleet/paid", patterns)

    def test_the_company_overview_reports_server_state_not_a_claim(self):
        data = self.full_setup()
        client = Client()
        # Utan giltig JWT finns ingen väg att säga "jag har betalat".
        response = client.post(
            "/api/fleet/orders",
            data='{"accepted": true, "addVehicles": []}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)
