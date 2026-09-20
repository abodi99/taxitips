"""
Stripe: kund, abonnemang, engångsdebiteringar och avstämning.

**Varför beloppen räknas här och inte av Stripe.** Prismodellen har tre lager
(volymnivå, introduktionspris, länstillägg) och en proportionering som måste gå
att förklara rad för rad. Stripes egen proration räknar om på sitt sätt, och då
hade fakturan och det kunden godkände kunnat skilja sig åt. Därför:

* Abonnemanget i Stripe är EN post med `price_data` och vårt uträknade
  månadsbelopp. Antalet bilar ligger i metadata, inte i `quantity`.
* Varje uppgradering mitt i perioden debiteras som en EGEN engångspost med vårt
  proportionerade belopp, och prenumerationen uppdateras med
  `proration_behavior="none"` så att Stripe inte lägger på sin egen.
* Inga `subscription schedules`. En uppsägning ska inte behöva leta rätt på och
  avbryta ett schema först -- det var precis den fällan §9 pekar ut.

**Aktivering litar aldrig på klientens success-redirect.** Rättigheter sätts
bara av `billing/webhooks`-vägen eller av en avstämning som läst status från
Stripes API. En användare som öppnar `?paid=1` får ett svar från servern om vad
servern faktiskt vet, inte en aktivering.

**Ingen körning mot produktionen.** Modulen vägrar arbeta mot en livenyckel om
inte `STRIPE_ALLOW_LIVE=1` är satt. Uppdraget som byggde den här koden fick inte
röra riktiga kundabonnemang, och spärren är billigare än en ursäkt.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone

from billing.models import Company
from fleet import audit
from fleet.models import Order, Subscription, SubscriptionStatus

log = logging.getLogger(__name__)


class StripeUnavailable(Exception):
    """Ingen nyckel konfigurerad, eller livenyckel utan uttryckligt tillstånd."""


def _client():
    import stripe

    key = getattr(settings, "STRIPE_SECRET_KEY", "") or ""
    if not key:
        raise StripeUnavailable("STRIPE_SECRET_KEY saknas.")
    live = key.startswith("sk_live_") or key.startswith("rk_live_")
    if live and str(getattr(settings, "STRIPE_ALLOW_LIVE", "")) != "1":
        raise StripeUnavailable(
            "Livenyckel utan STRIPE_ALLOW_LIVE=1. Vägrar röra riktiga abonnemang."
        )
    stripe.api_key = key
    return stripe


def available() -> bool:
    try:
        _client()
        return True
    except StripeUnavailable:
        return False


def _vat_tax_rates() -> list[str]:
    """
    Momssatsen i Stripe, som ett `TaxRate`-id.

    Konfigureras med `STRIPE_VAT_TAX_RATE_ID`. Är den tom skickas inga
    skattesatser, och fakturan i Stripe visar beloppet EXKLUSIVE moms -- ett
    läge som inte får gå i produktion. `check_billing_config` larmar om det.
    """
    rate = getattr(settings, "STRIPE_VAT_TAX_RATE_ID", "") or ""
    return [rate] if rate else []


def ensure_customer(company: Company, subscription: Subscription) -> str:
    """
    En Stripe Customer per företag. Läser befintligt id först, från båda
    hållen (`companies.stripe_customer_id` och vår egen rad), så att en
    dubblett inte kan uppstå för att de två kommit isär.
    """
    stripe = _client()
    existing = subscription.stripe_customer_id or (company.stripe_customer_id or "")
    if existing:
        if not subscription.stripe_customer_id:
            Subscription.objects.filter(id=subscription.id).update(stripe_customer_id=existing)
        return existing

    customer = stripe.Customer.create(
        email=company.email or None,
        name=company.name,
        metadata={"company_id": str(company.id), "org_number": company.org_number or ""},
        idempotency_key=f"customer:{company.id}",
    )
    Subscription.objects.filter(id=subscription.id).update(stripe_customer_id=customer.id)
    Company.objects.filter(id=company.id).update(stripe_customer_id=customer.id)
    return customer.id


@dataclass(frozen=True)
class SyncResult:
    subscription_id: str
    amount_ore: int
    created: bool


def sync_subscription_amount(
    subscription: Subscription, *, monthly_amount_ore: int, licenses: int, extra_counties: int
) -> SyncResult:
    """
    Speglar det uträknade månadsbeloppet till Stripe.

    `proration_behavior="none"`: proportioneringen är redan debiterad som en
    egen post (se `charge_order`). Utan flaggan hade Stripe lagt på sin egen
    och kunden fått betala tillägget två gånger.
    """
    stripe = _client()
    company = Company.objects.get(id=subscription.company_id)
    customer_id = ensure_customer(company, subscription)
    price = subscription.price_version

    item = {
        "price_data": {
            "currency": price.currency.lower(),
            "product": getattr(settings, "STRIPE_PRODUCT_ID", "") or None,
            "unit_amount": monthly_amount_ore,
            "recurring": {"interval": "month"},
        },
        "quantity": 1,
        "tax_rates": _vat_tax_rates() or None,
    }
    item["price_data"] = {k: v for k, v in item["price_data"].items() if v is not None}
    item = {k: v for k, v in item.items() if v is not None}

    metadata = {
        "company_id": str(subscription.company_id),
        "licenses": str(licenses),
        "extra_counties": str(extra_counties),
        "price_version": price.id,
    }

    if subscription.stripe_subscription_id:
        current = stripe.Subscription.retrieve(subscription.stripe_subscription_id)
        item_id = current["items"]["data"][0]["id"] if current["items"]["data"] else None
        stripe.Subscription.modify(
            subscription.stripe_subscription_id,
            items=[{"id": item_id, **item}] if item_id else [item],
            proration_behavior="none",
            metadata=metadata,
        )
        return SyncResult(subscription.stripe_subscription_id, monthly_amount_ore, created=False)

    created = stripe.Subscription.create(
        customer=customer_id,
        items=[item],
        metadata=metadata,
        payment_behavior="default_incomplete",
        idempotency_key=f"sub:{subscription.company_id}:{price.id}",
    )
    Subscription.objects.filter(id=subscription.id).update(stripe_subscription_id=created.id)
    return SyncResult(created.id, monthly_amount_ore, created=True)


def charge_order(order: Order) -> str:
    """
    Debiterar en uppgradering: en egen faktura med vårt proportionerade belopp.

    `idempotency_key` är orderns id. Ett återförsök efter en timeout skapar
    därför aldrig en andra debitering -- Stripe returnerar samma objekt (§11).
    """
    stripe = _client()
    subscription = Subscription.objects.get(company_id=order.company_id)
    company = Company.objects.get(id=order.company_id)
    customer_id = ensure_customer(company, subscription)

    for line in order.lines or []:
        stripe.InvoiceItem.create(
            customer=customer_id,
            amount=int(line.get("amount_ore", 0)),
            currency=order.currency.lower(),
            description=f"{line.get('label', 'Ändring')} — {line.get('note', '')}".strip(" —"),
            tax_rates=_vat_tax_rates() or None,
            metadata={"order_id": str(order.id), "line": line.get("key", "")},
            idempotency_key=f"item:{order.id}:{line.get('key', '')}",
        )
    invoice = stripe.Invoice.create(
        customer=customer_id,
        collection_method="charge_automatically",
        auto_advance=True,
        metadata={"order_id": str(order.id), "company_id": str(order.company_id)},
        idempotency_key=f"invoice:{order.id}",
    )
    stripe.Invoice.finalize_invoice(invoice.id, idempotency_key=f"finalize:{order.id}")
    Order.objects.filter(id=order.id).update(stripe_invoice_id=invoice.id)
    return invoice.id


def cancel_stripe_subscription(subscription: Subscription, *, at_period_end: bool = True) -> None:
    """
    Säger upp i Stripe.

    Fungerar även med väntande ändringar hos oss, eftersom vi inte använder
    `subscription schedules`: det finns inget schema att leta rätt på och
    avbryta först. Finns ett schema ändå (skapat för hand i dashboarden)
    släpps det först -- annars hade det förnyat abonnemanget efter uppsägningen.
    """
    stripe = _client()
    if not subscription.stripe_subscription_id:
        return
    current = stripe.Subscription.retrieve(subscription.stripe_subscription_id)
    schedule_id = current.get("schedule")
    if schedule_id:
        try:
            stripe.SubscriptionSchedule.release(schedule_id)
        except Exception as exc:  # pragma: no cover - beror på Stripes läge
            log.warning("fleet.stripe: kunde inte släppa schema %s: %s", schedule_id, exc)
    if at_period_end:
        stripe.Subscription.modify(
            subscription.stripe_subscription_id, cancel_at_period_end=True
        )
    else:
        stripe.Subscription.cancel(subscription.stripe_subscription_id)


def billing_portal_url(subscription: Subscription, return_url: str) -> str:
    """
    Stripes portal för betalmetod och fakturor.

    Ändringar av antal och uppsägning görs INTE där: portalen kan inte uttrycka
    den här prismodellen (volymnivå som omprissätter alla licenser,
    introduktion, länstillägg per bil) och skulle lämna Stripe och appen med
    olika sanningar. Portalen konfigureras därför med enbart betalmetod och
    fakturor -- se docs/fleet-abonnemang.md.
    """
    stripe = _client()
    if not subscription.stripe_customer_id:
        raise StripeUnavailable("Företaget har ingen Stripe-kund.")
    session = stripe.billing_portal.Session.create(
        customer=subscription.stripe_customer_id, return_url=return_url
    )
    return session.url


# ---------------------------------------------------------------------------
# Avstämning
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Discrepancy:
    company_id: str
    field: str
    local: str
    remote: str

    def as_dict(self) -> dict:
        return {
            "companyId": self.company_id, "field": self.field,
            "local": self.local, "remote": self.remote,
        }


def reconcile(subscription: Subscription) -> list[Discrepancy]:
    """
    Jämför vår bild med Stripes. Rapporterar, ändrar inget.

    Att låta avstämningen rätta automatiskt hade betytt att ett fel i endera
    riktningen sprider sig tyst. Den larmar i stället, och rättningen är ett
    beslut någon fattar -- med den här listan som underlag (§9).
    """
    stripe = _client()
    out: list[Discrepancy] = []
    if not subscription.stripe_subscription_id:
        if subscription.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE):
            out.append(
                Discrepancy(str(subscription.company_id), "stripe_subscription_id", "saknas", "")
            )
        return out

    remote = stripe.Subscription.retrieve(subscription.stripe_subscription_id)
    mapped = map_stripe_status(remote.get("status"))
    if mapped != subscription.status:
        out.append(
            Discrepancy(str(subscription.company_id), "status", subscription.status, str(remote.get("status")))
        )

    remote_end = remote.get("current_period_end")
    if remote_end and subscription.current_period_end:
        from datetime import datetime, timezone as dt_timezone

        remote_dt = datetime.fromtimestamp(int(remote_end), tz=dt_timezone.utc)
        if abs((remote_dt - subscription.current_period_end).total_seconds()) > 3600:
            out.append(
                Discrepancy(
                    str(subscription.company_id), "current_period_end",
                    subscription.current_period_end.isoformat(), remote_dt.isoformat(),
                )
            )

    if subscription.cancel_at_period_end != bool(remote.get("cancel_at_period_end")):
        out.append(
            Discrepancy(
                str(subscription.company_id), "cancel_at_period_end",
                str(subscription.cancel_at_period_end), str(remote.get("cancel_at_period_end")),
            )
        )
    if out:
        audit.record(
            "stripe_discrepancy", company_id=subscription.company_id, actor_kind="system",
            subject_type="subscription", subject_id=subscription.id,
            detail={"fields": [d.field for d in out]},
        )
    return out


def map_stripe_status(status: str | None) -> str:
    """Stripes status -> vår. Okänt läge blir aldrig 'aktiv'."""
    return {
        "active": SubscriptionStatus.ACTIVE,
        "trialing": SubscriptionStatus.TRIALING,
        "past_due": SubscriptionStatus.PAST_DUE,
        "unpaid": SubscriptionStatus.PAST_DUE,
        "canceled": SubscriptionStatus.CANCELED,
        "incomplete_expired": SubscriptionStatus.CANCELED,
        "incomplete": SubscriptionStatus.NONE,
        "paused": SubscriptionStatus.NONE,
    }.get(str(status or ""), SubscriptionStatus.NONE)


def check_billing_config() -> list[str]:
    """
    Vad som fattas innan modellen får gå i produktion. Läser bara konfiguration.
    """
    problems = []
    if not getattr(settings, "STRIPE_SECRET_KEY", ""):
        problems.append("STRIPE_SECRET_KEY saknas.")
    if not getattr(settings, "STRIPE_WEBHOOK_SECRET", ""):
        problems.append("STRIPE_WEBHOOK_SECRET saknas -- webhooksignaturer kan inte verifieras.")
    if not getattr(settings, "STRIPE_VAT_TAX_RATE_ID", ""):
        problems.append(
            "STRIPE_VAT_TAX_RATE_ID saknas -- fakturorna skulle sakna moms."
        )
    if not getattr(settings, "STRIPE_PRODUCT_ID", ""):
        problems.append(
            "STRIPE_PRODUCT_ID saknas -- prenumerationsposterna får ingen produkt."
        )
    return problems
