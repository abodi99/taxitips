"""
Flytt av ett betalande abonnemang till en annan prislista.

Prislistan väljs när abonnemanget skapas och ändras aldrig av att en ny lista
blir förvald (se `fleet/pricing.py`). För en kund som redan betalar krävs alltså
en uttrycklig flytt, och den är en riktig ändring av vad kunden debiteras --
därför finns här bara PLANEN (`plan_move_to_price_version`), som är ren läsning
och aldrig rör Stripe. Att verkställa flytten är medvetet inte byggt, se
`apply_move_to_price_version`.
"""

from __future__ import annotations

from django.utils import timezone

from billing.models import Company
from fleet import discounts, licensing, orders, pricing
from fleet.models import PriceVersion, Subscription, SubscriptionStatus


class PriceMoveError(Exception):
    """Flytten går inte att planera (fel läge på abonnemanget, saknad lista)."""


def _monthly(subscription: Subscription, price: PriceVersion, now):
    """Månadsbeloppet på `price`, räknat som `stripe_sync.sync_company_amount` gör."""
    company_id = subscription.company_id
    licenses = licensing.billable_license_count(company_id)
    extras = licensing.extra_county_count(company_id, now)
    quote = pricing.monthly_quote(
        price,
        licenses=licenses,
        extra_counties=extras,
        intro=orders._intro_next_period(subscription, now),
        discount=discounts.active_spec(company_id, now=now),
    )
    return quote, licenses, extras


def plan_move_to_price_version(
    subscription: Subscription, target_version: PriceVersion | str, *, now=None
) -> dict:
    """
    Beskriver, utan att ändra något, vad en flytt till `target_version` innebär
    för ett AKTIVT betalande abonnemang. Heltal i ören; klienten räknar aldrig.

    Beloppen räknas av samma motor som fakturan (`pricing.monthly_quote`) med
    företagets nuvarande platser, extra län och rabatt. Flytten gäller från
    nästa förnyelse (`current_period_end`): perioden som redan är betald rörs inte.
    """
    now = now or timezone.now()
    if isinstance(target_version, str):
        target = PriceVersion.objects.filter(id=target_version).first()
        if target is None:
            raise PriceMoveError(f"Prislistan {target_version} finns inte.")
    else:
        target = target_version
    current = subscription.price_version
    if subscription.status != SubscriptionStatus.ACTIVE:
        raise PriceMoveError(
            f"Abonnemanget är '{subscription.status}', inte 'active'. Bara betalande "
            "abonnemang flyttas; övriga följer den förvalda listan av sig själva."
        )
    if not subscription.current_period_end:
        raise PriceMoveError("Abonnemanget saknar periodslut, så ett förnyelsedatum kan inte anges.")
    if current.id == target.id:
        raise PriceMoveError(f"Abonnemanget ligger redan på {target.id}.")

    before, licenses, extras = _monthly(subscription, current, now)
    after, _, _ = _monthly(subscription, target, now)
    company = Company.objects.filter(id=subscription.company_id).first()

    # Så här ser Stripe-raderna ut efter flytten: exakt samma uppbyggnad som
    # `stripe_sync.sync_subscription_amount` skickar (ren uträkning, inget anrop).
    from fleet import stripe_sync

    new_items = stripe_sync._items_from_lines(
        [line.as_dict() for line in after.lines],
        currency=target.currency, amount_ore=after.amount_ore,
    )
    stripe_changes = {
        "stripeSubscriptionId": subscription.stripe_subscription_id or None,
        "action": (
            "Subscription.modify: alla nuvarande rader tas bort (deleted) och "
            "nya läggs till i samma anrop, proration_behavior='none'; metadata."
            "price_version sätts till målet."
        ),
        "replacedItems": [
            {"key": line.key, "quantity": line.quantity, "unitPriceOre": line.unit_price_ore}
            for line in before.lines
        ],
        "newItems": [
            {
                "unitAmountOre": item["price_data"]["unit_amount"],
                "quantity": item["quantity"],
                "interval": item["price_data"]["recurring"]["interval"],
            }
            for item in new_items
        ],
        "chargedNow": 0,
    }

    return {
        "companyId": str(subscription.company_id),
        "companyName": company.name if company else "",
        "currentPriceVersion": current.id,
        "targetPriceVersion": target.id,
        "seats": licenses,
        "extraCounties": extras,
        "currentMonthlyExVatOre": before.amount_ore,
        "currentMonthlyInclVatOre": before.total_ore,
        "newMonthlyExVatOre": after.amount_ore,
        "newMonthlyInclVatOre": after.total_ore,
        "monthlyDeltaExVatOre": after.amount_ore - before.amount_ore,
        "effectiveAt": subscription.current_period_end.isoformat(),
        "stripe": stripe_changes,
    }


def apply_move_to_price_version(subscription: Subscription, target_version: PriceVersion | str) -> None:
    """
    Verkställer flytten. INTE byggt, med flit.

    Det som saknas för "byt prislista vid nästa förnyelse":

    * `PendingChange.Kind` har ingen sort för prislistebyte. Att lägga till en
      kräver en ändring i `fleet/models.py` (choices) och därmed en migration.
    * `orders.apply_pending_changes` rör aldrig Stripe, så raderna i Stripe
      skulle behöva uppdateras av en separat nyhet i samma steg, före
      förnyelsefakturan skapas -- annars debiteras förnyelsen på gammalt pris.

    Ett alternativ UTAN modelländring finns men är en annan sak än det planen
    beskriver: byt `Subscription.price_version` nu och kör
    `stripe_sync.sync_company_amount` (proration 'none', ingenting debiteras nu,
    nästa faktura får det nya priset). Det är en riktig Stripe-ändring och ska
    bara göras efter uttryckligt ja i chatten.
    """
    raise NotImplementedError(
        "apply_move_to_price_version är inte byggd: det saknas en PendingChange-sort "
        "för prislistebyte (kräver modell/migration). Se funktionens docstring."
    )
