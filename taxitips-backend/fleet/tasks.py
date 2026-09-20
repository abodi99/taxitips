"""
Celery-tasks för kundlivscykeln.

`fleet_tick` körs en gång i timmen. Den är avsiktligt idempotent: varje steg
har ett villkor i sin egen fråga (`status=pending`, `effective_at__lte=now`,
`renewal_stopped_at__isnull=True`), så två körningar efter varandra gör inte
samma sak två gånger.

Avstämningen mot Stripe RAPPORTERAR bara. Att låta den rätta automatiskt hade
betytt att ett fel i endera riktningen sprider sig tyst (§9).
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.core.management import call_command

log = logging.getLogger(__name__)


@shared_task(name="fleet.tasks.fleet_tick")
def fleet_tick() -> dict:
    call_command("fleet_tick")
    return {"ok": True}


@shared_task(name="fleet.tasks.reconcile_stripe")
def reconcile_stripe(limit: int = 200) -> dict:
    """
    Jämför vår bild med Stripes och larmar på avvikelser.

    Utan Stripe-nyckel gör den ingenting och säger det -- en avstämning som
    tyst svarar "inga avvikelser" när den inte kunnat fråga är värre än ingen
    avstämning.
    """
    from fleet import stripe_sync
    from fleet.models import Subscription

    if not stripe_sync.available():
        return {"checked": 0, "skipped": "stripe_unavailable"}

    checked = 0
    discrepancies = []
    for subscription in Subscription.objects.exclude(stripe_subscription_id="")[:limit]:
        checked += 1
        try:
            found = stripe_sync.reconcile(subscription)
        except Exception as exc:
            log.warning("fleet: avstämning misslyckades för %s: %s", subscription.company_id, exc)
            continue
        discrepancies.extend(d.as_dict() for d in found)

    if discrepancies:
        log.error(
            "fleet: %d avvikelser mellan Stripe och appens rättigheter: %s",
            len(discrepancies), discrepancies[:10],
        )
    return {"checked": checked, "discrepancies": discrepancies}
