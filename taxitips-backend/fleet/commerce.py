"""
Beställning -> betalning -> Stripe, och uppsägning, samlat på ett ställe.

`fleet/orders.py` vet vad en ändring kostar och vad som ska hända när den är
betald, men den rör aldrig Stripe. `fleet/stripe_sync.py` pratar med Stripe
men vet inget om regler. Den här modulen är det tunna lagret emellan, och den
används av BÅDE kundportalen (fleet/api.py) och adminwebbens säljflöde
(fleet/admin_sales.py) -- två vägar till samma beställning ska inte kunna ta
betalt på två olika sätt.

**Rättigheter ges bara av en betalning som Stripe bekräftat.** Att skapa en
betallänk ändrar ingenting; webhooken (fleet/webhook_events.py) eller
avstämningen här (`refresh_payment`, som läser fakturans status från Stripes
API) verkställer ordern. Det finns ingen väg förbi: all betalning går genom
Stripe, så att varje krona som gett åtkomst har en faktura i Stripe och
avstämningen har något att stämma av mot. (Den tidigare "betald utanför
Stripe"-markeringen är borttagen av just det skälet.)

**Uppsägning hos oss går alltid igenom, även när Stripe inte går att nå.**
Kundens uppsägning får inte blockeras av ett nätverksfel. Svaret säger då
uttryckligen att Stripe INTE uppdaterades, och händelsen loggas, så att någon
kan säga upp där för hand -- annars hade Stripe fortsatt debitera ett
abonnemang kunden sagt upp.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from fleet import audit, orders, stripe_sync, trials
from fleet.models import (
    CompanyProfile,
    Order,
    PendingChange,
    Subscription,
    SubscriptionStatus,
    Trial,
)

log = logging.getLogger(__name__)

PAYMENT_CARD = "stripe_card"
PAYMENT_INVOICE = "stripe_invoice"
PAYMENT_CHOICES = (PAYMENT_CARD, PAYMENT_INVOICE)

_COLLECTION = {
    PAYMENT_CARD: "charge_automatically",
    PAYMENT_INVOICE: "send_invoice",
}


def _stripe_failure(exc: Exception) -> orders.OrderError:
    if isinstance(exc, stripe_sync.StripeUnavailable):
        return orders.OrderError(
            "stripe_unavailable",
            f"Stripe är inte kopplat här: {exc}",
            status=503,
        )
    message = getattr(exc, "user_message", None) or str(exc)
    return orders.OrderError(
        "stripe_error", f"Stripe svarade med ett fel: {message[:300]}", status=502
    )


# ---------------------------------------------------------------------------
# Beställning och betalning
# ---------------------------------------------------------------------------


def place_order(
    company_id,
    plan: orders.ChangePlan,
    *,
    created_by,
    actor_kind: str,
    payment: str = PAYMENT_CARD,
    days_until_due: int = 14,
    idempotency: str | None = None,
) -> tuple[Order, dict]:
    """
    Lägger beställningen och, om den kostar något nu, begär betalningen.

    `payment`:
    * `stripe_card` -- betalsida med kort; kortet sparas för förnyelserna.
    * `stripe_invoice` -- Stripe mejlar en faktura med förfallodag.

    Kostar ändringen något nu och Stripe inte är kopplat i miljön vägras
    beställningen innan något sparas: en order som inte går att betala hade
    bara väntat tills någon gav åtkomst på annat sätt. Svarar Stripe med ett
    fel (nätverk, tillfälligt) ligger ordern kvar som `pending_payment` --
    ingenting är ändrat -- och svaret säger varför; betallänken kan skapas igen.
    """
    if payment not in PAYMENT_CHOICES:
        raise orders.OrderError("invalid_payment", "Välj kort eller faktura via Stripe.")
    if plan.immediate and plan.quote.now.total_ore > 0 and not stripe_sync.available():
        raise _stripe_failure(stripe_sync.StripeUnavailable(stripe_sync.status()["reason"]))
    order = orders.create_order(
        company_id, plan, created_by=created_by, idempotency=idempotency, actor_kind=actor_kind
    )
    info = {"requested": False, "paymentUrl": order.stripe_payment_url or None, "stripeError": None}

    if order.status == Order.Status.PENDING_PAYMENT:
        try:
            info["paymentUrl"] = request_payment(
                order, payment=payment, days_until_due=days_until_due
            ) or None
            info["requested"] = True
        except orders.OrderError as exc:
            info["stripeError"] = {"reason": exc.reason, "message": exc.message}
    elif order.status in (Order.Status.SCHEDULED, Order.Status.APPLIED):
        # En minskning eller ett gratis tillägg: nästa faktura i Stripe ska
        # följa med redan nu, annars förnyas det gamla beloppet.
        resync_amount(company_id)
    order.refresh_from_db()
    return order, info


def request_payment(order: Order, *, payment: str = PAYMENT_CARD, days_until_due: int = 14) -> str:
    """Skapar (eller hämtar) betallänken för en order som väntar på betalning."""
    if payment not in _COLLECTION:
        raise orders.OrderError("invalid_payment", "Välj kort eller faktura.")
    if order.status != Order.Status.PENDING_PAYMENT:
        raise orders.OrderError(
            "order_not_payable", "Ordern väntar inte på betalning.", status=409,
            detail={"status": order.status},
        )
    try:
        return stripe_sync.collect_order(
            order, collection_method=_COLLECTION[payment], days_until_due=days_until_due
        )
    except (stripe_sync.StripeUnavailable, ValueError) as exc:
        if isinstance(exc, ValueError):
            raise orders.OrderError("order_not_payable", str(exc), status=409) from exc
        raise _stripe_failure(exc) from exc
    except Exception as exc:  # stripe.error.StripeError och nätverksfel
        log.exception("fleet.commerce: betalningen kunde inte begäras för order %s", order.id)
        raise _stripe_failure(exc) from exc


def refresh_payment(order: Order) -> dict:
    """
    Avstämning av EN order: läser fakturans status från Stripes API.

    Betald faktura verkställs genom exakt samma väg som webhooken, så att en
    missad eller försenad webhook inte lämnar kunden utan det hen betalat för.
    Idempotent -- en redan verkställd order rörs inte.
    """
    from fleet import webhook_events

    if not order.stripe_invoice_id:
        raise orders.OrderError("no_invoice", "Ordern har ingen faktura i Stripe.")
    try:
        invoice = stripe_sync.fetch_invoice(order.stripe_invoice_id)
    except Exception as exc:
        raise _stripe_failure(exc) from exc

    status = str(invoice.get("status") or "")
    if status == "paid":
        webhook_events.handle("invoice.paid", invoice)
    elif status in ("void", "uncollectible"):
        orders.mark_order_failed(order, reason=f"stripe_invoice_{status}")
    order.refresh_from_db()
    return {
        "invoiceStatus": status,
        "orderStatus": order.status,
        "amountDueOre": invoice.get("amount_due"),
        "amountPaidOre": invoice.get("amount_paid"),
        "paymentUrl": invoice.get("hosted_invoice_url") or order.stripe_payment_url or None,
    }


def cancel_order(order: Order, *, actor_user_id, reason: str = "") -> Order:
    """
    Avbryter en obetald order. Fakturan i Stripe makuleras, så att kunden
    inte kan betala för något som inte längre gäller.
    """
    if order.status not in (Order.Status.PENDING_PAYMENT, Order.Status.DRAFT):
        raise orders.OrderError(
            "order_not_cancelable", "Bara obetalda order kan avbrytas.", status=409,
            detail={"status": order.status},
        )
    if order.stripe_invoice_id:
        try:
            stripe_sync.void_order_invoice(order)
        except Exception as exc:
            raise _stripe_failure(exc) from exc
    Order.objects.filter(
        id=order.id, status__in=[Order.Status.PENDING_PAYMENT, Order.Status.DRAFT]
    ).update(status=Order.Status.CANCELED, failure_reason=(reason or "canceled")[:500])
    audit.record(
        "order_canceled", company_id=order.company_id, actor_user_id=actor_user_id,
        actor_kind="sales", subject_type="order", subject_id=order.id,
        detail={"reason": (reason or "")[:300]},
    )
    order.refresh_from_db()
    return order


def resync_amount(company_id) -> dict:
    """Månadsbeloppet i Stripe efter bilarna och länen hos oss. Kastar aldrig."""
    subscription = Subscription.objects.filter(company_id=company_id).first()
    return _stripe_step(
        subscription, lambda: stripe_sync.sync_company_amount(company_id), "amount_sync"
    )


# ---------------------------------------------------------------------------
# Prov → kort i portalen → auto-förnyelse
# ---------------------------------------------------------------------------


def pending_trial_commit_order(company_id) -> Order | None:
    """Väntande order märkt trial_commit (kort sparas / dragning vid provslut)."""
    for order in Order.objects.filter(
        company_id=company_id, status=Order.Status.PENDING_PAYMENT
    ).order_by("-created_at")[:10]:
        if (order.request or {}).get("trial_commit"):
            return order
    return None


def trial_commit_status(company_id) -> dict:
    """
    Tillståndet portalen och appen visar under provet: har kunden bekräftat
    bilarna och sparat kort?
    """
    order = pending_trial_commit_order(company_id)
    profile = CompanyProfile.objects.filter(company_id=company_id).first()
    card_on_file = bool(profile and profile.payment_method_verified_at)
    committed = order is not None
    return {
        "committed": committed,
        "cardOnFile": card_on_file,
        "paymentUrl": (order.stripe_payment_url or None) if order and not card_on_file else None,
        "orderId": str(order.id) if order else None,
        "firstChargeAt": None,  # fylls av anroparen från trial.ends_at
    }


def has_active_trial_commit(company_id) -> bool:
    """
    True när fleet_tick INTE ska avsluta provet utan debitering: kort är
    sparat och Stripe-abonnemanget väntar på trial_end.
    """
    order = pending_trial_commit_order(company_id)
    if order is None:
        return False
    profile = CompanyProfile.objects.filter(company_id=company_id).first()
    if not (profile and profile.payment_method_verified_at):
        return False
    subscription = Subscription.objects.filter(company_id=company_id).first()
    if subscription is None or not subscription.stripe_subscription_id:
        return False
    return subscription.status in (
        SubscriptionStatus.TRIALING, SubscriptionStatus.ACTIVE, SubscriptionStatus.NONE,
    )


def commit_trial_continuation(
    company_id,
    plan: orders.ChangePlan,
    *,
    created_by,
    success_url: str,
    cancel_url: str,
    idempotency: str | None = None,
) -> tuple[Order, dict]:
    """
    Bekräftar vilka provbilar som fortsätter och öppnar Stripe Checkout för
    att spara kort. Debitering sker vid Trial.ends_at via Stripe trial_end.
    """
    trial = trials.active_trial(company_id)
    if trial is None or trial.status != Trial.Status.ACTIVE or not trial.ends_at:
        raise orders.OrderError(
            "no_active_trial",
            "Det finns inget pågående prov att fortsätta.",
            status=409,
        )
    if not plan.request.get("addVehicles"):
        raise orders.OrderError(
            "vehicles_required", "Välj vilka bilar som ska fortsätta.", status=400,
        )
    existing = pending_trial_commit_order(company_id)
    if existing is not None and existing.stripe_payment_url:
        profile = CompanyProfile.objects.filter(company_id=company_id).first()
        if profile and profile.payment_method_verified_at:
            return existing, {
                "requested": False,
                "paymentUrl": None,
                "alreadyCommitted": True,
                "cardOnFile": True,
            }
        return existing, {
            "requested": True,
            "paymentUrl": existing.stripe_payment_url,
            "alreadyCommitted": True,
            "cardOnFile": False,
        }

    if not stripe_sync.available():
        raise _stripe_failure(stripe_sync.StripeUnavailable(stripe_sync.status()["reason"]))

    # Märk planen så webhooken vet att inte verkställa vid Checkout (0 kr).
    plan.request = {**(plan.request or {}), "trial_commit": True}
    # Idempotens inkluderar trial_commit så den inte krockar med en vanlig order.
    key = idempotency or (
        orders.idempotency_key(company_id, plan) + ":trial_commit"
    )[:64]

    order = orders.create_order(
        company_id, plan, created_by=created_by, idempotency=key, actor_kind="customer",
    )
    # create_order kan ha returnerat en befintlig utan trial_commit-flaggan.
    request = dict(order.request or {})
    if not request.get("trial_commit"):
        request["trial_commit"] = True
        Order.objects.filter(id=order.id).update(request=request)
        order.refresh_from_db()

    if order.status != Order.Status.PENDING_PAYMENT:
        # Gratisplan (0 kr) -- ovanligt; verkställ inte som deferred.
        raise orders.OrderError(
            "nothing_to_commit",
            "Det finns inget att betala för de här bilarna.",
            status=409,
        )

    try:
        url = stripe_sync.collect_trial_commit(
            order, trial_end=trial.ends_at,
            success_url=success_url, cancel_url=cancel_url,
        )
    except ValueError as exc:
        raise orders.OrderError("trial_commit_failed", str(exc), status=409) from exc
    except Exception as exc:
        log.exception("fleet.commerce: trial_commit misslyckades för %s", company_id)
        raise _stripe_failure(exc) from exc

    order.refresh_from_db()
    return order, {
        "requested": True,
        "paymentUrl": url or order.stripe_payment_url or None,
        "alreadyCommitted": False,
        "cardOnFile": False,
        "firstChargeAt": trial.ends_at.isoformat(),
    }


def cancel_trial_commit(company_id, *, actor_user_id) -> dict:
    """Ångrar auto-förnyelse före första dragningen: Stripe-sub + pending order."""
    order = pending_trial_commit_order(company_id)
    if order is None:
        raise orders.OrderError(
            "no_trial_commit", "Det finns ingen sparad fortsättning att ångra.", status=404,
        )
    subscription = Subscription.objects.filter(company_id=company_id).first()
    if subscription and subscription.stripe_subscription_id:
        try:
            stripe_sync.cancel_trial_commit_subscription(subscription)
        except Exception as exc:
            raise _stripe_failure(exc) from exc
    if order.stripe_invoice_id:
        try:
            stripe_sync.void_order_invoice(order)
        except Exception:
            log.exception("fleet.commerce: kunde inte voida invoice för trial_commit %s", order.id)
    Order.objects.filter(id=order.id).update(
        status=Order.Status.CANCELED, failure_reason="trial_commit_canceled",
    )
    CompanyProfile.objects.filter(company_id=company_id).update(
        payment_method_verified_at=None,
    )
    audit.record(
        "trial_commit_canceled", company_id=company_id, actor_user_id=actor_user_id,
        actor_kind="customer", subject_type="order", subject_id=order.id, detail={},
    )
    return {"ok": True, "canceledOrderId": str(order.id)}


# ---------------------------------------------------------------------------
# Uppsägning
# ---------------------------------------------------------------------------


def _stripe_step(subscription: Subscription | None, action, label: str) -> dict:
    """
    Kör ett Stripe-steg efter att vår egen ändring redan gjorts. Svaret säger
    alltid om Stripe uppdaterades.
    """
    if subscription is None or not subscription.stripe_subscription_id:
        return {"synced": True, "reason": "no_stripe_subscription"}
    if not stripe_sync.available():
        audit.record(
            "stripe_not_updated", company_id=subscription.company_id, actor_kind="system",
            subject_type="subscription", subject_id=subscription.id,
            detail={"step": label, "reason": "stripe_unavailable"},
        )
        return {
            "synced": False, "reason": "stripe_unavailable",
            "message": "Stripe är inte kopplat i den här miljön. Gör samma ändring i "
                       "Stripes dashboard, annars fortsätter Stripe som förut.",
        }
    try:
        action()
        return {"synced": True, "reason": ""}
    except Exception as exc:
        log.exception("fleet.commerce: Stripe-steget %s misslyckades", label)
        audit.record(
            "stripe_not_updated", company_id=subscription.company_id, actor_kind="system",
            subject_type="subscription", subject_id=subscription.id,
            detail={"step": label, "reason": "stripe_error", "error": str(exc)[:300]},
        )
        return {
            "synced": False, "reason": "stripe_error",
            "message": f"Stripe uppdaterades inte: {str(exc)[:200]}",
        }


def cancel_subscription(company_id, *, actor_user_id, actor_kind: str, reason: str = "") -> tuple:
    """Uppsägning till periodens slut, hos oss och i Stripe."""
    change = orders.cancel_subscription(
        company_id, actor_user_id=actor_user_id, reason=reason, actor_kind=actor_kind
    )
    subscription = Subscription.objects.filter(company_id=company_id).first()
    stripe_result = _stripe_step(
        subscription, lambda: stripe_sync.set_cancel_at_period_end(subscription, True),
        "cancel_at_period_end",
    )
    return change, stripe_result


def undo_cancellation(company_id, *, actor_user_id, actor_kind: str) -> tuple:
    subscription = orders.undo_cancellation(
        company_id, actor_user_id=actor_user_id, actor_kind=actor_kind
    )
    stripe_result = _stripe_step(
        subscription, lambda: stripe_sync.set_cancel_at_period_end(subscription, False),
        "undo_cancel",
    )
    return subscription, stripe_result


def terminate_now(company_id, *, actor_user_id, reason: str, now=None) -> dict:
    """
    Avslutar abonnemanget DIREKT: åtkomsten upphör nu, licenserna avslutas,
    aktiva förarpass stängs och Stripe slutar debitera. Ingen återbetalning
    görs här -- det är ett eget beslut i Stripe.

    Plattformens åtgärd (bedrägeri, avtalsbrott, kundens uttryckliga begäran),
    aldrig kundens egen väg: kunden säger upp till periodens slut (§8).
    """
    now = now or timezone.now()
    reason = (reason or "").strip()
    if not reason:
        raise orders.OrderError("reason_required", "Ange varför abonnemanget avslutas direkt.")

    with transaction.atomic():
        subscription = orders.get_or_create_subscription(company_id)
        PendingChange.objects.filter(
            company_id=company_id, status=PendingChange.Status.PENDING
        ).update(status=PendingChange.Status.SUPERSEDED, canceled_at=now)
        Subscription.objects.filter(id=subscription.id).update(
            status=SubscriptionStatus.CANCELED, cancel_at_period_end=False,
            canceled_at=now, access_until=now, renewal_stopped_at=now,
            grace_until=None, grace_origin=None,
        )
        orders._apply_cancellation(company_id, now=now)
        open_trial = Trial.objects.filter(
            company_id=company_id, status__in=[Trial.Status.PENDING, Trial.Status.ACTIVE]
        ).first()
        if open_trial is not None:
            trials.end_trial(open_trial, reason="terminated_by_platform", converted=False, now=now)
        Order.objects.filter(
            company_id=company_id, status=Order.Status.PENDING_PAYMENT, stripe_invoice_id=""
        ).update(status=Order.Status.CANCELED, failure_reason="terminated")
        audit.record(
            "subscription_terminated_now", company_id=company_id,
            actor_user_id=actor_user_id, actor_kind="platform_admin",
            subject_type="subscription", subject_id=subscription.id,
            detail={"reason": reason[:500]},
        )
    subscription.refresh_from_db()
    stripe_result = _stripe_step(
        subscription, lambda: stripe_sync.cancel_now(subscription), "cancel_now"
    )
    return {"stripe": stripe_result, "accessUntil": now.isoformat()}
