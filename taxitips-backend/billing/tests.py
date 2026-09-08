"""
Tester för faktureringsvägen: signatur, idempotens, statusuppdatering.

Vägen har funnits utan ett enda test därför att den bara gick att prova med
Stripe CLI och en riktig anslutning -- alltså provades den i praktiken
aldrig. En webhook som tyst slutar uppdatera `companies.status` ser ut som
ingenting alls, ända tills en betalande kund plötsligt inte ser några tips.

De omanagerade domäntabellerna skapas explicit här, av samma skäl som i
core/test_api.py: gränsen mellan Djangos tabeller och Supabases ska kosta en
rad att korsa, så att den märks.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid

from django.db import connection
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from billing.models import Company, Device, ProcessedWebhookEvent

SECRET = "whsec_test_secret"


@override_settings(STRIPE_WEBHOOK_SECRET=SECRET, CELERY_TASK_ALWAYS_EAGER=True)
class StripeWebhookTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.schema_editor() as editor:
            for model in (Company, Device, ProcessedWebhookEvent):
                editor.create_model(model)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as editor:
            for model in (ProcessedWebhookEvent, Device, Company):
                editor.delete_model(model)
        super().tearDownClass()

    def setUp(self):
        self.client = Client()
        self.company = Company.objects.create(
            id=uuid.uuid4(), name="Malmö Taxi AB", join_code="MALMO1", seats=25,
            status="active", subscription_status="active", created_at=timezone.now(),
            stripe_customer_id="cus_test_1", stripe_subscription_id="sub_test_1",
        )

    def event(self, event_type="customer.subscription.updated", status="active",
              quantity=25, event_id=None, metadata=None):
        if event_type == "checkout.session.completed":
            obj = {
                "id": "cs_1", "customer": "cus_test_1", "subscription": "sub_new",
                "metadata": metadata or {"company_id": str(self.company.id)},
            }
        else:
            obj = {
                "id": "sub_test_1", "customer": "cus_test_1", "status": status,
                "items": {"data": [{"quantity": quantity}]},
            }
        return {
            "id": event_id or f"evt_{uuid.uuid4().hex[:12]}",
            "object": "event", "created": int(time.time()),
            "type": event_type, "livemode": False, "data": {"object": obj},
        }

    def post(self, event, sign_with=SECRET):
        payload = json.dumps(event, separators=(",", ":"))
        ts = int(time.time())
        sig = hmac.new(sign_with.encode(), f"{ts}.{payload}".encode(), hashlib.sha256).hexdigest()
        return self.client.post(
            "/billing/stripe/webhook", data=payload,
            content_type="application/json",
            headers={"Stripe-Signature": f"t={ts},v1={sig}"},
        )

    def test_a_valid_event_updates_the_company(self):
        res = self.post(self.event(status="past_due", quantity=30))
        self.assertEqual(res.status_code, 200)
        self.company.refresh_from_db()
        self.assertEqual(self.company.status, "past_due")
        self.assertEqual(self.company.subscription_status, "past_due")
        self.assertEqual(self.company.seats, 30)

    def test_an_unsigned_event_is_refused(self):
        # Utan den här kontrollen kan vem som helst som når endpointen
        # aktivera sin egen prenumeration.
        res = self.post(self.event(), sign_with="whsec_fel_hemlighet")
        self.assertEqual(res.status_code, 400)
        self.company.refresh_from_db()
        self.assertEqual(self.company.status, "active")

    def test_the_same_event_twice_is_processed_once(self):
        # Stripe levererar om vid minsta osäkerhet. Utan idempotens skulle
        # en omleverans räknas som en ny händelse.
        event = self.event(status="past_due", event_id="evt_samma")
        self.assertEqual(self.post(event).status_code, 200)
        second = self.post(event)
        self.assertTrue(second.json().get("duplicate"))
        self.assertEqual(ProcessedWebhookEvent.objects.count(), 1)

    def test_a_deleted_subscription_cancels_the_company(self):
        self.post(self.event(event_type="customer.subscription.deleted"))
        self.company.refresh_from_db()
        self.assertEqual(self.company.status, "canceled")

    def test_checkout_finds_the_company_through_metadata(self):
        # Vid första köpet finns ingen kundkoppling ännu -- bolaget hittas
        # via metadata, inte via stripe_customer_id.
        self.company.stripe_customer_id = None
        self.company.status = "trial"
        self.company.save()
        self.post(self.event(event_type="checkout.session.completed"))
        self.company.refresh_from_db()
        self.assertEqual(self.company.status, "active")
        self.assertEqual(self.company.stripe_subscription_id, "sub_new")

    def test_an_unknown_customer_changes_nothing(self):
        event = self.event()
        event["data"]["object"]["customer"] = "cus_finns_inte"
        self.assertEqual(self.post(event).status_code, 200)
        self.company.refresh_from_db()
        self.assertEqual(self.company.seats, 25)

    def test_the_event_is_recorded_as_processed(self):
        event = self.event(event_id="evt_spårbar")
        self.post(event)
        row = ProcessedWebhookEvent.objects.get(stripe_event_id="evt_spårbar")
        self.assertEqual(row.status, "ok")
        self.assertEqual(row.event_type, "customer.subscription.updated")
