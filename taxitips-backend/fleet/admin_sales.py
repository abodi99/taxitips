"""
Adminwebbens säljflöde: /api/admin/sales/..., /api/admin/companies/<id>/...
och /api/admin/coupons.

Samma behörighetsmodell som resten av adminwebben (fleet/admin_api.py): en
aktiv `StaffRole` krävs, och varje vy kontrollerar sin egen behörighet.

* `ADMIN_SELL` (säljare och plattformsadministratör): lägga upp och ändra
  företag, offerter, beställningar med betallänk, prov, lösa in kuponger,
  bjuda in kundens administratör, säga upp till periodens slut.
* `ADMIN_MANAGE` (plattformsadministratör): skapa och stänga av kuponger,
  markera en order betald utanför Stripe, avsluta ett abonnemang direkt.

Logiken bor i fleet/sales.py och fleet/commerce.py; här finns bara
behörighet, tolkning av anropet och svarets form.
"""

from __future__ import annotations

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core import areas
from core.api import _json
from fleet import commerce, orders, pricing, sales, stripe_sync, trials
from fleet.admin_api import _body, _company_or_404, _iso, _staff, handle
from fleet.models import Coupon, CouponRedemption, Order, RiskConfig
from fleet.roles import Perm


def _order_or_404(order_id) -> Order:
    order = Order.objects.filter(id=order_id).first()
    if order is None:
        raise orders.OrderError("unknown_order", "Ordern finns inte.", status=404)
    return order


def _order_row(order: Order) -> dict:
    return {
        "id": str(order.id), "kind": order.kind, "status": order.status,
        "totalNowOre": order.total_now_ore, "vatNowOre": order.vat_now_ore,
        "nextPeriodTotalOre": order.next_period_total_ore,
        "quantityAfter": order.quantity_after, "lines": order.lines,
        "effectiveAt": _iso(order.effective_at), "createdAt": _iso(order.created_at),
        "paidAt": _iso(order.paid_at), "failureReason": order.failure_reason,
        "stripeInvoiceId": order.stripe_invoice_id,
        "paymentUrl": order.stripe_payment_url or None,
    }


def _plan(company_id, body: dict) -> orders.ChangePlan:
    specs = [
        orders.VehicleSpec(
            plate=str(v.get("plate", "")), base_county=str(v.get("baseCounty", "")),
            label=str(v.get("label", "")),
            extra_counties=[str(c) for c in (v.get("extraCounties") or [])],
        )
        for v in (body.get("addVehicles") or [])
    ]
    return orders.plan_change(
        company_id,
        add_vehicles=specs,
        add_counties=body.get("addCounties") or [],
        remove_counties=body.get("removeCounties") or [],
        cancel_license_ids=body.get("cancelLicenseIds") or [],
        base_county_changes=body.get("baseCountyChanges") or [],
    )


# ---------------------------------------------------------------------------
# Underlag
# ---------------------------------------------------------------------------


@require_GET
@handle
def config(request):
    """GET /api/admin/sales/config -- län, prislista, provregler och Stripe-läge."""
    principal = _staff(request, Perm.ADMIN_VIEW)
    price = pricing.default_price_version()
    return _json(request, {
        "ok": True,
        "canSell": principal.can(Perm.ADMIN_SELL),
        "canManage": principal.can(Perm.ADMIN_MANAGE),
        "counties": [{"code": code, "name": name} for code, name in areas.COUNTIES],
        "price": {
            "id": price.id, "label": price.label, "currency": price.currency,
            "vatRateBp": price.vat_rate_bp, "baseOre": price.base_price_ore,
            "volumeOre": price.volume_price_ore, "volumeThreshold": price.volume_threshold,
            "extraCountyOre": price.extra_county_price_ore,
        },
        "trial": {"days": trials.TRIAL_DAYS, "vehicleLimit": trials.TRIAL_VEHICLE_LIMIT},
        "pairingCodeTtlSeconds": RiskConfig.current().pairing_code_ttl_seconds,
        "stripe": stripe_sync.status(),
    })


