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


@shared_task(name="fleet.tasks.send_support_reply_push")
def send_support_reply_push(thread_id: str, message_id: str) -> dict:
    """
    Notis till användaren när supporten svarat.

    Går förbi förarens notisinställningar (paus, län, nivå): de gäller tips,
    och ett svar på en fråga användaren själv ställt är inte ett tips. Texten
    är början av svaret, så att det går att läsa utan att öppna appen.
    """
    from django.conf import settings

    from billing import fcm
    from fleet import support
    from fleet.models import SupportMessage, SupportThread

    thread = SupportThread.objects.filter(id=thread_id).first()
    message = SupportMessage.objects.filter(id=message_id, thread_id=thread_id).first()
    if thread is None or message is None:
        return {"sent": 0, "skipped": "missing"}
    devices = support.device_push_targets(thread)
    if not devices:
        return {"sent": 0, "skipped": "no_push_token"}

    service_account = fcm.load_service_account(
        getattr(settings, "FIREBASE_SERVICE_ACCOUNT_JSON", "") or ""
    )
    if not service_account:
        log.warning("fleet.support: FIREBASE_SERVICE_ACCOUNT_JSON saknas, ingen notis")
        return {"sent": 0, "skipped": "no_service_account"}
    try:
        access_token = fcm.get_access_token(service_account)
    except Exception as exc:
        log.warning("fleet.support: fcm-inloggningen misslyckades: %s", exc)
        return {"sent": 0, "error": "auth_failed"}

    preview = message.body if len(message.body) <= 140 else message.body[:137] + "…"
    sent = 0
    for device in devices:
        result = fcm.send_push(
            service_account, access_token, token=device.push_token,
            title="Svar från TaxiTips support", body=preview,
            data={"type": "support_reply", "threadId": str(thread.id)},
            collapse_key=f"support-{thread.id}",
        )
        if result.get("ok"):
            sent += 1
    return {"sent": sent, "devices": len(devices)}
