"""
Skickar en signerad Stripe-webhook till den lokala tjänsten.

Varför den finns: hela faktureringsvägen -- signaturkontroll, idempotens,
statusuppdatering, push -- gick bara att prova med Stripe CLI och en riktig
Stripe-anslutning. Det gjorde att den i praktiken aldrig provades, och en
webhook som tyst slutar uppdatera `companies.status` ser ut som ingenting
alls förrän en betalande kund plötsligt inte ser några tips.

Kommandot bygger en riktig event-payload, signerar den precis som Stripe
gör (`t=<tid>,v1=<hmac>`) och postar den till den lokala endpointen. Ingen
Stripe-anslutning behövs, och inget rörs i något riktigt Stripe-konto.

    python manage.py simulate_stripe_event --company "Malmö Taxi AB" --type customer.subscription.updated --status past_due
    python manage.py simulate_stripe_event --company "Malmö Taxi AB" --type customer.subscription.deleted
    python manage.py simulate_stripe_event --company "Taxi Tips Demo AB" --type checkout.session.completed

Kräver att `CELERY_TASK_ALWAYS_EAGER=1` är satt för tjänsten som tar emot,
annars läggs bara tasken på kön och ingenting händer förrän en worker kör.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from billing.models import Company

TYPES = [
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "checkout.session.completed",
    "invoice.payment_failed",
]


class Command(BaseCommand):
    help = "Postar en signerad Stripe-webhook mot den lokala tjänsten"

    def add_arguments(self, parser):
        parser.add_argument("--company", required=True, help="Bolagsnamn eller uuid")
        parser.add_argument("--type", default="customer.subscription.updated", choices=TYPES)
        parser.add_argument(
            "--status", default="active",
            help="Prenumerationsstatus i eventet: active, past_due, canceled, unpaid ...",
        )
        parser.add_argument("--quantity", type=int, default=None, help="Antal platser i eventet")
        parser.add_argument("--url", default="http://127.0.0.1:8000/billing/stripe/webhook")

    def handle(self, *args, **o):
        secret = settings.STRIPE_WEBHOOK_SECRET
        if not secret:
            raise CommandError(
                "STRIPE_WEBHOOK_SECRET saknas i .env. Lokalt duger vilken sträng "
                "som helst -- den delas bara mellan det här kommandot och vyn."
            )

        company = (
            Company.objects.filter(name=o["company"]).first()
            or Company.objects.filter(id=o["company"]).first()
        )
        if not company:
            raise CommandError(f"Hittar inget bolag som heter {o['company']!r}")
        if not company.stripe_customer_id and o["type"] != "checkout.session.completed":
            raise CommandError(
                f"{company.name} saknar stripe_customer_id -- webhooken hittar bolaget "
                "genom det fältet. Kör `manage.py seed_local_demo` först."
            )

        self.stdout.write(
            f"före:  {company.name}  status={company.status}  "
            f"prenumeration={company.subscription_status}  platser={company.seats}"
        )

        payload = json.dumps(self._event(company, o), separators=(",", ":"))
        timestamp = int(time.time())
        signature = hmac.new(
            secret.encode(), f"{timestamp}.{payload}".encode(), hashlib.sha256
        ).hexdigest()

        req = urllib.request.Request(
            o["url"],
            data=payload.encode(),
            headers={
                "Content-Type": "application/json",
                "Stripe-Signature": f"t={timestamp},v1={signature}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as res:
                body = res.read().decode()
                self.stdout.write(f"webhook: {res.status} {body}")
        except urllib.error.HTTPError as exc:
            raise CommandError(f"webhook {exc.code}: {exc.read().decode()[:300]}")
        except urllib.error.URLError as exc:
            raise CommandError(f"Nådde inte {o['url']}: {exc.reason}")

        company.refresh_from_db()
        self.stdout.write(self.style.SUCCESS(
            f"efter: {company.name}  status={company.status}  "
            f"prenumeration={company.subscription_status}  platser={company.seats}"
        ))

    def _event(self, company: Company, o: dict) -> dict:
        """Samma form som Stripe skickar. Bara fälten hanteraren läser."""
        now = int(time.time())
        event_id = f"evt_local_{uuid.uuid4().hex[:16]}"
        if o["type"] == "checkout.session.completed":
            obj = {
                "id": f"cs_local_{uuid.uuid4().hex[:12]}",
                "object": "checkout.session",
                "customer": company.stripe_customer_id or f"cus_local_{uuid.uuid4().hex[:10]}",
                "subscription": company.stripe_subscription_id or f"sub_local_{uuid.uuid4().hex[:10]}",
                # Hanteraren hittar bolaget via metadata här, inte via kunden --
                # vid första köpet finns ingen kundkoppling ännu.
                "metadata": {"company_id": str(company.id)},
            }
        elif o["type"] == "invoice.payment_failed":
            obj = {
                "id": f"in_local_{uuid.uuid4().hex[:12]}",
                "object": "invoice",
                "customer": company.stripe_customer_id,
                "subscription": company.stripe_subscription_id,
            }
        else:
            obj = {
                "id": company.stripe_subscription_id or f"sub_local_{uuid.uuid4().hex[:10]}",
                "object": "subscription",
                "customer": company.stripe_customer_id,
                "status": o["status"],
                "items": {
                    "data": [{
                        "id": f"si_local_{uuid.uuid4().hex[:10]}",
                        "quantity": o["quantity"] if o["quantity"] is not None else company.seats,
                    }]
                },
            }
        return {
            "id": event_id,
            "object": "event",
            "api_version": "2024-06-20",
            "created": now,
            "type": o["type"],
            "livemode": False,
            "data": {"object": obj},
        }
