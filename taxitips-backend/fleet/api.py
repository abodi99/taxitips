"""
HTTP-API:t för kundlivscykeln.

Två sorters ingång, med olika bevis:

* **Förarens** -- `X-Device-Token`. Parkoppling, bilval, skiftbyte. Ger aldrig
  administrativ behörighet, oavsett vad klienten påstår.
* **Administratörens** -- `Authorization: Bearer <supabase-jwt>`. Bilar,
  telefoner, län, beställningar, uppsägning. Varje anrop går genom
  `access.principal_for` och `roles.require` -- behörigheten kontrolleras på
  servern, inte i menyn.

Ingen vy här läser ett belopp från klienten. Priset räknas i fleet/pricing.py
och beställningen bär den uträkning kunden såg.

Svaren har samma form som resten av appens API (se core/api.py): `_json` med
CORS, svenska felmeddelanden och ett maskinläsbart `reason` bredvid.
"""

from __future__ import annotations

import json
import logging

from django.db import transaction
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from billing.models import Company, CompanyMember
from core.api import _json
from core import areas
from fleet import (
    accounts,
    access,
    audit,
    commerce,
    licensing,
    ownership,
    notifications,
    orders,
    orgnr,
    pairing,
    ratelimit,
    risk,
    roles,
    sales,
    sessions,
    trials,
)
from fleet.models import (
    ChangeReview,
    OwnershipTransfer,
    CompanyProfile,
    DeviceApproval,
    License,
    LicenseCounty,
    Order,
    PendingChange,
    Subscription,
    Trial,
    Vehicle,
    VehicleAssignment,
    VehicleSession,
)
from fleet.roles import Perm, PermissionDenied

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Felhantering
# ---------------------------------------------------------------------------

# Alla domänfel bär samma tre fält (reason, message, status), så vyerna slipper
# en except-gren per modul. Ett fel utan begripligt meddelande blir ett
# supportärende; det är billigare att kräva formen här.
_DOMAIN_ERRORS = (
    accounts.AccountError,
    pairing.PairingError,
    sessions.SessionError,
    licensing.LicensingError,
    orders.OrderError,
    trials.TrialError,
    risk.ReviewRequired,
    ratelimit.RateLimited,
    ownership.OwnershipError,
    sales.SalesError,
    PermissionDenied,
)


def _error(request, exc):
    payload = {
        "ok": False,
        "reason": getattr(exc, "reason", "error"),
        "message": getattr(exc, "message", "Något gick fel."),
    }
    detail = getattr(exc, "detail", None)
    if detail:
        payload["detail"] = detail
    return _json(request, payload, status=getattr(exc, "status", 400))


def _body(request) -> dict:
    try:
        return json.loads(request.body or b"{}")
    except ValueError:
        return {}


