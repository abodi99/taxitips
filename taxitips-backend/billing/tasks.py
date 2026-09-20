"""
Stripe-webhook -> Celery-task -> FCM-push. Grenlogiken i process_stripe_event
är en 1:1-port av taxitips-api/supabase/functions/stripe-webhook/index.ts --
den funktionen är fortfarande den enda produktionskopplade hanteraren
(Stripes dashboard pekar dit, inte hit). Det här är en andra, lokal
implementation som visar hela vägen på riktigt (verifiering, idempotens,
uppdatering, push) utan att röra det som redan är live.

send_billing_push är en NY, egen notiskategori -- inte samma sak som
worker/src/fcmPush.js:s förar-opportunity-larm. Se modulens docstring
längre ner för varför den går till ALLA företagets enheter, inte bara
"ägaren".
"""

from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings

from billing.fcm import get_access_token, load_service_account, send_push
from billing.models import Company, Device, ProcessedWebhookEvent

log = logging.getLogger(__name__)

# customer.subscription.updated/deleted:s status -> companies.status.
# Speglar edge-funktionens mapped-uttryck exakt.
_STATUS_MAP = {
    "active": "active",
    "past_due": "past_due",
    "canceled": "canceled",
    "unpaid": "canceled",
    "incomplete_expired": "canceled",
}

_PUSH_TITLES = {
    "checkout.session.completed": "Betalning mottagen",
    "customer.subscription.updated": "Prenumeration uppdaterad",
    "customer.subscription.deleted": "Prenumeration avslutad",
    "invoice.payment_failed": "Betalning misslyckades",
}


@shared_task(name="billing.tasks.process_stripe_event")
def process_stripe_event(
    event_id: str, event_type: str, object_payload: dict, event_created=None
) -> None:
    try:
        _handle_event(event_type, object_payload)
        # Kundlivscykeln: abonnemang, beställningar, betalningsfrist och
        # väntande ändringar. Ligger i fleet/webhook_events.py och inte här,
        # eftersom den här modulen är en 1:1-port av edge-funktionen och ska
        # gå att jämföra rad för rad med den.
        from fleet import webhook_events

        webhook_events.handle(event_type, object_payload, event_created=event_created)
    except Exception as exc:
        log.exception("billing: %s misslyckades för %s", event_type, event_id)
        ProcessedWebhookEvent.objects.filter(stripe_event_id=event_id).update(
            status="error", error=str(exc)[:500]
        )
        return

    ProcessedWebhookEvent.objects.filter(stripe_event_id=event_id).update(status="ok")

    company_id = _company_id_for(event_type, object_payload)
    if company_id and event_type in _PUSH_TITLES:
        send_billing_push.delay(str(company_id), event_type)


def _handle_event(event_type: str, obj: dict) -> None:
    if event_type == "checkout.session.completed":
        company_id = (obj.get("metadata") or {}).get("company_id")
        subscription_id = obj.get("subscription")
        if company_id and subscription_id:
            Company.objects.filter(id=company_id).update(
                stripe_subscription_id=subscription_id,
                subscription_status="active",
                status="active",
            )
    elif event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
        customer_id = obj.get("customer")
        status = "canceled" if event_type == "customer.subscription.deleted" else obj.get("status")
        items = ((obj.get("items") or {}).get("data")) or []
        quantity = items[0].get("quantity") if items else None

        company = Company.objects.filter(stripe_customer_id=customer_id).first()
        if company:
            update_fields = {
                "subscription_status": status,
                "status": _STATUS_MAP.get(status, "inactive"),
            }
            if quantity:
                update_fields["seats"] = quantity
            Company.objects.filter(id=company.id).update(**update_fields)


def _company_id_for(event_type: str, obj: dict) -> str | None:
    if event_type == "checkout.session.completed":
        return (obj.get("metadata") or {}).get("company_id")
    customer_id = obj.get("customer")
    if not customer_id:
        return None
    company = Company.objects.filter(stripe_customer_id=customer_id).first()
    return str(company.id) if company else None


@shared_task(name="billing.tasks.send_billing_push")
def send_billing_push(company_id: str, event_type: str) -> dict:
    """
    Faktureringslivscykel-notiser -- en annan kategori än förarnas
    opportunity-larm (som fortfarande bara fcmPush.js skickar, se
    core/tasks.py:s "utanför scope"-kommentar).

    Går till ALLA enheter under företaget, inte bara "ägaren": devices.kind
    skiljer idag bara 'shared' från förartelefon (dashboard.js:84) -- det
    finns ingen ägare/admin-enhetstyp i produktion. En riktig
    ägare/admin-enhetstyp är en förutsättning för att göra det här snävare;
    tills den finns är hela företagets enhetskrets den enda mottagarkrets
    som existerar.
    """
    service_account_info = load_service_account(settings.FIREBASE_SERVICE_ACCOUNT_JSON)
    if not service_account_info:
        log.warning("billing: FIREBASE_SERVICE_ACCOUNT_JSON saknas, hoppar över push")
        return {"sent": 0, "skipped": "no_service_account"}

    devices = list(Device.objects.filter(company_id=company_id, push_token__isnull=False))
    if not devices:
        return {"sent": 0}

    try:
        access_token = get_access_token(service_account_info)
    except Exception as exc:
        log.warning("billing: fcm auth misslyckades: %s", exc)
        return {"sent": 0, "error": "auth_failed"}

    title = _PUSH_TITLES.get(event_type, "TaxiTips")
    sent = 0
    for device in devices:
        result = send_push(
            service_account_info,
            access_token,
            token=device.push_token,
            title=title,
            body="Se detaljer i webbportalen.",
            data={"event_type": event_type},
        )
        if result["ok"]:
            sent += 1
        elif result.get("status") in (404, 400):
            Device.objects.filter(id=device.id).update(push_token=None)
        else:
            log.warning("billing: push misslyckades för enhet %s: %s", device.id, result)
    return {"sent": sent}
