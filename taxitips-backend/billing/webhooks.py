"""
Stripe-webhook-mottagare. LOKAL, TEST-MODE ENDAST -- se billing/tasks.pys
docstring. Stripes dashboard pekar på taxitips-api/supabase/functions/
stripe-webhook/index.ts, inte hit; att faktiskt lägga om (peka om Stripes
webhook-URL, pensionera edge-funktionen) är ett separat, senare, uttryckligen
bekräftat produktionssteg.

Testas lokalt med Stripe CLI:
    stripe listen --forward-to localhost:8000/billing/stripe/webhook
    stripe trigger checkout.session.completed
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone as dt_timezone

import stripe
from django.conf import settings
from django.db import IntegrityError, transaction
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from billing.models import ProcessedWebhookEvent
from billing.tasks import process_stripe_event

log = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def stripe_webhook(request):
    payload = request.body
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except (ValueError, stripe.SignatureVerificationError) as exc:
        log.warning("billing: webhook-signatur ogiltig: %s", exc)
        return HttpResponse(f"Webhook Error: {exc}", status=400)

    # Idempotens: samma insert-innan-behandling-mönster som edge-funktionen --
    # en unik-krock på stripe_event_id betyder att Stripe levererat samma
    # event igen, och behandlas som redan klart.
    try:
        # atomic runt insert: en unik-krock markerar annars hela den
        # omgivande transaktionen som trasig, och nästa fråga i samma
        # request dör i stället för att omleveransen hanteras som det den
        # är. Osynligt i produktion idag (autocommit per request) men
        # verkligt i varje sammanhang som lägger en transaktion runt vyn --
        # ATOMIC_REQUESTS, ett test, en framtida wrapper.
        with transaction.atomic():
            ProcessedWebhookEvent.objects.create(
                stripe_event_id=event.id,
                event_type=event.type,
                processed_at=datetime.fromtimestamp(event.created, tz=dt_timezone.utc),
                status="processing",
            )
    except IntegrityError:
        return JsonResponse({"received": True, "duplicate": True})

    # event.data.object är en StripeObject (dict-subklass) -- dict(...) ger
    # en vanlig, JSON-serialiserbar dict att skicka som Celery-task-argument.
    process_stripe_event.delay(event.id, event.type, dict(event.data.object))
    return JsonResponse({"received": True})
