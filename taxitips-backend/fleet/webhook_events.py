"""
Stripe-händelser -> abonnemang och rättigheter.

Fyra regler som var och en är ett eget sätt att ge fel kund åtkomst:

1. **Ordningen är inte garanterad.** Stripe lovar ingen ordning, så en äldre
   händelse som kommer efter en nyare får inte skriva över den.
   `Subscription.last_stripe_event_at` är vakten -- samma lösning som
   edge-funktionens `last_subscription_event_at`.
2. **Dubbletter får inte verkställa två gånger.** Idempotensen ligger i
   `processed_webhook_events` (webhookvyn) OCH i `Order.paid_at` +
   `Order.status == applied` (här). Två lager, för att det första bara
   skyddar mot samma EVENT och det andra mot två olika event som beskriver
   samma betalning.
3. **En äldre betald faktura får inte återöppna ett avslutat abonnemang.**
   En faktura för en period som redan löpt ut bär inget nytt åtkomstlöfte.
4. **Klientens success-redirect aktiverar ingenting.** Den här modulen anropas
   bara av den signaturverifierade webhookvägen och av avstämningen.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone as dt_timezone

from django.utils import timezone

from billing.models import Company
from fleet import audit, notifications, orders
from fleet.models import Order, Subscription, SubscriptionStatus

log = logging.getLogger(__name__)


def _ts(value) -> datetime | None:
    if value in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=dt_timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def _subscription_for(obj: dict) -> Subscription | None:
    """Hittar abonnemanget från metadata, kundid eller prenumerationsid."""
    company_id = (obj.get("metadata") or {}).get("company_id")
    if company_id:
        found = Subscription.objects.filter(company_id=company_id).first()
        if found is not None:
            return found

    customer_id = obj.get("customer")
    if customer_id:
        found = Subscription.objects.filter(stripe_customer_id=customer_id).first()
        if found is not None:
            return found
        company = Company.objects.filter(stripe_customer_id=customer_id).first()
        if company is not None:
            return Subscription.objects.filter(company_id=company.id).first()

    subscription_id = obj.get("subscription")
    if isinstance(subscription_id, str) and subscription_id:
        return Subscription.objects.filter(stripe_subscription_id=subscription_id).first()
    return None


def _order_for(obj: dict) -> Order | None:
    order_id = (obj.get("metadata") or {}).get("order_id")
    if order_id:
        return Order.objects.filter(id=order_id).first()
    invoice_id = obj.get("id") if obj.get("object") == "invoice" else obj.get("invoice")
    if isinstance(invoice_id, str) and invoice_id:
        return Order.objects.filter(stripe_invoice_id=invoice_id).first()
    session_id = obj.get("id") if obj.get("object") == "checkout.session" else None
    if session_id:
        return Order.objects.filter(stripe_checkout_session_id=session_id).first()
    return None


def _paid_period(obj: dict) -> tuple[datetime | None, datetime | None]:
    """
    Perioden en betald faktura täcker.

    Abonnemangsradens `period` först: på en abonnemangsfaktura beskriver
    fakturans egna `period_start`/`period_end` något annat -- på den första
    fakturan är de samma tidpunkt, och vid en förnyelse är de den period som
    just TOG SLUT. Att läsa dem hade gett en period som slutar i samma sekund
    som den betalas, och kunden hade blivit utelåst av sin egen betalning.
    Fakturans egna fält används bara om de beskriver ett verkligt intervall.
    Ett intervall som slutar där det börjar är ingen period.
    """
    for line in ((obj.get("lines") or {}).get("data") or []):
        if line.get("type") not in (None, "subscription") and not line.get("subscription"):
            continue
        period = line.get("period") or {}
        start, end = _ts(period.get("start")), _ts(period.get("end"))
        if start and end and end > start:
            return start, end
    start, end = _ts(obj.get("period_start")), _ts(obj.get("period_end"))
    if start and end and end > start:
        return start, end
    return None, None


def _is_stale(subscription: Subscription, event_at: datetime | None) -> bool:
    if event_at is None or subscription.last_stripe_event_at is None:
        return False
    return event_at < subscription.last_stripe_event_at


def _touch(subscription: Subscription, event_at: datetime | None) -> None:
    if event_at is not None:
        Subscription.objects.filter(id=subscription.id).update(last_stripe_event_at=event_at)


def handle(event_type: str, obj: dict, *, event_created=None, now=None) -> dict:
    """
    Tar emot en verifierad händelse. Returnerar vad som gjordes, för loggen och
    för testerna -- ett tyst "ingenting hände" går inte att felsöka.
    """
    now = now or timezone.now()
    event_at = _ts(event_created)

    if event_type in (
        "checkout.session.completed", "checkout.session.async_payment_succeeded",
        "invoice.paid", "invoice.payment_succeeded",
    ):
        return _payment_succeeded(event_type, obj, event_at=event_at, now=now)
    if event_type in ("invoice.payment_failed", "checkout.session.async_payment_failed"):
        return _payment_failed(obj, event_at=event_at, now=now)
    if event_type in ("customer.subscription.updated", "customer.subscription.deleted"):
        return _subscription_changed(event_type, obj, event_at=event_at, now=now)
    return {"handled": False, "reason": "unhandled_event_type"}


def _payment_succeeded(event_type: str, obj: dict, *, event_at, now) -> dict:
    # Ett fördröjt betalsätt är 'unpaid' tills async_payment_succeeded. Att
    # aktivera på `completed` hade gett rättigheter för en betalning som ännu
    # inte gått igenom (§8).
    if obj.get("object") == "checkout.session":
        paid = obj.get("payment_status") in ("paid", "no_payment_required")
        if not paid:
            return {"handled": True, "action": "awaiting_payment"}

    subscription = _subscription_for(obj)
    if subscription is None:
        return {"handled": False, "reason": "unknown_subscription"}

    period_start, period_end = _paid_period(obj)

    # En äldre faktura får inte återöppna ett senare avslutat abonnemang.
    if subscription.status == SubscriptionStatus.CANCELED:
        access_until = subscription.access_until or subscription.current_period_end
        if access_until is not None and (period_end is None or period_end <= access_until):
            audit.record(
                "stripe_stale_invoice_ignored", company_id=subscription.company_id,
                actor_kind="system", subject_type="subscription", subject_id=subscription.id,
                detail={"event_type": event_type, "period_end": str(period_end)},
            )
            return {"handled": True, "action": "ignored_stale_invoice"}

    order = _order_for(obj)
    if order is not None:
        # Idempotent: `mark_order_paid` gör ingenting om ordern redan är betald.
        orders.mark_order_paid(order, now=now)

    if period_start and period_end:
        orders.record_successful_payment(
            subscription, period_start=period_start, period_end=period_end, now=now
        )
    else:
        Subscription.objects.filter(id=subscription.id).update(
            status=SubscriptionStatus.ACTIVE, had_successful_payment=True,
            grace_until=None, grace_origin=None,
        )
    subscription.refresh_from_db()
    orders.apply_pending_changes(subscription.company_id, now=now)
    _touch(subscription, event_at)
    if order is not None:
        # Den betalda ordern ändrade bilar eller län: nästa faktura i Stripe
        # ska följa med. Ett fel här får inte göra betalningen obokförd --
        # avstämningen fångar ett belopp som inte hann uppdateras.
        _resync_amount(subscription.company_id)
    return {
        "handled": True, "action": "payment_succeeded",
        "order_id": str(order.id) if order else None,
    }


def _resync_amount(company_id) -> None:
    from fleet import stripe_sync

    if not stripe_sync.available():
        return
    try:
        stripe_sync.sync_company_amount(company_id)
    except Exception:
        log.exception("fleet.webhook: kunde inte uppdatera månadsbeloppet för %s", company_id)
        audit.record(
            "stripe_amount_sync_failed", company_id=company_id, actor_kind="system",
            subject_type="company", subject_id=company_id, detail={},
        )


def _payment_failed(obj: dict, *, event_at, now) -> dict:
    subscription = _subscription_for(obj)
    if subscription is None:
        return {"handled": False, "reason": "unknown_subscription"}

    order = _order_for(obj)
    if order is not None and order.status in (Order.Status.PENDING_PAYMENT, Order.Status.DRAFT):
        # En misslyckad UPPGRADERING ger inga rättigheter -- och tar inga.
        orders.mark_order_failed(order, reason="stripe_payment_failed", now=now)
        _touch(subscription, event_at)
        return {"handled": True, "action": "upgrade_failed", "order_id": str(order.id)}

    due_at = _ts(obj.get("period_end")) or subscription.current_period_end
    orders.start_grace(subscription, due_at=due_at, now=now)
    subscription.refresh_from_db()
    notifications.payment_failed(subscription, grace_until=subscription.grace_until)
    _touch(subscription, event_at)
    return {
        "handled": True, "action": "grace_started",
        "grace_until": subscription.grace_until.isoformat() if subscription.grace_until else None,
    }


def _subscription_changed(event_type: str, obj: dict, *, event_at, now) -> dict:
    from fleet import stripe_sync

    subscription = _subscription_for(obj)
    if subscription is None:
        return {"handled": False, "reason": "unknown_subscription"}
    if _is_stale(subscription, event_at):
        return {"handled": True, "action": "ignored_out_of_order"}

    status = (
        SubscriptionStatus.CANCELED
        if event_type == "customer.subscription.deleted"
        else stripe_sync.map_stripe_status(obj.get("status"))
    )
    updates = {"status": status}

    period_end = _ts(obj.get("current_period_end"))
    period_start = _ts(obj.get("current_period_start"))
    if period_start:
        updates["current_period_start"] = period_start
    if period_end:
        updates["current_period_end"] = period_end
    if "cancel_at_period_end" in obj:
        updates["cancel_at_period_end"] = bool(obj.get("cancel_at_period_end"))

    if status == SubscriptionStatus.CANCELED:
        # Åtkomsten löper till betald periods slut -- ingen extra frist (§8).
        updates["access_until"] = (
            subscription.access_until or period_end or subscription.current_period_end or now
        )
        updates["renewal_stopped_at"] = subscription.renewal_stopped_at or now
    if status == SubscriptionStatus.ACTIVE:
        updates["grace_until"] = None
        updates["grace_origin"] = None

    Subscription.objects.filter(id=subscription.id).update(**updates)
    subscription.refresh_from_db()
    _touch(subscription, event_at)

    if status == SubscriptionStatus.CANCELED:
        orders.apply_pending_changes(subscription.company_id, now=now)

    audit.record(
        "stripe_subscription_synced", company_id=subscription.company_id, actor_kind="system",
        subject_type="subscription", subject_id=subscription.id,
        detail={"event_type": event_type, "status": status},
    )
    return {"handled": True, "action": "subscription_synced", "status": status}
