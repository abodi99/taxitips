"""
Beställningar, ändringar, förnyelse och uppsägning.

**Riktningen i tiden är hela modellen.** Uppgraderingar (fler bilar, extra län)
kostar proportionellt NU och ger rättigheter först när betalningen lyckats.
Minskningar, baslänsbyten och uppsägning gäller vid NÄSTA FÖRNYELSE och kostar
ingenting nu. Allt som ska hända senare ligger som `PendingChange`, samlat, så
att en uppsägning kan stänga av allt annat schemalagt i samma steg -- annars
hade en minskning kunnat ligga kvar och förnya ett abonnemang kunden sagt upp
(§9).

**Väntande betalning ger ingen åtkomst och förstör ingen.** En order i
`pending_payment` rör inga rättigheter. Ett fördröjt betalsätt som väntar på
bankgodkännande lämnar alltså både det gamla (fungerar) och det nya (inte än)
i ett begripligt läge (§8).

**Betalningsfristen.** Högst sju dagar, räknade från den URSPRUNGLIGA
förfallotiden, och bara för den som betalat förut. `grace_origin` sparas första
gången och läses vid varje återförsök: ett återförsök kan därför aldrig
förlänga fristen. Första misslyckade betalningen efter ett gratisprov ger ingen
frist alls -- `Subscription.had_successful_payment` är False då.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from fleet import audit, licensing, pricing
from fleet.models import (
    License,
    LicenseCounty,
    Order,
    PendingChange,
    PriceVersion,
    Subscription,
    SubscriptionStatus,
    Trial,
    Vehicle,
    VehicleSession,
)

# §8: högst sju dagars betalningsfrist vid misslyckad förnyelse.
GRACE_DAYS = 7


class OrderError(Exception):
    def __init__(self, reason: str, message: str, status: int = 400, detail: dict | None = None):
        super().__init__(reason)
        self.reason = reason
        self.message = message
        self.status = status
        self.detail = detail or {}


# ---------------------------------------------------------------------------
# Abonnemanget
# ---------------------------------------------------------------------------


def get_or_create_subscription(company_id, *, price_version: PriceVersion | None = None) -> Subscription:
    subscription = Subscription.objects.filter(company_id=company_id).first()
    if subscription is not None:
        return subscription
    return Subscription.objects.create(
        company_id=company_id,
        price_version=price_version or pricing.default_price_version(),
        status=SubscriptionStatus.NONE,
    )


def _intro_next_period(subscription: Subscription, now) -> bool:
    """Gäller introduktionspriset fortfarande vid nästa förnyelse?"""
    if not subscription.intro_ends_at or not subscription.current_period_end:
        return False
    return subscription.current_period_end < subscription.intro_ends_at


# ---------------------------------------------------------------------------
# Planera en ändring
# ---------------------------------------------------------------------------


@dataclass
class VehicleSpec:
    """En bil som ska få en licens. Baslänet väljs per bil (§5)."""

    plate: str
    base_county: str
    label: str = ""
    extra_counties: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "plate": licensing.normalize_plate(self.plate),
            "baseCounty": self.base_county,
            "label": self.label,
            "extraCounties": list(self.extra_counties),
        }


@dataclass
class ChangePlan:
    kind: str
    immediate: bool
    quote: pricing.ChangeQuote
    request: dict
    current_licenses: int
    new_licenses: int
    current_extra_counties: int
    new_extra_counties: int
    effective_at: object | None

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "immediate": self.immediate,
            "licenses": {"before": self.current_licenses, "after": self.new_licenses},
            "extraCounties": {
                "before": self.current_extra_counties, "after": self.new_extra_counties
            },
            "effectiveAt": self.effective_at.isoformat() if self.effective_at else None,
            **self.quote.as_dict(),
        }


def plan_change(
    company_id,
    *,
    add_vehicles: list[VehicleSpec] | None = None,
    add_counties: list[dict] | None = None,
    remove_counties: list[dict] | None = None,
    cancel_license_ids: list[str] | None = None,
    base_county_changes: list[dict] | None = None,
    now=None,
) -> ChangePlan:
    """
    Räknar fram vad ändringen kostar nu och vad nästa period blir.

    Allt i ett anrop, så att 9 -> 10 blir rätt: den tionde bilen gör alla nio
    billigare och kunden ska betala mellanskillnaden. Räknat per post hade den
    tionde bilen kostat fullt pris och de nio aldrig blivit omprissatta.

    Ett baslänsbyte med `immediate: true` blir TVÅ saker: länet köps som
    tillägg nu, och bytet schemaläggs till nästa förnyelse. Det är precis vad
    §5 beskriver, och det extra tillägget tas bort automatiskt vid bytet så att
    ingen betalar för samma län två gånger.
    """
    now = now or timezone.now()
    add_vehicles = add_vehicles or []
    add_counties = add_counties or []
    remove_counties = remove_counties or []
    cancel_license_ids = [str(x) for x in (cancel_license_ids or [])]
    base_county_changes = base_county_changes or []

    subscription = get_or_create_subscription(company_id)
    price = subscription.price_version

    current_licenses = licensing.billable_license_count(company_id)
    current_extra = licensing.extra_county_count(company_id, now)

    for spec in add_vehicles:
        licensing.assert_county_available(spec.base_county)
        for county in spec.extra_counties:
            licensing.assert_county_available(county)
    for item in add_counties:
        licensing.assert_county_available(item.get("county"))
    for item in base_county_changes:
        licensing.assert_county_available(item.get("county"))

    # Baslänsbyte som behövs direkt: länet köps som extra nu.
    immediate_base_counties = [
        {"licenseId": str(item["licenseId"]), "county": item["county"]}
        for item in base_county_changes
        if item.get("immediate")
    ]

    added_extra = (
        sum(len(spec.extra_counties) for spec in add_vehicles)
        + len(add_counties)
        + len(immediate_base_counties)
    )
    removed_extra = len(remove_counties)
    canceled_extra = _extra_counties_on(cancel_license_ids, now)

    new_licenses = current_licenses + len(add_vehicles) - len(cancel_license_ids)
    new_extra = current_extra + added_extra - removed_extra - canceled_extra
    if new_licenses < 0 or new_extra < 0:
        raise OrderError("invalid_change", "Ändringen går inte att räkna ut.")

    immediate = bool(add_vehicles or add_counties or immediate_base_counties)
    kind = _kind_for(add_vehicles, add_counties, remove_counties, cancel_license_ids, base_county_changes)

    if immediate:
        # Nu-beloppet räknas bara på tilläggen. Minskningar i samma anrop får
        # inte dras av mot det som köps nu -- de gäller vid nästa förnyelse.
        upgrade_licenses = current_licenses + len(add_vehicles)
        upgrade_extra = current_extra + added_extra
        quote = pricing.quote_change(
            price, now=now,
            period_start=subscription.current_period_start,
            period_end=subscription.current_period_end,
            intro_now=pricing.intro_active(subscription, now),
            intro_next_period=_intro_next_period(subscription, now),
            current_licenses=current_licenses, current_extra_counties=current_extra,
            new_licenses=upgrade_licenses, new_extra_counties=upgrade_extra,
            immediate=True,
        )
        # Nästa period speglar hela slutläget, inklusive minskningarna.
        quote = pricing.ChangeQuote(
            now=quote.now,
            next_period=pricing.monthly_quote(
                price, licenses=new_licenses, extra_counties=new_extra,
                intro=_intro_next_period(subscription, now),
            ),
            current=quote.current,
            effective_at=quote.effective_at,
            next_period_start=quote.next_period_start,
            proration_remaining_seconds=quote.proration_remaining_seconds,
            proration_total_seconds=quote.proration_total_seconds,
            price_version=price.id,
        )
    else:
        quote = pricing.quote_change(
            price, now=now,
            period_start=subscription.current_period_start,
            period_end=subscription.current_period_end,
            intro_now=pricing.intro_active(subscription, now),
            intro_next_period=_intro_next_period(subscription, now),
            current_licenses=current_licenses, current_extra_counties=current_extra,
            new_licenses=new_licenses, new_extra_counties=new_extra,
            immediate=False,
        )

    request = {
        "addVehicles": [spec.as_dict() for spec in add_vehicles],
        "addCounties": [
            {"licenseId": str(i["licenseId"]), "county": i["county"]} for i in add_counties
        ],
        "removeCounties": [
            {"licenseId": str(i["licenseId"]), "county": i["county"]} for i in remove_counties
        ],
        "cancelLicenseIds": cancel_license_ids,
        "baseCountyChanges": [
            {
                "licenseId": str(i["licenseId"]),
                "county": i["county"],
                "immediate": bool(i.get("immediate")),
            }
            for i in base_county_changes
        ],
    }
    return ChangePlan(
        kind=kind, immediate=immediate, quote=quote, request=request,
        current_licenses=current_licenses, new_licenses=new_licenses,
        current_extra_counties=current_extra, new_extra_counties=new_extra,
        effective_at=quote.effective_at,
    )


def _extra_counties_on(license_ids: list[str], now) -> int:
    if not license_ids:
        return 0
    return (
        LicenseCounty.objects.filter(
            license_id__in=license_ids, kind=LicenseCounty.Kind.EXTRA, active_from__lte=now
        )
        .exclude(active_to__lte=now)
        .count()
    )


def _kind_for(add_vehicles, add_counties, remove_counties, cancel_ids, base_changes) -> str:
    if add_vehicles:
        return Order.Kind.ADD_LICENSE
    if add_counties:
        return Order.Kind.ADD_COUNTY
    if base_changes:
        return Order.Kind.CHANGE_BASE_COUNTY
    if remove_counties or cancel_ids:
        return Order.Kind.REDUCE
    return Order.Kind.INITIAL


# ---------------------------------------------------------------------------
# Lägg beställningen
# ---------------------------------------------------------------------------


def idempotency_key(company_id, plan: ChangePlan) -> str:
    """
    Nyckeln som gör att en dubbelklick eller ett nätåterförsök inte blir två
    beställningar. Samma företag, samma önskade ändring, samma minut.
    """
    payload = json.dumps(
        {"company": str(company_id), "request": plan.request, "kind": plan.kind},
        sort_keys=True,
    )
    minute = timezone.now().strftime("%Y%m%d%H%M")
    return hashlib.sha256(f"{payload}:{minute}".encode()).hexdigest()


@transaction.atomic
def create_order(
    company_id,
    plan: ChangePlan,
    *,
    created_by=None,
    now=None,
    idempotency: str | None = None,
) -> Order:
    """
    Skapar beställningen. Ändrar INGA rättigheter -- det gör `apply_order`,
    och bara när betalningen är bekräftad av servern.
    """
    now = now or timezone.now()
    subscription = get_or_create_subscription(company_id)
    price = subscription.price_version
    key = idempotency or idempotency_key(company_id, plan)

    existing = Order.objects.filter(idempotency_key=key).first()
    if existing is not None:
        return existing

    status = (
        Order.Status.PENDING_PAYMENT
        if plan.immediate and plan.quote.now.total_ore > 0
        else (Order.Status.SCHEDULED if not plan.immediate else Order.Status.PAID)
    )

    try:
        order = Order.objects.create(
            company_id=company_id,
            kind=plan.kind,
            status=status,
            price_version=price,
            quantity_before=plan.current_licenses,
            quantity_after=plan.new_licenses,
            amount_now_ore=plan.quote.now.amount_ore,
            vat_now_ore=plan.quote.now.vat_ore,
            total_now_ore=plan.quote.now.total_ore,
            next_period_amount_ore=plan.quote.next_period.amount_ore,
            next_period_vat_ore=plan.quote.next_period.vat_ore,
            next_period_total_ore=plan.quote.next_period.total_ore,
            currency=price.currency,
            effective_at=plan.effective_at,
            lines=[line.as_dict() for line in plan.quote.now.lines]
            or [line.as_dict() for line in plan.quote.next_period.lines],
            request=plan.request,
            terms_version=price.terms_version,
            created_by=created_by,
            idempotency_key=key,
        )
    except IntegrityError:
        return Order.objects.get(idempotency_key=key)

    audit.record(
        "order_created", company_id=company_id, actor_user_id=created_by,
        actor_kind="customer", subject_type="order", subject_id=order.id,
        detail={
            "kind": plan.kind, "status": status,
            "total_now_ore": plan.quote.now.total_ore,
            "next_period_total_ore": plan.quote.next_period.total_ore,
            "price_version": price.id, "terms_version": price.terms_version,
        },
    )

    if status == Order.Status.PAID:
        # Gratis tillägg (t.ex. första beställningen under prov): inget att
        # betala, rättigheterna kan träda i kraft direkt.
        apply_order(order, now=now)
    elif status == Order.Status.SCHEDULED:
        _schedule_reductions(order, now=now)
    return order


def _schedule_reductions(order: Order, *, now) -> None:
    """Minskningar och baslänsbyten läggs som väntande ändringar till nästa förnyelse."""
    subscription = get_or_create_subscription(order.company_id)
    effective_at = subscription.current_period_end or now
    request = order.request or {}

    if request.get("cancelLicenseIds"):
        PendingChange.objects.create(
            company_id=order.company_id, kind=PendingChange.Kind.REDUCE_LICENSES,
            payload={"licenseIds": request["cancelLicenseIds"]},
            order=order, effective_at=effective_at, created_by=order.created_by,
        )
        License.objects.filter(
            id__in=request["cancelLicenseIds"], company_id=order.company_id
        ).update(status=License.Status.PENDING_CANCEL, ends_at=effective_at)

    for item in request.get("removeCounties", []):
        license = License.objects.filter(
            id=item["licenseId"], company_id=order.company_id
        ).first()
        if license is None:
            continue
        licensing.schedule_county_removal(
            license=license, county_code=item["county"], effective_at=effective_at,
            actor_user_id=order.created_by,
        )
        PendingChange.objects.create(
            company_id=order.company_id, kind=PendingChange.Kind.REMOVE_COUNTY,
            payload=item, order=order, effective_at=effective_at,
            created_by=order.created_by,
        )

    for item in request.get("baseCountyChanges", []):
        License.objects.filter(
            id=item["licenseId"], company_id=order.company_id
        ).update(scheduled_base_county=item["county"])
        PendingChange.objects.create(
            company_id=order.company_id, kind=PendingChange.Kind.CHANGE_BASE_COUNTY,
            payload=item, order=order, effective_at=effective_at,
            created_by=order.created_by,
        )


# ---------------------------------------------------------------------------
# Betalning -> rättigheter
# ---------------------------------------------------------------------------


@transaction.atomic
def apply_order(order: Order, *, now=None) -> Order:
    """
    Verkställer en BETALD beställning: skapar bilar och licenser, aktiverar
    extra län, schemalägger det som ska gälla senare.

    Idempotent: en dubblerad webhook, ett återförsök och en manuell
    avstämning ska kunna anropa den här utan att skapa en andra licens.
    `applied`-statusen är det som håller det, och den sätts i samma
    transaktion som rättigheterna.
    """
    now = now or timezone.now()
    locked = Order.objects.select_for_update().get(id=order.id)
    if locked.status == Order.Status.APPLIED:
        return locked
    if locked.status not in (Order.Status.PAID, Order.Status.SCHEDULED):
        raise OrderError(
            "order_not_paid", "Beställningen är inte betald.", status=409,
            detail={"status": locked.status},
        )

    request = locked.request or {}
    subscription = get_or_create_subscription(locked.company_id)
    trial = (
        Trial.objects.filter(
            company_id=locked.company_id, status__in=[Trial.Status.PENDING, Trial.Status.ACTIVE]
        ).first()
    )

    created_licenses = []
    for spec in request.get("addVehicles", []):
        vehicle = licensing.create_vehicle(
            company_id=locked.company_id, plate=spec["plate"],
            label=spec.get("label", ""), actor_user_id=locked.created_by,
        )
        # En provbil som beställs vidare byter status i stället för att få en
        # andra licens -- annars hade kunden fått betala för två.
        existing = (
            License.objects.filter(
                company_id=locked.company_id, status=License.Status.TRIAL,
                assignments__vehicle=vehicle, assignments__ended_at__isnull=True,
            ).first()
        )
        if existing is not None:
            License.objects.filter(id=existing.id).update(status=License.Status.ACTIVE)
            existing.refresh_from_db()
            license = existing
        else:
            license = licensing.create_license(
                company_id=locked.company_id, vehicle=vehicle,
                base_county=spec["baseCounty"], status=License.Status.ACTIVE,
                actor_user_id=locked.created_by, now=now,
            )
        for county in spec.get("extraCounties", []):
            licensing.activate_extra_county(
                license=license, county_code=county, order=locked, now=now
            )
        created_licenses.append(str(license.id))

    for item in request.get("addCounties", []):
        license = License.objects.filter(
            id=item["licenseId"], company_id=locked.company_id
        ).first()
        if license is None:
            continue
        licensing.activate_extra_county(
            license=license, county_code=item["county"], order=locked, now=now
        )

    # Baslänsbyte: länet finns nu som betalt tillägg, själva bytet sker vid
    # förnyelsen (och tar då bort tillägget, se licensing.apply_base_county_change).
    for item in request.get("baseCountyChanges", []):
        license = License.objects.filter(
            id=item["licenseId"], company_id=locked.company_id
        ).first()
        if license is None:
            continue
        if item.get("immediate"):
            licensing.activate_extra_county(
                license=license, county_code=item["county"], order=locked, now=now
            )
        License.objects.filter(id=license.id).update(scheduled_base_county=item["county"])
        PendingChange.objects.get_or_create(
            company_id=locked.company_id, kind=PendingChange.Kind.CHANGE_BASE_COUNTY,
            order=locked, status=PendingChange.Status.PENDING,
            defaults={
                "payload": item,
                "effective_at": subscription.current_period_end or now,
                "created_by": locked.created_by,
            },
        )

    if request.get("cancelLicenseIds") or request.get("removeCounties"):
        _schedule_reductions(locked, now=now)

    Order.objects.filter(id=locked.id).update(status=Order.Status.APPLIED)
    locked.refresh_from_db()

    if created_licenses and trial is not None and trial.status == Trial.Status.ACTIVE:
        # Kunden har uttryckligen beställt vilka bilar som fortsätter. Provet
        # övergår till betalning -- aldrig av sig självt (§8).
        from fleet import trials

        trials.end_trial(trial, reason="converted_by_order", converted=True, now=now)

    audit.record(
        "order_applied", company_id=locked.company_id, actor_kind="system",
        subject_type="order", subject_id=locked.id,
        detail={"created_licenses": created_licenses, "kind": locked.kind},
    )
    return locked


def mark_order_paid(order: Order, *, now=None, stripe_ids: dict | None = None) -> Order:
    """
    Bokför en lyckad betalning och verkställer beställningen.

    Idempotent på `paid_at`: en dubblerad webhook eller ett återförsök som
    redan gått igenom får inte debitera eller verkställa två gånger.
    """
    now = now or timezone.now()
    updated = Order.objects.filter(
        id=order.id, status__in=[Order.Status.PENDING_PAYMENT, Order.Status.DRAFT]
    ).update(status=Order.Status.PAID, paid_at=now, **(stripe_ids or {}))
    order.refresh_from_db()
    if not updated and order.status in (Order.Status.PAID, Order.Status.APPLIED):
        return order
    return apply_order(order, now=now)


def mark_order_failed(order: Order, *, reason: str, now=None) -> Order:
    """
    En misslyckad betalning ger inga rättigheter -- och tar inga.

    Befintlig betald åtkomst rörs inte: ordern som misslyckades var ett
    TILLÄGG, och kunden ska inte förlora det hen redan har för att en
    uppgradering föll (§8).
    """
    now = now or timezone.now()
    Order.objects.filter(
        id=order.id, status__in=[Order.Status.PENDING_PAYMENT, Order.Status.DRAFT]
    ).update(status=Order.Status.FAILED, failed_at=now, failure_reason=reason[:500])
    order.refresh_from_db()
    audit.record(
        "order_failed", company_id=order.company_id, actor_kind="system",
        subject_type="order", subject_id=order.id, detail={"reason": reason[:500]},
    )
    return order


# ---------------------------------------------------------------------------
# Uppsägning
# ---------------------------------------------------------------------------


@transaction.atomic
def cancel_subscription(company_id, *, actor_user_id=None, reason: str = "", now=None) -> PendingChange:
    """
    Säger upp abonnemanget till periodens slut.

    Åtkomsten behålls till den betalda periodens slut -- ingen ytterligare
    30-dagarsfrist, inget obligatoriskt supportsamtal (§8). Alla andra
    väntande ändringar ersätts, så att ingen schemalagd minskning eller
    länsändring ligger kvar och förnyar något.

    Fungerar under introduktionen och med väntande ändringar: uppsägningen
    läser inte prisläget alls.
    """
    now = now or timezone.now()
    subscription = get_or_create_subscription(company_id)
    if subscription.status == SubscriptionStatus.CANCELED:
        existing = PendingChange.objects.filter(
            company_id=company_id, kind=PendingChange.Kind.CANCEL_SUBSCRIPTION,
            status=PendingChange.Status.PENDING,
        ).first()
        if existing:
            return existing

    effective_at = subscription.current_period_end or now

    # Samlat: allt annat schemalagt ersätts av uppsägningen.
    PendingChange.objects.filter(
        company_id=company_id, status=PendingChange.Status.PENDING
    ).exclude(kind=PendingChange.Kind.CANCEL_SUBSCRIPTION).update(
        status=PendingChange.Status.SUPERSEDED, canceled_at=now
    )

    change = PendingChange.objects.create(
        company_id=company_id, kind=PendingChange.Kind.CANCEL_SUBSCRIPTION,
        payload={"reason": reason[:500]}, effective_at=effective_at,
        created_by=actor_user_id,
    )
    Subscription.objects.filter(id=subscription.id).update(
        cancel_at_period_end=True, canceled_at=now, access_until=effective_at
    )

    # Ett pågående prov ska inte kunna debitera när det tar slut.
    trial = Trial.objects.filter(
        company_id=company_id, status__in=[Trial.Status.PENDING, Trial.Status.ACTIVE]
    ).first()
    if trial is not None:
        from fleet import trials

        trials.end_trial(trial, reason="subscription_canceled", converted=False, now=now)

    audit.record(
        "subscription_canceled", company_id=company_id, actor_user_id=actor_user_id,
        actor_kind="customer", subject_type="subscription", subject_id=subscription.id,
        detail={"effective_at": effective_at.isoformat(), "reason": reason[:500]},
    )
    return change


@transaction.atomic
def undo_cancellation(company_id, *, actor_user_id=None, now=None) -> Subscription:
    """
    Ångrar uppsägningen före slutdatum. Historiken för introduktion och provtid
    behålls -- inget av det rörs här, och det är avsikten (§8).
    """
    now = now or timezone.now()
    subscription = get_or_create_subscription(company_id)
    if not subscription.cancel_at_period_end:
        raise OrderError("not_canceled", "Abonnemanget är inte uppsagt.")
    if subscription.access_until and subscription.access_until <= now:
        raise OrderError(
            "cancellation_final",
            "Uppsägningen har redan trätt i kraft. Lägg en ny beställning för att komma igång igen.",
        )

    PendingChange.objects.filter(
        company_id=company_id, kind=PendingChange.Kind.CANCEL_SUBSCRIPTION,
        status=PendingChange.Status.PENDING,
    ).update(status=PendingChange.Status.CANCELED, canceled_at=now)
    Subscription.objects.filter(id=subscription.id).update(
        cancel_at_period_end=False, canceled_at=None, access_until=None
    )
    subscription.refresh_from_db()
    audit.record(
        "subscription_cancellation_undone", company_id=company_id,
        actor_user_id=actor_user_id, actor_kind="customer",
        subject_type="subscription", subject_id=subscription.id, detail={},
    )
    return subscription


# ---------------------------------------------------------------------------
# Förnyelse och betalningsfrist
# ---------------------------------------------------------------------------


@transaction.atomic
def apply_pending_changes(company_id, *, now=None) -> list[PendingChange]:
    """
    Verkställer allt som skulle gälla från och med nu. Körs vid förnyelsen och
    av `manage.py fleet_tick`.
    """
    now = now or timezone.now()
    due = list(
        PendingChange.objects.select_for_update().filter(
            company_id=company_id, status=PendingChange.Status.PENDING, effective_at__lte=now
        ).order_by("effective_at")
    )
    applied = []
    for change in due:
        if change.kind == PendingChange.Kind.CANCEL_SUBSCRIPTION:
            _apply_cancellation(company_id, now=now)
        elif change.kind == PendingChange.Kind.REDUCE_LICENSES:
            _apply_license_reduction(company_id, change, now=now)
        elif change.kind == PendingChange.Kind.CHANGE_BASE_COUNTY:
            license = License.objects.filter(
                id=change.payload.get("licenseId"), company_id=company_id
            ).first()
            if license is not None:
                licensing.apply_base_county_change(license=license, now=now)
        # REMOVE_COUNTY behöver ingen åtgärd: `active_to` sattes när den
        # schemalades, och åtkomstkontrollen läser tiden.
        PendingChange.objects.filter(id=change.id).update(
            status=PendingChange.Status.APPLIED, applied_at=now
        )
        applied.append(change)
    return applied


def _apply_cancellation(company_id, *, now) -> None:
    subscription = get_or_create_subscription(company_id)
    Subscription.objects.filter(id=subscription.id).update(
        status=SubscriptionStatus.CANCELED,
        access_until=subscription.access_until or subscription.current_period_end or now,
        renewal_stopped_at=now,
    )
    License.objects.filter(company_id=company_id).exclude(
        status=License.Status.CANCELED
    ).update(status=License.Status.CANCELED, canceled_at=now, ends_at=now)
    for license_id in License.objects.filter(company_id=company_id).values_list("id", flat=True):
        from fleet import sessions

        sessions.end_sessions_for_license(
            license_id, reason=VehicleSession.EndReason.LICENSE_CHANGE, now=now
        )
    audit.record(
        "subscription_cancellation_applied", company_id=company_id, actor_kind="system",
        subject_type="subscription", subject_id=subscription.id, detail={},
    )


def _apply_license_reduction(company_id, change: PendingChange, *, now) -> None:
    from fleet import sessions

    ids = [str(x) for x in (change.payload or {}).get("licenseIds", [])]
    License.objects.filter(id__in=ids, company_id=company_id).update(
        status=License.Status.CANCELED, canceled_at=now, ends_at=now
    )
    for license_id in ids:
        sessions.end_sessions_for_license(
            license_id, reason=VehicleSession.EndReason.LICENSE_CHANGE, now=now
        )
    audit.record(
        "licenses_reduced", company_id=company_id, actor_kind="system",
        subject_type="pending_change", subject_id=change.id, detail={"license_ids": ids},
    )


def start_grace(subscription: Subscription, *, due_at=None, now=None) -> Subscription:
    """
    Öppnar betalningsfristen vid en misslyckad förnyelse.

    Tre regler i en funktion, för att de hör ihop:

    * Bara den som betalat förut får en frist (§8).
    * Fristen räknas från den URSPRUNGLIGA förfallotiden, inte från
      återförsöket -- `grace_origin` sparas en gång och läses sedan.
    * Ett återförsök förlänger den aldrig: andra anropet ser att
      `grace_origin` finns och räknar om samma slutdatum.
    """
    now = now or timezone.now()
    if not subscription.had_successful_payment:
        # Första misslyckade betalningen efter ett gratisprov: ingen frist.
        Subscription.objects.filter(id=subscription.id).update(
            status=SubscriptionStatus.PAST_DUE, grace_until=None, grace_origin=None
        )
        subscription.refresh_from_db()
        return subscription

    origin = subscription.grace_origin or due_at or subscription.current_period_end or now
    Subscription.objects.filter(id=subscription.id).update(
        status=SubscriptionStatus.PAST_DUE,
        grace_origin=origin,
        grace_until=origin + timedelta(days=GRACE_DAYS),
    )
    subscription.refresh_from_db()
    return subscription


def stop_renewal(subscription: Subscription, *, reason: str, now=None) -> Subscription:
    """
    Efter slutligt betalningsfel: stoppa den löpande förnyelsen.

    Nya månadsfordringar ska inte fortsätta växa efter avstängning (§8). Den
    obetalda fakturan hanteras separat enligt ekonomipolicyn -- den rörs inte
    här, och det är avsiktligt: att nolla en fordran är ett bokföringsbeslut,
    inte en teknisk städning.
    """
    now = now or timezone.now()
    Subscription.objects.filter(id=subscription.id).update(
        renewal_stopped_at=now, cancel_at_period_end=True
    )
    subscription.refresh_from_db()
    audit.record(
        "renewal_stopped", company_id=subscription.company_id, actor_kind="system",
        subject_type="subscription", subject_id=subscription.id, detail={"reason": reason[:200]},
    )
    return subscription


def record_successful_payment(subscription: Subscription, *, period_start, period_end, now=None) -> Subscription:
    """
    Bokför en lyckad betalning: perioden flyttas fram, fristen nollas och
    introduktionsfönstret sätts EN gång.
    """
    now = now or timezone.now()
    price = subscription.price_version
    updates = {
        "status": SubscriptionStatus.ACTIVE,
        "current_period_start": period_start,
        "current_period_end": period_end,
        "grace_until": None,
        "grace_origin": None,
        "had_successful_payment": True,
    }
    if subscription.intro_started_at is None and pricing.intro_available(price, now):
        updates["intro_started_at"] = now
        updates["intro_ends_at"] = pricing.intro_window(price, now)
        updates["intro_months_used"] = price.intro_months
    Subscription.objects.filter(id=subscription.id).update(**updates)
    subscription.refresh_from_db()
    return subscription