@require_GET
@handle
def lookup(request):
    """GET /api/admin/sales/lookup?orgNumber=&country= -- finns bolaget, får det prov?"""
    _staff(request, Perm.ADMIN_SELL)
    return _json(request, {
        "ok": True,
        **sales.lookup(request.GET.get("orgNumber", ""), request.GET.get("country", "SE")),
    })


# ---------------------------------------------------------------------------
# Företaget
# ---------------------------------------------------------------------------


@csrf_exempt
@require_POST
@handle
def create_company(request):
    """POST /api/admin/companies/new"""
    principal = _staff(request, Perm.ADMIN_SELL)
    body = _body(request)
    company = sales.create_company(
        name=body.get("name", ""), org_number=body.get("orgNumber", ""),
        country=body.get("country", "SE"), legal_name=body.get("legalName", ""),
        contact_name=body.get("contactName", ""), contact_role=body.get("contactRole", ""),
        contact_email=body.get("contactEmail", ""), contact_phone=body.get("contactPhone", ""),
        billing_email=body.get("billingEmail", ""),
        billing_reference=body.get("billingReference", ""),
        billing_address=body.get("billingAddress") or {},
        verification_note=body.get("verificationNote", ""),
        actor_user_id=principal.user_id,
    )
    return _json(request, {
        "ok": True, "companyId": str(company.id), "name": company.name,
        "joinCode": company.join_code,
    })


@csrf_exempt
@require_POST
@handle
def update_profile(request, company_id):
    """POST /api/admin/companies/<id>/profile -- kund- och fakturauppgifter."""
    principal = _staff(request, Perm.ADMIN_SELL)
    company = _company_or_404(company_id)
    sales.update_profile(company, _body(request), actor_user_id=principal.user_id)
    return _json(request, {"ok": True})


# ---------------------------------------------------------------------------
# Paket, beställning och betalning
# ---------------------------------------------------------------------------


@csrf_exempt
@require_POST
@handle
def quote(request, company_id):
    """POST /api/admin/companies/<id>/quote -- vad kostar paketet? Ändrar inget."""
    _staff(request, Perm.ADMIN_SELL)
    company = _company_or_404(company_id)
    plan = _plan(company.id, _body(request))
    return _json(request, {"ok": True, **plan.as_dict()})


@csrf_exempt
@require_POST
@handle
def create_order(request, company_id):
    """
    POST /api/admin/companies/<id>/orders

    {"addVehicles": [...], ..., "accepted": true, "payment": "stripe_card" |
    "stripe_invoice" | "later", "daysUntilDue": 14}

    `accepted` betyder att kunden i telefon har godkänt antal, pris och datum
    -- samma krav som i kundportalen (§6). Säljaren intygar det; det loggas.
    """
    principal = _staff(request, Perm.ADMIN_SELL)
    body = _body(request)
    company = _company_or_404(company_id)
    if not body.get("accepted"):
        raise orders.OrderError(
            "acceptance_required",
            "Bekräfta att kunden har godkänt antal, pris och betalningsdatum.",
        )
    plan = _plan(company.id, body)
    order, payment = commerce.place_order(
        company.id, plan, created_by=principal.user_id, actor_kind="sales",
        payment=str(body.get("payment") or commerce.PAYMENT_CARD),
        days_until_due=int(body.get("daysUntilDue") or 14),
        idempotency=body.get("idempotencyKey"),
    )
    return _json(request, {"ok": True, "order": _order_row(order), "payment": payment})


@csrf_exempt
@require_POST
@handle
def order_payment_link(request, order_id):
    """POST /api/admin/orders/<id>/payment-link {"payment": "stripe_card"|"stripe_invoice"}"""
    _staff(request, Perm.ADMIN_SELL)
    body = _body(request)
    order = _order_or_404(order_id)
    url = commerce.request_payment(
        order, payment=str(body.get("payment") or commerce.PAYMENT_CARD),
        days_until_due=int(body.get("daysUntilDue") or 14),
    )
    order.refresh_from_db()
    return _json(request, {"ok": True, "paymentUrl": url or None, "order": _order_row(order)})