def handle(view):
    """Fångar domänfelen. Oväntade fel loggas och blir 500 utan intern text."""

    def wrapper(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except _DOMAIN_ERRORS as exc:
            return _error(request, exc)
        except Exception:
            log.exception("fleet.api: oväntat fel i %s", view.__name__)
            return _json(
                request,
                {"ok": False, "reason": "internal_error", "message": "Något gick fel."},
                status=500,
            )

    wrapper.__name__ = view.__name__
    return wrapper


def _principal(request, permission: str | None = None) -> roles.Principal:
    principal = access.principal_for(request)
    if principal.user_id is None:
        raise PermissionDenied("login_required", "Logga in för att fortsätta.", status=401)
    if permission:
        roles.require(principal, permission)
    return principal


def _company_license(principal: roles.Principal, license_id) -> License:
    license = License.objects.filter(id=license_id, company_id=principal.company_id).first()
    if license is None:
        raise licensing.LicensingError("unknown_license", "Licensen finns inte.", status=404)
    return license


def _company_vehicle(principal: roles.Principal, vehicle_id) -> Vehicle:
    vehicle = Vehicle.objects.filter(id=vehicle_id, company_id=principal.company_id).first()
    if vehicle is None:
        raise licensing.LicensingError("unknown_vehicle", "Bilen finns inte.", status=404)
    return vehicle


# ---------------------------------------------------------------------------
# Förarens vägar
# ---------------------------------------------------------------------------


@csrf_exempt
@require_POST
@handle
def pair(request):
    """
    POST /api/fleet/pair -- lös in engångskoden.

    Svaret bär hemligheten EN gång. Appen lägger den i plattformens säkra
    lagring; servern har bara hashen.
    """
    body = _body(request)
    result = pairing.redeem_code(
        code=body.get("code", ""),
        installation_id=body.get("installation_id", ""),
        label=body.get("label", ""),
        platform=body.get("platform", ""),
        push_token=(body.get("push_token") or "").strip() or None,
    )
    # Provet startar vid FÖRSTA telefonaktiveringen, inte vid registreringen.
    trial = trials.active_trial(result.company_id)
    if trial is not None and trial.status == Trial.Status.PENDING:
        trials.start_trial(trial)
        company = Company.objects.filter(id=result.company_id).first()
        notifications.trial_started(result.company_id, (company.email if company else ""), trial)
    return _json(request, {"ok": True, **result.as_dict()})


@require_GET
@handle
def driver_status(request):
    """
    GET /api/fleet/me -- vad den här telefonen får, och vilken bil den kör.

    Appen anropar den vid start: svaret säger om telefonen är godkänd, vilka
    bilar den kan välja, om någon annan har bilen, och till när åtkomsten
    gäller.
    """
    now = timezone.now()
    token = request.headers.get("X-Device-Token") or request.GET.get("device_token")
    device, credential, how = access.device_for_token(token)
    if device is None:
        return _json(request, {"ok": False, "reason": how}, status=401)

    resolved = access.resolve(request, now)
    approvals = list(
        DeviceApproval.objects.filter(
            device_id=device.id, status=DeviceApproval.Status.ACTIVE
        ).select_related("vehicle", "license")
    )
    session = sessions.active_session_for_device(device.id)

    vehicles = []
    for approval in approvals:
        holder = sessions.active_session_for_license(approval.license_id)
        vehicles.append({
            "licenseId": str(approval.license_id),
            "vehicleId": str(approval.vehicle_id),
            "plate": approval.vehicle.plate,
            "label": approval.label or approval.vehicle.label,
            "baseCounty": approval.license.base_county,
            "counties": list(access.license_counties(approval.license_id, now)),
            "occupied": bool(holder and str(holder.device_id) != str(device.id)),
            "occupiedBy": (
                sessions.holder_label(holder)
                if holder and str(holder.device_id) != str(device.id) else ""
            ),
            "isMine": bool(session and str(session.license_id) == str(approval.license_id)),
        })

    return _json(request, {
        "ok": True,
        "deviceId": str(device.id),
        "companyId": str(device.company_id),
        "credentialScheme": (credential.scheme if credential else "legacy_plaintext"),
        "vehicles": vehicles,
        "session": (
            {
                "sessionId": str(session.id),
                "licenseId": str(session.license_id),
                "vehicleId": str(session.vehicle_id),
                "startedAt": session.started_at.isoformat(),
            }
            if session else None
        ),
        **resolved.as_dict(),
    })


@csrf_exempt
@require_POST
@handle
def session_start(request):
    """
    POST /api/fleet/session -- ta bilen, eller ta över den.

    Utan `force` svarar den `takeover_required` med uppgift om vem som har
    bilen. Appen frågar föraren; `force: true` är svaret på den frågan.
    """
    body = _body(request)
    token = request.headers.get("X-Device-Token") or body.get("device_token")
    device, _credential, how = access.device_for_token(token)
    if device is None:
        return _json(request, {"ok": False, "reason": how}, status=401)

    license_id = body.get("license_id")
    if not license_id:
        raise sessions.SessionError("license_required", "Välj vilken bil du kör.", status=400)
    license = License.objects.filter(id=license_id, company_id=device.company_id).first()
    if license is None:
        raise sessions.SessionError("unknown_license", "Licensen finns inte.", status=404)

    window = access.company_window(device.company_id)
    if not window.ok:
        return _json(
            request,
            {"ok": False, "reason": window.reason, "message": access._window_message(window.reason)},
            status=403,
        )

    force = bool(body.get("force"))
    if force:
        # Riskkontrollen gäller övertagandet, inte åtkomsten: den som kör nu
        # påverkas inte medan ärendet granskas (§4).
        risk.guard_takeover(license)

    result = sessions.start_session(device_id=device.id, license_id=license.id, force=force)
    return _json(request, {"ok": True, **result.as_dict()})


@csrf_exempt
@require_POST
@handle
def session_end(request):
    """POST /api/fleet/session/end -- lämna bilen."""
    token = request.headers.get("X-Device-Token") or _body(request).get("device_token")
    device, _credential, how = access.device_for_token(token)
    if device is None:
        return _json(request, {"ok": False, "reason": how}, status=401)
    session = sessions.active_session_for_device(device.id)
    if session is None:
        return _json(request, {"ok": True, "reason": "no_active_session"})
    sessions.end_session(session, reason=VehicleSession.EndReason.DRIVER_END)
    return _json(request, {"ok": True})


@csrf_exempt
@require_POST
@handle
def join_request(request):
    """
    POST /api/fleet/join-request -- bolagskoden hittar företaget. Inget mer.

    Ingen token, ingen åtkomst, ingen administratörsbehörighet. Koden lägger en
    ansökan som en administratör ser i portalen och besvarar med en
    engångskod (§2).
    """
    body = _body(request)
    code = (body.get("join_code") or "").strip().upper()
    installation_id = (body.get("installation_id") or "").strip()
    if not code or not installation_id:
        raise pairing.PairingError(
            "missing_fields", "Bolagskod och installations-id krävs."
        )
    company = Company.objects.filter(join_code=code).first()
    if company is None:
        # Samma svar oavsett: en okänd kod ska inte gå att skilja från en känd.
        return _json(request, {
            "ok": True,
            "message": "Ansökan skickad. Din administratör godkänner telefonen med en kod.",
        })
    pairing.create_join_request(
        company=company, installation_id=installation_id, label=body.get("label", "")
    )
    return _json(request, {
        "ok": True,
        "companyName": company.name,
        "message": "Ansökan skickad. Din administratör godkänner telefonen med en kod.",
    })


# ---------------------------------------------------------------------------
# Administratörens vägar: översikt
# ---------------------------------------------------------------------------


@require_GET
@handle
def company_overview(request):
    """
    GET /api/fleet/company -- Översikt.

    Aktuell aktiv telefon per bil, köpta län, prov-/betalperiod, nästa
    betalning, introduktionens slut, väntande ändringar och öppna
    granskningar (§10).
    """
    principal = _principal(request, Perm.VIEW_COMPANY)
    now = timezone.now()
    company_id = principal.company_id
    if not company_id:
        return _json(request, {"ok": False, "reason": "no_company"}, status=403)

    company = Company.objects.filter(id=company_id).first()
    profile = CompanyProfile.objects.filter(company_id=company_id).first()
    subscription = orders.get_or_create_subscription(company_id)
    trial = trials.active_trial(company_id)

    rows = []
    for license in License.objects.filter(company_id=company_id).exclude(
        status=License.Status.CANCELED
    ):
        serving = sessions.current_vehicle(license)
        session = sessions.active_session_for_license(license.id)
        assignment = VehicleAssignment.objects.filter(
            license=license, ended_at__isnull=True
        ).first()
        rows.append({
            "licenseId": str(license.id),
            "status": license.status,
            "vehicle": serving.plate if serving else "",
            "vehicleId": str(serving.id) if serving else None,
            "assignmentKind": assignment.kind if assignment else "",
            "plannedReturn": (
                assignment.planned_end.isoformat()
                if assignment and assignment.planned_end else None
            ),
            "baseCounty": license.base_county,
            "scheduledBaseCounty": license.scheduled_base_county,
            "counties": list(access.license_counties(license.id, now)),
            "extraCounties": [
                c.county_code
                for c in LicenseCounty.objects.filter(
                    license=license, kind=LicenseCounty.Kind.EXTRA
                ).exclude(active_to__lte=now)
            ],
            "endsAt": license.ends_at.isoformat() if license.ends_at else None,
            "activePhone": (
                {
                    "deviceId": str(session.device_id),
                    "label": sessions.holder_label(session),
                    "since": session.started_at.isoformat(),
                }
                if session else None
            ),
            "approvedPhones": [
                {
                    "approvalId": str(a.id),
                    "deviceId": str(a.device_id),
                    "label": a.label,
                    "approvedAt": a.approved_at.isoformat(),
                }
                for a in DeviceApproval.objects.filter(
                    license=license, status=DeviceApproval.Status.ACTIVE
                )
            ],
        })

    pending = [
        {
            "id": str(p.id), "kind": p.kind,
            "effectiveAt": p.effective_at.isoformat(), "payload": p.payload,
        }
        for p in PendingChange.objects.filter(
            company_id=company_id, status=PendingChange.Status.PENDING
        ).order_by("effective_at")
    ]

    return _json(request, {
        "ok": True,
        "company": {
            "id": str(company_id),
            "name": company.name if company else "",
            "orgNumber": orgnr.format_se(profile.org_number) if profile else "",
            "country": profile.country if profile else "SE",
            "verificationStatus": profile.verification_status if profile else "unverified",
            "suspended": accounts.company_block(company_id) is not None,
            "legacyAccessUntil": (
                profile.legacy_access_until.isoformat()
                if profile and profile.legacy_access_until else None
            ),
        },
        # Samma svar som förarens telefon får, med skälet: appen och portalen
        # visar det i stället för att räkna ut det själva.
        "access": _access_summary(company_id, now),
        "role": principal.role,
        "permissions": sorted(principal.permissions),
        "twoFactor": {
            "enforced": roles.two_factor_enforced(now),
            "satisfied": principal.has_two_factor,
        },
        "subscription": {
            "status": subscription.status,
            "priceVersion": subscription.price_version_id,
            "currentPeriodStart": (
                subscription.current_period_start.isoformat()
                if subscription.current_period_start else None
            ),
            "currentPeriodEnd": (
                subscription.current_period_end.isoformat()
                if subscription.current_period_end else None
            ),
            "cancelAtPeriodEnd": subscription.cancel_at_period_end,
            "accessUntil": (
                subscription.access_until.isoformat() if subscription.access_until else None
            ),
            "graceUntil": (
                subscription.grace_until.isoformat() if subscription.grace_until else None
            ),
            "introEndsAt": (
                subscription.intro_ends_at.isoformat() if subscription.intro_ends_at else None
            ),
            "renewalStopped": bool(subscription.renewal_stopped_at),
        },
        "trial": (
            {
                "status": trial.status,
                "startedAt": trial.started_at.isoformat() if trial.started_at else None,
                "endsAt": trial.ends_at.isoformat() if trial.ends_at else None,
                "vehicleLimit": trial.vehicle_limit,
                "vehiclesUsed": trials.trial_vehicle_count(trial),
                "requiresPaymentMethod": trial.requires_payment_method,
            }
            if trial else None
        ),
        "licenses": rows,
        "licenseCount": licensing.billable_license_count(company_id),
        "extraCountyCount": licensing.extra_county_count(company_id, now),
        "pendingChanges": pending,
        "reviews": risk.customer_status(company_id),
        # Länslistan för att välja baslän på en ny provbil i appen.
        "countyCatalog": [{"code": code, "name": name} for code, name in areas.COUNTIES],
    })


# ---------------------------------------------------------------------------
# Bilar och telefoner
# ---------------------------------------------------------------------------


def _access_summary(company_id, now) -> dict:
    window = access.company_window(company_id, now)
    return {
        "ok": window.ok,
        "reason": window.reason,
        "message": "" if window.ok else access._window_message(window.reason),
        "validUntil": window.valid_until.isoformat() if window.valid_until else None,
    }


@csrf_exempt
@require_POST
@handle
def create_vehicle(request):
    """POST /api/fleet/vehicles"""
    principal = _principal(request, Perm.MANAGE_VEHICLES)
    body = _body(request)
    vehicle = licensing.create_vehicle(
        company_id=principal.company_id, plate=body.get("plate", ""),
        label=body.get("label", ""), actor_user_id=principal.user_id,
    )
    return _json(request, {
        "ok": True, "vehicleId": str(vehicle.id), "plate": vehicle.plate,
    })


@csrf_exempt
@require_POST
@handle
def issue_pairing_code(request):
    """
    POST /api/fleet/pairing-codes -- godkänn en telefon för en bil.

    Koden i klartext returneras EN gång, tillsammans med en QR-nyttolast.
    """
    principal = _principal(request, Perm.MANAGE_DEVICES)
    body = _body(request)
    license = _company_license(principal, body.get("license_id"))
    vehicle = _company_vehicle(principal, body.get("vehicle_id"))
    risk.guard_pairing(vehicle)
    issued = pairing.issue_code(
        license=license, vehicle=vehicle, created_by=principal.user_id,
        label=body.get("label", ""),
    )
    return _json(request, {"ok": True, **issued.as_dict()})


@csrf_exempt
@require_POST
@handle
def block_approval(request, approval_id):
    """
    POST /api/fleet/approvals/<id>/block -- spärra en borttappad telefon.

    Kräver inte tillgång till telefonen, tar effekt omedelbart och avslutar
    den aktiva sessionen (§2).
    """
    principal = _principal(request, Perm.MANAGE_DEVICES)
    approval = DeviceApproval.objects.filter(
        id=approval_id, company_id=principal.company_id
    ).first()
    if approval is None:
        raise licensing.LicensingError("unknown_approval", "Telefonen finns inte.", status=404)
    pairing.block_device(
        approval=approval, actor_user_id=principal.user_id,
        reason=_body(request).get("reason", "lost_phone"),
    )
    notifications.device_blocked(principal.company_id, approval)
    return _json(request, {"ok": True})


@csrf_exempt
@require_POST
@handle
def change_license_vehicle(request, license_id):
    """
    POST /api/fleet/licenses/<id>/vehicle

    `mode`: permanent | temporary | return. Permanent byte bevarar
    betalperiod, län och provhistorik och återkallar den gamla bilens åtkomst.
    """
    principal = _principal(request, Perm.MANAGE_VEHICLES)
    body = _body(request)
    license = _company_license(principal, license_id)
    mode = (body.get("mode") or "permanent").strip()

    if mode == "return":
        assignment = licensing.return_from_replacement(
            license=license, actor_user_id=principal.user_id
        )
    else:
        vehicle = _company_vehicle(principal, body.get("vehicle_id"))
        if mode == "temporary":
            planned_end = body.get("planned_end")
            if planned_end:
                from django.utils.dateparse import parse_datetime

                planned_end = parse_datetime(planned_end)
            assignment = licensing.start_temporary_replacement(
                license=license, replacement_vehicle=vehicle,
                planned_end=planned_end, actor_user_id=principal.user_id,
            )
        else:
            assignment = licensing.change_vehicle_permanently(
                license=license, new_vehicle=vehicle, actor_user_id=principal.user_id
            )
    return _json(request, {
        "ok": True, "assignmentId": str(assignment.id), "kind": assignment.kind,
        "vehicle": assignment.vehicle.plate,
        "message": "Telefonerna för den gamla bilen behöver godkännas på nytt.",
    })


# ---------------------------------------------------------------------------
# Beställningar
# ---------------------------------------------------------------------------


def _plan_from_body(company_id, body: dict, now=None) -> orders.ChangePlan:
    specs = [
        orders.VehicleSpec(
            plate=v.get("plate", ""), base_county=v.get("baseCounty", ""),
            label=v.get("label", ""), extra_counties=list(v.get("extraCounties") or []),
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
        now=now,
    )


@csrf_exempt
@require_POST
@handle
def quote(request):
    """
    POST /api/fleet/quote -- vad kostar ändringen?

    Visar kostnad nu, nästa period, moms, totalsumma och datum innan
    beställningen godkänns (§6). Ändrar ingenting.
    """
    principal = _principal(request, Perm.VIEW_BILLING)
    plan = _plan_from_body(principal.company_id, _body(request))
    return _json(request, {"ok": True, **plan.as_dict()})


@csrf_exempt
@require_POST
@handle
def create_order(request):
    """
    POST /api/fleet/orders -- lägg beställningen.

    Rättigheter träder i kraft först när betalningen är bekräftad av servern.
    Ett svar med `status: pending_payment` betyder precis det: ingenting har
    ändrats än.
    """
    principal = _principal(request, Perm.PURCHASE)
    body = _body(request)
    plan = _plan_from_body(principal.company_id, body)

    if not body.get("accepted"):
        raise orders.OrderError(
            "acceptance_required",
            "Kunden måste godkänna kvantitet, pris och betalningsdatum.",
        )

    payment = str(body.get("payment") or commerce.PAYMENT_CARD)
    if payment not in (commerce.PAYMENT_CARD, commerce.PAYMENT_INVOICE):
        payment = commerce.PAYMENT_CARD
    order, payment_info = commerce.place_order(
        principal.company_id, plan, created_by=principal.user_id, actor_kind="customer",
        payment=payment, idempotency=body.get("idempotency_key"),
    )
    notifications.order_confirmed(order)
    return _json(request, {
        "ok": True,
        "orderId": str(order.id),
        "status": order.status,
        # Stripes betalsida. Rättigheterna ges när Stripe bekräftat betalningen,
        # inte när kunden kommer tillbaka från sidan.
        "paymentUrl": payment_info.get("paymentUrl"),
        "paymentError": payment_info.get("stripeError"),
        "totalNowOre": order.total_now_ore,
        "nextPeriodTotalOre": order.next_period_total_ore,
        "effectiveAt": order.effective_at.isoformat() if order.effective_at else None,
        "lines": order.lines,
        "termsVersion": order.terms_version,
    })


@require_GET
@handle
def list_orders(request):
    """
    GET /api/fleet/orders -- beställningar och fakturareferenser.

    Åtkomlig även när liveinformationen är spärrad (§8): den här vyn kräver
    VIEW_BILLING, inte en giltig period.
    """
    principal = _principal(request, Perm.VIEW_BILLING)
    rows = [
        {
            "id": str(o.id), "kind": o.kind, "status": o.status,
            "createdAt": o.created_at.isoformat(),
            "totalNowOre": o.total_now_ore, "vatNowOre": o.vat_now_ore,
            "nextPeriodTotalOre": o.next_period_total_ore,
            "currency": o.currency, "lines": o.lines,
            "stripeInvoiceId": o.stripe_invoice_id,
            "paymentUrl": o.stripe_payment_url or None,
            "paidAt": o.paid_at.isoformat() if o.paid_at else None,
            "priceVersion": o.price_version_id,
            "termsVersion": o.terms_version,
        }
        for o in Order.objects.filter(company_id=principal.company_id).order_by("-created_at")[:100]
    ]
    return _json(request, {"ok": True, "orders": rows})


@csrf_exempt
@require_POST
@handle
def cancel(request):
    """POST /api/fleet/subscription/cancel"""
    principal = _principal(request, Perm.CANCEL_SUBSCRIPTION)
    change, _stripe = commerce.cancel_subscription(
        principal.company_id, actor_user_id=principal.user_id, actor_kind="customer",
        reason=_body(request).get("reason", ""),
    )
    notifications.cancellation_confirmed(principal.company_id, change.effective_at)
    return _json(request, {
        "ok": True,
        "effectiveAt": change.effective_at.isoformat(),
        "message": (
            "Abonnemanget avslutas vid periodens slut. Fram till dess fungerar "
            "allt som vanligt, och du kan ångra uppsägningen."
        ),
    })


@csrf_exempt
@require_POST
@handle
def undo_cancel(request):
    """POST /api/fleet/subscription/undo-cancel"""
    principal = _principal(request, Perm.CANCEL_SUBSCRIPTION)
    subscription, _stripe = commerce.undo_cancellation(
        principal.company_id, actor_user_id=principal.user_id, actor_kind="customer"
    )
    return _json(request, {
        "ok": True,
        "currentPeriodEnd": (
            subscription.current_period_end.isoformat()
            if subscription.current_period_end else None
        ),
    })


# ---------------------------------------------------------------------------
# Registrering, prov och säljarinbjudan
# ---------------------------------------------------------------------------


@csrf_exempt
@require_POST
@handle
def signup(request):
    """
    POST /api/fleet/signup -- knyter ett inloggat konto till ett företag och
    skapar provet i läget `pending`.

    Kräver inloggning (Supabase Auth har redan verifierat e-posten) och
    kontrollerade företagsuppgifter. Provet STARTAR inte här -- klockan börjar
    vid första telefonaktiveringen (§7).
    """
    principal = access.principal_for(request)
    if principal.user_id is None:
        raise PermissionDenied("login_required", "Logga in för att fortsätta.", status=401)

    body = _body(request)
    country = (body.get("country") or "SE").upper()
    org_number = body.get("orgNumber") or ""
    ratelimit.enforce(ratelimit.SIGNUP, f"{country}:{orgnr.normalize(org_number, country)}")

    if not orgnr.is_valid(org_number, country):
        raise trials.TrialError("invalid_org_number", "Organisationsnumret går inte att tolka.")

    member = CompanyMember.objects.filter(user_id=principal.user_id, status="active").first()
    if member is None:
        raise PermissionDenied(
            "no_company", "Kontot hör inte till något företag ännu.", status=403
        )
    company_id = member.company_id

    profile, _created = CompanyProfile.objects.update_or_create(
        company_id=company_id,
        defaults={
            "country": country,
            "org_number": orgnr.normalize(org_number, country),
            "legal_name": body.get("legalName", ""),
            "contact_name": body.get("contactName", ""),
            "contact_role": body.get("contactRole", ""),
            "contact_email": body.get("contactEmail", ""),
            "contact_phone": body.get("contactPhone", ""),
            "billing_email": body.get("billingEmail", ""),
            "billing_reference": body.get("billingReference", ""),
            # Ett organisationsnummer och en verifierad e-post är inte bevis på
            # företagsbehörighet (§7). Statusen börjar därför som obekräftad.
            "verification_status": CompanyProfile._meta.get_field(
                "verification_status"
            ).default,
        },
    )

    invite_code = (body.get("inviteCode") or "").strip()
    invite = None
    requires_payment_method = True
    if invite_code:
        invite = trials.find_invite(invite_code)
        if orgnr.normalize(invite.org_number, invite.country) != profile.org_number:
            raise trials.TrialError(
                "invite_org_mismatch", "Inbjudan gäller ett annat organisationsnummer."
            )
        requires_payment_method = False

    trial = trials.create_trial(
        company_id=company_id, country=country, org_number=org_number,
        source=(Trial.Source.SALES_INVITE if invite else Trial.Source.SELF_SIGNUP),
        invite=invite, requires_payment_method=requires_payment_method,
        actor_user_id=principal.user_id,
    )
    if invite is not None:
        trials.consume_invite(invite, company_id=company_id)

    orders.get_or_create_subscription(company_id)
    return _json(request, {
        "ok": True,
        "trialId": str(trial.id),
        "status": trial.status,
        "requiresPaymentMethod": requires_payment_method,
        "vehicleLimit": trial.vehicle_limit,
        "message": (
            "Provperioden startar när den första telefonen aktiveras."
            if requires_payment_method
            else "Kortfri provperiod. Utan beställning avslutas provet utan debitering."
        ),
    })


@csrf_exempt
@require_POST
@handle
def register(request):
    """
    POST /api/fleet/register -- appens registrering: nytt företag, kontot som
    ägare och en kortfri provperiod. Se fleet/registration.py.

        {"orgNumber": "556...", "companyName": "...", "contactName": "...",
         "contactPhone": "...", "vehicles": [{"plate": "ABC123", "baseCounty": "12"}]}

    E-postadressen läses ur den VERIFIERADE token, aldrig ur anropet.
    """
    from core.entitlement import verify_supabase_jwt
    from fleet import registration

    auth = request.headers.get("Authorization", "")
    payload = verify_supabase_jwt(auth[7:].strip()) if auth.lower().startswith("bearer ") else None
    if not payload:
        raise PermissionDenied("login_required", "Logga in för att fortsätta.", status=401)
    accounts.seen(payload)
    body = _body(request)
    country = (body.get("country") or "SE").upper()
    org_number = str(body.get("orgNumber") or "")
    ratelimit.enforce(ratelimit.SIGNUP, f"{country}:{orgnr.normalize(org_number, country)}")
    result = registration.register(
        user_id=payload.get("sub"), email=str(payload.get("email") or ""),
        org_number=org_number, company_name=str(body.get("companyName") or ""),
        contact_name=str(body.get("contactName") or ""),
        contact_phone=str(body.get("contactPhone") or ""),
        vehicles=body.get("vehicles") or [], country=country,
    )
    trial = result.trial
    return _json(request, {
        "ok": True,
        "created": result.created,
        "companyId": str(result.company.id),
        "companyName": result.company.name,
        "trial": (
            {"status": trial.status, "vehicleLimit": trial.vehicle_limit,
             "vehiclesUsed": trials.trial_vehicle_count(trial),
             "endsAt": trial.ends_at.isoformat() if trial.ends_at else None}
            if trial else None
        ),
        "message": result.trial_message,
    }, status=201 if result.created else 200)


@csrf_exempt
@require_POST
@handle
def trial_vehicles(request):
    """
    POST /api/fleet/trial/vehicles {"vehicles": [{"plate": "ABC123", "baseCounty": "12"}]}

    Fler bilar i ett pågående prov, upp till provets gräns. Kostar ingenting:
    fler bilar EFTER provet är en beställning, och den läggs i kundportalen
    eller av en säljare -- aldrig i appen (fleet/registration.py).
    """
    principal = _principal(request, Perm.MANAGE_VEHICLES)
    trial = trials.active_trial(principal.company_id)
    if trial is None:
        raise trials.TrialError(
            "no_active_trial",
            "Företaget har ingen pågående provperiod. Fler bilar beställs hos TaxiTips.",
        )
    with transaction.atomic():
        created = sales._add_trial_vehicles(
            trial, sales._vehicle_specs(_body(request).get("vehicles") or []),
            actor_user_id=principal.user_id, now=timezone.now(),
        )
    return _json(request, {
        "ok": True,
        "licenses": [str(license.id) for license in created],
        "vehiclesUsed": trials.trial_vehicle_count(trial),
        "vehicleLimit": trial.vehicle_limit,
    }, status=201)


@csrf_exempt
@require_POST
@handle
def claim_invite(request):
    """
    POST /api/fleet/claim-invite -- knyter det inloggade kontot till företaget
    som en säljare bjöd in dess e-postadress till (fleet/sales.py).

    E-postadressen läses ur den VERIFIERADE token, aldrig ur anropet: den som
    kan skicka ett påstående om en adress bevisar ingenting.
    """
    from core.entitlement import verify_supabase_jwt

    auth = request.headers.get("Authorization", "")
    payload = verify_supabase_jwt(auth[7:].strip()) if auth.lower().startswith("bearer ") else None
    if not payload:
        raise PermissionDenied("login_required", "Logga in för att fortsätta.", status=401)
    member = sales.claim_owner_invite(
        user_id=payload.get("sub"), email=str(payload.get("email") or "")
    )
    if member is None:
        return _json(request, {
            "ok": False, "reason": "no_invite",
            "message": "Det finns ingen inbjudan till den här e-postadressen.",
        }, status=404)
    return _json(request, {"ok": True, "companyId": str(member.company_id), "role": member.role})


@require_GET
@handle
def trial_eligibility(request):
    """GET /api/fleet/trial-eligibility?orgNumber=...&country=SE"""
    check = trials.eligibility(
        country=request.GET.get("country", "SE"),
        org_number=request.GET.get("orgNumber", ""),
    )
    return _json(request, {"ok": True, **check.as_dict()})


@csrf_exempt
@require_POST
@handle
def create_invite(request):
    """
    POST /api/fleet/invites -- säljarens kortfria inbjudan.

    Koden returneras en gång. `verificationNote` är obligatorisk: utan
    dokumenterad, verifierad företagskontakt skickas ingen inbjudan (§7).
    """
    principal = _principal(request, Perm.CREATE_SALES_INVITE)
    body = _body(request)
    invite, code = trials.create_invite(
        created_by=principal.user_id,
        country=body.get("country", "SE"),
        org_number=body.get("orgNumber", ""),
        company_name=body.get("companyName", ""),
        contact_name=body.get("contactName", ""),
        contact_email=body.get("contactEmail", ""),
        contact_phone=body.get("contactPhone", ""),
        verification_note=body.get("verificationNote", ""),
    )
    return _json(request, {
        "ok": True, "inviteId": str(invite.id), "code": code,
        "expiresAt": invite.expires_at.isoformat(),
    })


# ---------------------------------------------------------------------------
# Granskningar
# ---------------------------------------------------------------------------


@csrf_exempt
@require_POST
@handle
def resolve_review(request, review_id):
    """POST /api/fleet/reviews/<id>/resolve -- plattformens granskning."""
    principal = _principal(request, Perm.REVIEW_CASES)
    body = _body(request)
    review = ChangeReview.objects.filter(id=review_id).first()
    if review is None:
        raise licensing.LicensingError("unknown_review", "Ärendet finns inte.", status=404)
    risk.resolve_review(
        review, approved=bool(body.get("approved")), resolved_by=principal.user_id,
        note=body.get("note", ""),
    )
    return _json(request, {"ok": True, "status": review.status})


# ---------------------------------------------------------------------------
# Företag och behörigheter
# ---------------------------------------------------------------------------


@csrf_exempt
@require_POST
@handle
def remove_member(request):
    """POST /api/fleet/members/remove -- vägrar lämna abonnemanget ägarlöst."""
    principal = _principal(request, Perm.MANAGE_MEMBERS)
    ownership.remove_member(
        company_id=principal.company_id,
        user_id=_body(request).get("user_id"),
        actor_user_id=principal.user_id,
    )
    return _json(request, {"ok": True})


@csrf_exempt
@require_POST
@handle
def transfer_ownership(request):
    """
    POST /api/fleet/ownership/transfer -- steg 1 av 2.

    Kräver ny autentisering (tvåfaktor när kravet är påslaget). Mottagaren
    måste acceptera innan något byter plats.
    """
    principal = _principal(request)
    transfer = ownership.request_transfer(
        company_id=principal.company_id, from_principal=principal,
        to_user_id=_body(request).get("to_user_id"),
    )
    return _json(request, {
        "ok": True, "transferId": str(transfer.id),
        "expiresAt": transfer.expires_at.isoformat(),
        "message": "Mottagaren måste acceptera innan ägarrollen byter plats.",
    })


@csrf_exempt
@require_POST
@handle
def accept_ownership(request, transfer_id):
    """POST /api/fleet/ownership/<id>/accept -- steg 2 av 2."""
    principal = _principal(request)
    transfer = OwnershipTransfer.objects.filter(
        id=transfer_id, company_id=principal.company_id
    ).first()
    if transfer is None:
        raise ownership.OwnershipError("unknown_transfer", "Överföringen finns inte.", 404)
    ownership.accept_transfer(transfer=transfer, by_user_id=principal.user_id)
    return _json(request, {"ok": True, "role": "company_owner"})


@csrf_exempt
@require_POST
@handle
def close_account(request):
    """POST /api/fleet/company/close -- stoppar framtida förnyelse."""
    principal = _principal(request, Perm.CLOSE_ACCOUNT)
    result = ownership.close_account(
        company_id=principal.company_id, actor_user_id=principal.user_id
    )
    return _json(request, {"ok": True, **result})


@csrf_exempt
@require_POST
@handle
def change_contracting_party(request):
    """POST /api/fleet/company/contracting-party -- öppnar ett granskningsärende."""
    principal = _principal(request, Perm.TRANSFER_OWNERSHIP)
    body = _body(request)
    review = ownership.change_contracting_party(
        company_id=principal.company_id, country=body.get("country", "SE"),
        org_number=body.get("orgNumber", ""), actor_user_id=principal.user_id,
        note=body.get("note", ""),
    )
    return _json(request, {
        "ok": True, "reviewId": str(review.id), "status": review.status,
        "message": review.customer_message,
    })
