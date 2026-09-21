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
        idempotency_key=f"customer:{company.id}", **_customer_fields(company)
    )
    Subscription.objects.filter(id=subscription.id).update(stripe_customer_id=customer.id)
    Company.objects.filter(id=company.id).update(stripe_customer_id=customer.id)
    return customer.id


def _customer_fields(company: Company) -> dict:
    """
    Namn, fakturamejl, telefon och adress från företagsprofilen. En svensk
    faktura ska bära mottagarens adress och organisationsnummer; utan dem är
    den inte användbar i kundens bokföring.
    """
    from fleet.models import CompanyProfile

    profile = CompanyProfile.objects.filter(company_id=company.id).first()
    fields = {
        "name": (profile.legal_name if profile and profile.legal_name else company.name),
        "email": ((profile.billing_email if profile else "") or company.email or None),
        "preferred_locales": ["sv"],
        "metadata": {"company_id": str(company.id), "org_number": company.org_number or ""},
    }
    if profile and profile.contact_phone:
        fields["phone"] = profile.contact_phone
    address = (profile.billing_address if profile else None) or {}
    if address.get("line1"):
        fields["address"] = {
            "line1": address.get("line1", ""),
            "line2": address.get("line2", "") or None,
            "postal_code": address.get("postal_code", ""),
            "city": address.get("city", ""),
            "country": (address.get("country") or (profile.country if profile else "SE")),
        }
        fields["address"] = {k: v for k, v in fields["address"].items() if v}
    if profile and profile.billing_reference:
        fields["invoice_settings"] = {
            "custom_fields": [{"name": "Er referens", "value": profile.billing_reference[:30]}]
        }
    return fields


def update_customer(company: Company, subscription: Subscription) -> None:
    """Skickar ändrade kunduppgifter till Stripe, om kunden finns där."""
    stripe = _client()
    customer_id = subscription.stripe_customer_id or (company.stripe_customer_id or "")
    if not customer_id:
        return
    fields = _customer_fields(company)
    fields.pop("preferred_locales", None)
    stripe.Customer.modify(customer_id, **fields)


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
    item = _monthly_item(subscription, monthly_amount_ore)

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


COLLECTION_METHODS = ("charge_automatically", "send_invoice")


def _collection(collection_method: str, days_until_due: int) -> dict:
    """
    Kort (`charge_automatically`) eller faktura (`send_invoice`).

    Kort: kunden betalar på Stripes betalsida, och kortet sparas för
    förnyelserna. Faktura: Stripe mejlar en faktura med förfallodag -- det
    vanliga för ett taxibolag som vill ha papper på det.
    """
    if collection_method not in COLLECTION_METHODS:
        raise ValueError(f"okänt betalsätt: {collection_method}")
    if collection_method == "send_invoice":
        return {
            "collection_method": "send_invoice",
            "days_until_due": max(1, min(int(days_until_due or 14), 60)),
        }
    return {"collection_method": "charge_automatically"}