@csrf_exempt
@require_POST
@handle
def order_refresh(request, order_id):
    """POST /api/admin/orders/<id>/refresh -- läs betalningen från Stripe."""
    _staff(request, Perm.ADMIN_SELL)
    order = _order_or_404(order_id)
    result = commerce.refresh_payment(order)
    order.refresh_from_db()
    return _json(request, {"ok": True, **result, "order": _order_row(order)})


@csrf_exempt
@require_POST
@handle
def order_mark_paid(request, order_id):
    """POST /api/admin/orders/<id>/mark-paid {"note": "..."} -- betald utanför Stripe."""
    principal = _staff(request, Perm.ADMIN_MANAGE)
    order = _order_or_404(order_id)
    order = commerce.mark_paid_manually(
        order, actor_user_id=principal.user_id, note=str(_body(request).get("note", ""))
    )
    return _json(request, {"ok": True, "order": _order_row(order)})


@csrf_exempt
@require_POST
@handle
def order_cancel(request, order_id):
    """POST /api/admin/orders/<id>/cancel -- avbryt en obetald order."""
    principal = _staff(request, Perm.ADMIN_SELL)
    order = _order_or_404(order_id)
    order = commerce.cancel_order(
        order, actor_user_id=principal.user_id, reason=str(_body(request).get("reason", ""))
    )
    return _json(request, {"ok": True, "order": _order_row(order)})


# ---------------------------------------------------------------------------
# Prov och kuponger
# ---------------------------------------------------------------------------


@csrf_exempt
@require_POST
@handle
def start_trial(request, company_id):
    """POST /api/admin/companies/<id>/trial {"vehicles": [...]}"""
    principal = _staff(request, Perm.ADMIN_SELL)
    company = _company_or_404(company_id)
    trial = sales.start_trial(
        company, _body(request).get("vehicles") or [], actor_user_id=principal.user_id
    )
    return _json(request, {
        "ok": True, "trialId": str(trial.id), "status": trial.status,
        "endsAt": _iso(trial.ends_at), "vehicleLimit": trial.vehicle_limit,
        "vehicles": trials.trial_vehicle_count(trial),
    })


@csrf_exempt
@require_POST
@handle
def redeem_coupon(request, company_id):
    """POST /api/admin/companies/<id>/coupon {"code": "...", "vehicles": [...]}"""
    principal = _staff(request, Perm.ADMIN_SELL)
    body = _body(request)
    company = _company_or_404(company_id)
    redemption = sales.redeem_coupon(
        company, str(body.get("code", "")), vehicles=body.get("vehicles") or [],
        actor_user_id=principal.user_id,
    )
    return _json(request, {
        "ok": True, "effect": redemption.effect, "days": redemption.days,
        "detail": redemption.detail,
    })


def _coupon_row(coupon: Coupon) -> dict:
    return {
        "id": str(coupon.id), "code": coupon.code, "description": coupon.description,
        "days": coupon.days, "vehicleLimit": coupon.vehicle_limit,
        "maxRedemptions": coupon.max_redemptions, "redemptions": coupon.redemption_count,
        "validUntil": _iso(coupon.valid_until), "active": coupon.is_active,
        "createdAt": _iso(coupon.created_at),
    }


@require_GET
@handle
def coupons(request):
    """GET /api/admin/coupons"""
    _staff(request, Perm.ADMIN_VIEW)
    rows = Coupon.objects.all().order_by("-created_at")[:200]
    return _json(request, {"ok": True, "coupons": [_coupon_row(c) for c in rows]})


def _parse_until(value):
    if not value:
        return None
    parsed = parse_datetime(str(value))
    if parsed is None:
        day = parse_date(str(value))
        if day is None:
            raise sales.SalesError("invalid_date", "Datumet går inte att tolka.")
        from datetime import datetime, time

        parsed = datetime.combine(day, time(23, 59, 59))
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed)
    return parsed


@csrf_exempt
@require_POST
@handle
def create_coupon(request):
    """POST /api/admin/coupons/new"""
    principal = _staff(request, Perm.ADMIN_MANAGE)
    body = _body(request)
    coupon = sales.create_coupon(
        code=body.get("code", ""), description=body.get("description", ""),
        days=body.get("days"), vehicle_limit=body.get("vehicleLimit") or 3,
        max_redemptions=body.get("maxRedemptions"),
        valid_until=_parse_until(body.get("validUntil")),
        actor_user_id=principal.user_id,
    )
    return _json(request, {"ok": True, "coupon": _coupon_row(coupon)})


@csrf_exempt
@require_POST
@handle
def deactivate_coupon(request, coupon_id):
    """POST /api/admin/coupons/<id>/deactivate"""
    principal = _staff(request, Perm.ADMIN_MANAGE)
    coupon = Coupon.objects.filter(id=coupon_id).first()
    if coupon is None:
        raise sales.SalesError("unknown_coupon", "Kupongen finns inte.", status=404)
    coupon = sales.deactivate_coupon(coupon, actor_user_id=principal.user_id)
    return _json(request, {"ok": True, "coupon": _coupon_row(coupon)})


# ---------------------------------------------------------------------------
# Uppsägning
# ---------------------------------------------------------------------------


@csrf_exempt
@require_POST
@handle
def cancel_subscription(request, company_id):
    """
    POST /api/admin/companies/<id>/cancel {"reason": "...", "immediate": false}

    Till periodens slut: säljare. Direkt (`immediate`): plattformsadministratör.
    """
    body = _body(request)
    immediate = bool(body.get("immediate"))
    principal = _staff(request, Perm.ADMIN_MANAGE if immediate else Perm.ADMIN_SELL)
    company = _company_or_404(company_id)
    reason = str(body.get("reason", ""))[:500]
    if immediate:
        result = commerce.terminate_now(company.id, actor_user_id=principal.user_id, reason=reason)
        return _json(request, {"ok": True, "immediate": True, **result})
    change, stripe_result = commerce.cancel_subscription(
        company.id, actor_user_id=principal.user_id, actor_kind="sales", reason=reason
    )
    return _json(request, {
        "ok": True, "immediate": False, "effectiveAt": _iso(change.effective_at),
        "stripe": stripe_result,
    })


@csrf_exempt
@require_POST
@handle
def undo_cancel(request, company_id):
    """POST /api/admin/companies/<id>/undo-cancel"""
    principal = _staff(request, Perm.ADMIN_SELL)
    company = _company_or_404(company_id)
    subscription, stripe_result = commerce.undo_cancellation(
        company.id, actor_user_id=principal.user_id, actor_kind="sales"
    )
    return _json(request, {
        "ok": True, "periodEnd": _iso(subscription.current_period_end), "stripe": stripe_result,
    })


# ---------------------------------------------------------------------------
# Kundens administratör
# ---------------------------------------------------------------------------


@csrf_exempt
@require_POST
@handle
def invite_owner(request, company_id):
    """
    POST /api/admin/companies/<id>/owner-invite {"email": "..."}

    Adminwebben skickar sedan inloggningslänken med Supabase Auth till samma
    adress; när personen loggar in i kundportalen knyts kontot till bolaget.
    """
    principal = _staff(request, Perm.ADMIN_SELL)
    company = _company_or_404(company_id)
    invite = sales.invite_owner(
        company, str(_body(request).get("email", "")), actor_user_id=principal.user_id
    )
    return _json(request, {
        "ok": True, "inviteId": str(invite.id), "email": invite.email,
        "expiresAt": _iso(invite.expires_at),
    })


def redemptions_for(company_id) -> list[dict]:
    return [
        {"code": r.coupon.code, "effect": r.effect, "days": r.days, "detail": r.detail,
         "at": _iso(r.created_at)}
        for r in CouponRedemption.objects.filter(company_id=company_id)
        .select_related("coupon").order_by("-created_at")[:20]
    ]