def charge_order(
    order: Order, *, collection_method: str = "charge_automatically", days_until_due: int = 14
):
    """
    Debiterar en uppgradering: en egen faktura med vårt proportionerade belopp.

    `idempotency_key` är orderns id. Ett återförsök efter en timeout skapar
    därför aldrig en andra debitering -- Stripe returnerar samma objekt (§11).
    Returnerar den slutförda fakturan.
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
        auto_advance=True,
        # Bara posterna ovan. Utan flaggan hade en annan väntande post hos
        # kunden hamnat på den här fakturan.
        pending_invoice_items_behavior="include",
        metadata={"order_id": str(order.id), "company_id": str(order.company_id)},
        idempotency_key=f"invoice:{order.id}",
        **_collection(collection_method, days_until_due),
    )
    invoice = stripe.Invoice.finalize_invoice(invoice.id, idempotency_key=f"finalize:{order.id}")
    Order.objects.filter(id=order.id).update(stripe_invoice_id=invoice.id)
    return invoice


def collect_order(
    order: Order, *, collection_method: str = "charge_automatically", days_until_due: int = 14
) -> str:
    """
    Tar betalt för en beställning som väntar på betalning. Returnerar länken
    till Stripes betalsida.

    * **Första beställningen** (inget abonnemang i Stripe): abonnemanget skapas
      med vårt månadsbelopp, och dess första faktura ÄR betalningen. Beloppet
      är det kunden godkände (`amount_now_ore`); förnyelserna följer
      `sync_company_amount` när beställningen är betald.
    * **Uppgradering**: en egen faktura med det proportionerade beloppet
      (`charge_order`). Månadsbeloppet i Stripe ändras först när den är
      betald -- en obetald uppgradering får inte höja nästa faktura.

    Rättigheterna ges fortfarande bara av webhooken eller avstämningen, när
    Stripe säger att fakturan är betald. Idempotent: en order som redan har en
    faktura får samma länk tillbaka.
    """
    stripe = _client()
    order.refresh_from_db()
    if order.status != Order.Status.PENDING_PAYMENT:
        raise ValueError(f"ordern väntar inte på betalning ({order.status})")
    if order.stripe_invoice_id:
        return order.stripe_payment_url or _invoice_url(order.stripe_invoice_id)

    subscription = Subscription.objects.get(company_id=order.company_id)
    company = Company.objects.get(id=order.company_id)
    customer_id = ensure_customer(company, subscription)
    collection = _collection(collection_method, days_until_due)

    if not subscription.stripe_subscription_id:
        created = stripe.Subscription.create(
            customer=customer_id,
            items=[_monthly_item(subscription, order.amount_now_ore)],
            metadata={
                "company_id": str(order.company_id),
                "order_id": str(order.id),
                "licenses": str(order.quantity_after),
                "price_version": subscription.price_version_id,
            },
            payment_behavior="default_incomplete",
            payment_settings={"save_default_payment_method": "on_subscription"},
            expand=["latest_invoice"],
            idempotency_key=f"sub:{order.id}",
            **collection,
        )
        Subscription.objects.filter(id=subscription.id).update(
            stripe_subscription_id=created.id
        )
        invoice = created.latest_invoice
        if isinstance(invoice, str):
            invoice = stripe.Invoice.retrieve(invoice)
        if invoice.status == "draft":
            invoice = stripe.Invoice.finalize_invoice(
                invoice.id, idempotency_key=f"finalize:{order.id}"
            )
        # Fakturan skapades av abonnemanget och bär inte orderns id. Webhooken
        # hittar ordern på fakturans id; metadata är för den som läser i
        # Stripes dashboard.
        stripe.Invoice.modify(
            invoice.id, metadata={"order_id": str(order.id), "company_id": str(order.company_id)}
        )
    else:
        invoice = charge_order(order, collection_method=collection_method, days_until_due=days_until_due)

    if collection["collection_method"] == "send_invoice":
        stripe.Invoice.send_invoice(invoice.id)

    url = getattr(invoice, "hosted_invoice_url", "") or ""
    Order.objects.filter(id=order.id).update(stripe_invoice_id=invoice.id, stripe_payment_url=url)
    audit.record(
        "order_payment_requested", company_id=order.company_id, actor_kind="system",
        subject_type="order", subject_id=order.id,
        detail={"invoice": invoice.id, "collection_method": collection["collection_method"],
                "total_now_ore": order.total_now_ore},
    )
    return url


def _invoice_url(invoice_id: str) -> str:
    stripe = _client()
    invoice = stripe.Invoice.retrieve(invoice_id)
    return getattr(invoice, "hosted_invoice_url", "") or ""


def _monthly_item(subscription: Subscription, amount_ore: int) -> dict:
    price = subscription.price_version
    price_data = {
        "currency": price.currency.lower(),
        "unit_amount": int(amount_ore),
        "recurring": {"interval": "month"},
    }
    product = getattr(settings, "STRIPE_PRODUCT_ID", "") or ""
    if product:
        price_data["product"] = product
    else:
        # Utan produkt-id kräver Stripe ett produktnamn i price_data.
        price_data["product_data"] = {"name": "TaxiTips billicenser"}
    item = {"price_data": price_data, "quantity": 1}
    rates = _vat_tax_rates()
    if rates:
        item["tax_rates"] = rates
    return item


def fetch_invoice(invoice_id: str) -> dict:
    """Fakturan som Stripe ser den just nu -- för avstämning av en enskild order."""
    stripe = _client()
    invoice = stripe.Invoice.retrieve(invoice_id)
    return invoice.to_dict() if hasattr(invoice, "to_dict") else dict(invoice)


def void_order_invoice(order: Order) -> None:
    """
    Makulerar en obetald orderfaktura. Var det den första beställningen
    avslutas också abonnemanget den skapade -- annars hade Stripe försökt
    driva in det i ett dygn och sedan lämnat ett dött abonnemang kvar.
    """
    stripe = _client()
    if not order.stripe_invoice_id:
        return
    invoice = stripe.Invoice.retrieve(order.stripe_invoice_id)
    if invoice.status in ("open", "draft"):
        if invoice.status == "draft":
            stripe.Invoice.delete(invoice.id)
        else:
            stripe.Invoice.void_invoice(invoice.id)
    subscription = Subscription.objects.filter(company_id=order.company_id).first()
    sub_id = getattr(invoice, "subscription", None)
    if subscription and sub_id and sub_id == subscription.stripe_subscription_id:
        remote = stripe.Subscription.retrieve(sub_id)
        if remote.status in ("incomplete", "incomplete_expired"):
            if remote.status == "incomplete":
                stripe.Subscription.cancel(sub_id)
            Subscription.objects.filter(id=subscription.id).update(stripe_subscription_id="")


def sync_company_amount(company_id) -> SyncResult | None:
    """
    Låter månadsbeloppet i Stripe följa bilarna och länen hos oss.

    Körs när en beställning har verkställts och när en minskning schemalagts,
    med `proration_behavior="none"`: det som ändras är NÄSTA faktura, aldrig
    en retroaktiv post. Gör ingenting för ett företag utan abonnemang i Stripe.
    """
    from fleet import licensing, pricing

    subscription = Subscription.objects.filter(company_id=company_id).select_related(
        "price_version"
    ).first()
    if subscription is None or not subscription.stripe_subscription_id:
        return None
    now = timezone.now()
    licenses = licensing.billable_license_count(company_id)
    extras = licensing.extra_county_count(company_id, now)
    intro_next = bool(
        subscription.intro_ends_at and subscription.current_period_end
        and subscription.current_period_end < subscription.intro_ends_at
    )
    quote = pricing.monthly_quote(
        subscription.price_version, licenses=licenses, extra_counties=extras, intro=intro_next
    )
    return sync_subscription_amount(
        subscription, monthly_amount_ore=quote.amount_ore, licenses=licenses,
        extra_counties=extras,
    )


def set_cancel_at_period_end(subscription: Subscription, flag: bool) -> None:
    """Uppsägning till periodens slut, eller ångrad uppsägning, i Stripe."""
    stripe = _client()
    if not subscription.stripe_subscription_id:
        return
    if flag:
        cancel_stripe_subscription(subscription, at_period_end=True)
    else:
        stripe.Subscription.modify(subscription.stripe_subscription_id, cancel_at_period_end=False)


def defer_billing(subscription: Subscription, days: int):
    """
    Gratisdagar på ett abonnemang i Stripe: nästa debitering flyttas `days`
    dagar framåt.

    Görs med `trial_end`, som Stripe själv beskriver som sättet att skjuta
    fram nästa fakturadatum på ett löpande abonnemang. `proration_behavior=
    "none"`, annars hade Stripe krediterat resten av perioden och lagt en
    extra post på nästa faktura. Abonnemanget står som `trialing` hos Stripe
    tills dess; åtkomstkontrollen läser det som betald period
    (fleet/access.py:company_window). Returnerar det nya datumet.
    """
    from datetime import datetime, timedelta, timezone as dt_timezone

    stripe = _client()
    remote = stripe.Subscription.retrieve(subscription.stripe_subscription_id)
    candidates = [remote.get("trial_end"), remote.get("current_period_end")]
    base_ts = max([int(c) for c in candidates if c] or [0])
    base = max(
        datetime.fromtimestamp(base_ts, tz=dt_timezone.utc) if base_ts else timezone.now(),
        timezone.now(),
    )
    new_end = base + timedelta(days=int(days))
    stripe.Subscription.modify(
        subscription.stripe_subscription_id,
        trial_end=int(new_end.timestamp()),
        proration_behavior="none",
    )
    return new_end


def status() -> dict:
    """Stripe-läget för adminwebben: går det att ta betalt, och i vilket läge."""
    key = getattr(settings, "STRIPE_SECRET_KEY", "") or ""
    live = key.startswith(("sk_live_", "rk_live_"))
    try:
        _client()
        ok, reason = True, ""
    except StripeUnavailable as exc:
        ok, reason = False, str(exc)
    return {
        "available": ok,
        "mode": "live" if live else ("test" if key else "none"),
        "reason": reason,
        "problems": check_billing_config(),
    }


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


def cancel_now(subscription: Subscription) -> None:
    """Avslutar abonnemanget i Stripe direkt, utan återbetalning."""
    cancel_stripe_subscription(subscription, at_period_end=False)


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
