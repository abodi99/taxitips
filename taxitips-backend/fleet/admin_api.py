"""
Adminwebbens API: kunder, abonnemang, notiser, evenemang och granskningar.

Det här är plattformens egen back-office -- inte kundportalen. Kundportalen
(fleet/api.py) visar ETT bolag för dess egna administratörer; den här visar
alla bolag för den som driver tjänsten.

**Vem får vad.** Allt kräver en aktiv `StaffRole`. Kundens roller i
`company_members` ger ingenting här, hur hög rollen än är: en bolagsägare är
inte plattformsadministratör. `support` läser, `platform_admin` läser och
ändrar. Kontrollen sker per anrop i `_staff()` -- en meny som döljer en knapp
skyddar ingenting.

**Varje ändring loggas** i `fleet_audit_event` med `actor_kind =
"platform_admin"`, så att en support-åtgärd går att skilja från något kunden
själv gjort. Aldrig en hemlighet i loggen.

**Inga hemligheter ut.** Svaren bär aldrig en enhetstoken, en push-token, en
parkopplingskods hash eller ett lösenord. Telefoner identifieras med id och
etikett.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from billing.models import Company, CompanyMember, Device
from core.api import _json
from core.models import PushDelivery
from fleet import access, audit, licensing, pairing, pricing, risk, roles, sessions
from fleet.api import _DOMAIN_ERRORS, _error
from fleet.models import (
    AuditEvent,
    ChangeReview,
    CompanyProfile,
    DeviceApproval,
    License,
    LicenseCounty,
    Order,
    OutboxMessage,
    PendingChange,
    Subscription,
    SubscriptionStatus,
    Trial,
    VehicleAssignment,
    VehicleSession,
)
from fleet.roles import Perm, PermissionDenied

log = logging.getLogger(__name__)

_LIST_LIMIT = 200


# ---------------------------------------------------------------------------
# Behörighet och felhantering
# ---------------------------------------------------------------------------


def _staff(request, permission: str) -> roles.Principal:
    """
    Plattformspersonal med rätt behörighet, annars ett fel.

    `principal_for` läser `StaffRole` före `company_members`, och en
    kundmedlem får därför aldrig en admin-behörighet här.
    """
    principal = access.principal_for(request)
    if principal.user_id is None:
        raise PermissionDenied("login_required", "Logga in för att fortsätta.", status=401)
    if not principal.staff_role:
        raise PermissionDenied(
            "not_staff", "Adminwebben är bara för plattformens personal.", status=403
        )
    roles.require(principal, permission)
    return principal


def handle(view):
    def wrapper(request, *args, **kwargs):
        try:
            return view(request, *args, **kwargs)
        except _DOMAIN_ERRORS as exc:
            return _error(request, exc)
        except Exception:
            log.exception("fleet.admin: oväntat fel i %s", view.__name__)
            return _json(
                request, {"ok": False, "reason": "internal_error", "message": "Något gick fel."},
                status=500,
            )

    wrapper.__name__ = view.__name__
    return wrapper


def _body(request) -> dict:
    try:
        return json.loads(request.body or b"{}")
    except ValueError:
        return {}


def _iso(value):
    return value.isoformat() if value else None


def _record(principal, action, *, company_id=None, subject_type="", subject_id="", detail=None):
    audit.record(
        action, company_id=company_id, actor_user_id=principal.user_id,
        actor_kind="platform_admin", subject_type=subject_type,
        subject_id=subject_id, detail=detail or {},
    )


# ---------------------------------------------------------------------------
# Översikt
# ---------------------------------------------------------------------------


def _monthly_ore(subscription: Subscription, now) -> int:
    """
    Det löpande månadsbeloppet för ett abonnemang, räknat av samma prismotor
    som fakturerar. En andra uträkning här hade kunnat visa en intäkt som
    fakturan inte bär.
    """
    count = licensing.billable_license_count(subscription.company_id)
    extras = licensing.extra_county_count(subscription.company_id, now)
    if not count and not extras:
        return 0
    quote = pricing.monthly_quote(
        subscription.price_version, licenses=count, extra_counties=extras,
        intro=pricing.intro_active(subscription, now),
    )
    return quote.amount_ore


@require_GET
@handle
def overview(request):
    """GET /api/admin/overview -- nyckeltal för hela tjänsten."""
    _staff(request, Perm.ADMIN_VIEW)
    now = timezone.now()
    day_ago = now - timedelta(hours=24)

    subs = Subscription.objects.select_related("price_version")
    by_status = {
        row["status"]: row["n"] for row in subs.values("status").annotate(n=Count("id"))
    }
    active = subs.filter(status=SubscriptionStatus.ACTIVE)
    mrr = sum(_monthly_ore(s, now) for s in active)

    push = {
        row["status"]: row["n"]
        for row in PushDelivery.objects.filter(created_at__gte=day_ago)
        .values("status").annotate(n=Count("id"))
    }

    return _json(request, {
        "ok": True,
        "companies": Company.objects.count(),
        "subscriptions": by_status,
        "mrrOre": mrr,
        "currency": "SEK",
        "trialsActive": Trial.objects.filter(status=Trial.Status.ACTIVE).count(),
        "licensesActive": License.objects.filter(
            status__in=[License.Status.ACTIVE, License.Status.PENDING_CANCEL]
        ).count(),
        "devices": Device.objects.count(),
        "sessionsActive": VehicleSession.objects.filter(ended_at__isnull=True).count(),
        "graceOpen": subs.filter(
            status=SubscriptionStatus.PAST_DUE, grace_until__gt=now
        ).count(),
        "reviewsOpen": ChangeReview.objects.filter(status=ChangeReview.Status.OPEN).count(),
        "push24h": push,
        "outboxPending": OutboxMessage.objects.filter(
            status=OutboxMessage.Status.PENDING
        ).count(),
        "generatedAt": now.isoformat(),
    })


# ---------------------------------------------------------------------------
# Kunder
# ---------------------------------------------------------------------------


@require_GET
@handle
def companies(request):
    """GET /api/admin/companies?q= -- sök på namn, organisationsnummer eller bolagskod."""
    _staff(request, Perm.ADMIN_VIEW)
    now = timezone.now()
    q = (request.GET.get("q") or "").strip()

    rows = Company.objects.all().order_by("name")
    if q:
        digits = "".join(ch for ch in q if ch.isdigit())
        filters = Q(name__icontains=q) | Q(join_code__iexact=q)
        if digits:
            filters |= Q(org_number__icontains=digits)
        rows = rows.filter(filters)
    rows = list(rows[:_LIST_LIMIT])

    ids = [c.id for c in rows]
    subs = {s.company_id: s for s in Subscription.objects.filter(company_id__in=ids)}
    license_counts = {
        row["company_id"]: row["n"]
        for row in License.objects.filter(
            company_id__in=ids,
            status__in=[License.Status.ACTIVE, License.Status.PENDING_CANCEL, License.Status.TRIAL],
        ).values("company_id").annotate(n=Count("id"))
    }
    device_counts = {
        row["company_id"]: row["n"]
        for row in Device.objects.filter(company_id__in=ids)
        .values("company_id").annotate(n=Count("id"))
    }

    out = []
    for company in rows:
        sub = subs.get(company.id)
        window = access.company_window(company.id, now)
        out.append({
            "id": str(company.id),
            "name": company.name,
            "orgNumber": company.org_number or "",
            "joinCode": company.join_code,
            "legacyStatus": company.status,
            "subscriptionStatus": sub.status if sub else "none",
            "periodEnd": _iso(sub.current_period_end) if sub else None,
            "cancelAtPeriodEnd": bool(sub and sub.cancel_at_period_end),
            "licenses": license_counts.get(company.id, 0),
            "devices": device_counts.get(company.id, 0),
            "accessOk": window.ok,
            "accessReason": window.reason,
            "createdAt": _iso(company.created_at),
        })
    return _json(request, {"ok": True, "companies": out, "truncated": len(rows) >= _LIST_LIMIT})


def _company_or_404(company_id) -> Company:
    company = Company.objects.filter(id=company_id).first()
    if company is None:
        raise licensing.LicensingError("unknown_company", "Bolaget finns inte.", status=404)
    return company


@require_GET
@handle
def company_detail(request, company_id):
    """GET /api/admin/companies/<id> -- allt om ett bolag, för en support-fråga."""
    _staff(request, Perm.ADMIN_VIEW)
    now = timezone.now()
    company = _company_or_404(company_id)
    profile = CompanyProfile.objects.filter(company_id=company.id).first()
    sub = Subscription.objects.filter(company_id=company.id).select_related("price_version").first()
    window = access.company_window(company.id, now)

    licenses = []
    for lic in License.objects.filter(company_id=company.id).order_by("-created_at"):
        serving = sessions.current_vehicle(lic)
        session = sessions.active_session_for_license(lic.id)
        assignment = VehicleAssignment.objects.filter(license=lic, ended_at__isnull=True).first()
        licenses.append({
            "id": str(lic.id),
            "status": lic.status,
            "vehicle": serving.plate if serving else "",
            "vehicleId": str(serving.id) if serving else None,
            "assignmentKind": assignment.kind if assignment else "",
            "baseCounty": lic.base_county,
            "scheduledBaseCounty": lic.scheduled_base_county,
            "counties": list(access.license_counties(lic.id, now)),
            "activePhone": (
                {"deviceId": str(session.device_id), "label": sessions.holder_label(session),
                 "since": _iso(session.started_at)}
                if session else None
            ),
            "approvals": [
                {"id": str(a.id), "deviceId": str(a.device_id), "label": a.label,
                 "status": a.status, "approvedAt": _iso(a.approved_at)}
                for a in DeviceApproval.objects.filter(license=lic).order_by("-approved_at")[:20]
            ],
        })

    # Telefonerna utan token och utan push-token i klartext: bara om de HAR en.
    devices = [
        {"id": str(d.id), "label": d.label, "kind": d.kind,
         "hasPush": bool(d.push_token), "lastSeenAt": _iso(d.last_seen_at),
         "counties": (d.notify_prefs or {}).get("counties", [])}
        for d in Device.objects.filter(company_id=company.id).order_by("-last_seen_at")[:50]
    ]
    members = [
        {"userId": str(m.user_id), "role": m.role, "status": m.status}
        for m in CompanyMember.objects.filter(company_id=company.id)
    ]
    trial = Trial.objects.filter(company_id=company.id).order_by("-created_at").first()

    return _json(request, {
        "ok": True,
        "company": {
            "id": str(company.id), "name": company.name, "email": company.email or "",
            "orgNumber": company.org_number or "", "joinCode": company.join_code,
            "legacyStatus": company.status, "legacySubscriptionStatus": company.subscription_status,
            "stripeCustomerId": company.stripe_customer_id or "",
            "createdAt": _iso(company.created_at),
        },
        "profile": (
            {"verificationStatus": profile.verification_status,
             "legalName": profile.legal_name, "contactEmail": profile.contact_email,
             "legacyAccessUntil": _iso(profile.legacy_access_until),
             "legacyCounties": profile.legacy_counties}
            if profile else None
        ),
        "access": {"ok": window.ok, "reason": window.reason, "validUntil": _iso(window.valid_until)},
        "subscription": (
            {"status": sub.status, "priceVersion": sub.price_version_id,
             "periodStart": _iso(sub.current_period_start), "periodEnd": _iso(sub.current_period_end),
             "cancelAtPeriodEnd": sub.cancel_at_period_end, "accessUntil": _iso(sub.access_until),
             "graceUntil": _iso(sub.grace_until), "introEndsAt": _iso(sub.intro_ends_at),
             "hadSuccessfulPayment": sub.had_successful_payment,
             "renewalStopped": bool(sub.renewal_stopped_at),
             "stripeSubscriptionId": sub.stripe_subscription_id,
             "monthlyOre": _monthly_ore(sub, now)}
            if sub else None
        ),
        "trial": (
            {"status": trial.status, "source": trial.source,
             "startedAt": _iso(trial.started_at), "endsAt": _iso(trial.ends_at),
             "vehicleLimit": trial.vehicle_limit}
            if trial else None
        ),
        "licenses": licenses,
        "devices": devices,
        "members": members,
        "orders": [
            {"id": str(o.id), "kind": o.kind, "status": o.status,
             "totalNowOre": o.total_now_ore, "nextPeriodTotalOre": o.next_period_total_ore,
             "createdAt": _iso(o.created_at), "paidAt": _iso(o.paid_at)}
            for o in Order.objects.filter(company_id=company.id).order_by("-created_at")[:30]
        ],
        "pendingChanges": [
            {"id": str(p.id), "kind": p.kind, "effectiveAt": _iso(p.effective_at), "payload": p.payload}
            for p in PendingChange.objects.filter(
                company_id=company.id, status=PendingChange.Status.PENDING
            )
        ],
        "reviews": risk.customer_status(company.id),
        "audit": [
            {"action": e.action, "actorKind": e.actor_kind, "at": _iso(e.created_at),
             "subject": f"{e.subject_type}:{e.subject_id}" if e.subject_type else "",
             "detail": e.detail}
            for e in AuditEvent.objects.filter(company_id=company.id).order_by("-created_at")[:50]
        ],
    })


@csrf_exempt
@require_POST
@handle
def set_subscription(request, company_id):
    """
    POST /api/admin/companies/<id>/subscription

    Support-åtgärd: sätt status och/eller förläng perioden. Rör INTE Stripe --
    det här är appens rättigheter, och en avvikelse mot Stripe dyker upp i
    avstämningen. Använd när en kund betalat utanför Stripe, eller för att ge
    ett testkonto åtkomst. Varje ändring loggas med före- och eftervärde.
    """
    principal = _staff(request, Perm.ADMIN_MANAGE)
    body = _body(request)
    company = _company_or_404(company_id)
    sub = Subscription.objects.filter(company_id=company.id).first()
    if sub is None:
        from fleet import orders

        sub = orders.get_or_create_subscription(company.id)

    before = {"status": sub.status, "periodEnd": _iso(sub.current_period_end)}
    updates = {}

    status = body.get("status")
    if status:
        if status not in SubscriptionStatus.values:
            raise licensing.LicensingError("invalid_status", f"Okänd status: {status}.")
        updates["status"] = status

    now = timezone.now()
    if body.get("extendDays") is not None:
        days = int(body["extendDays"])
        if not 1 <= days <= 366:
            raise licensing.LicensingError("invalid_days", "Förlängning 1–366 dagar.")
        base = sub.current_period_end if sub.current_period_end and sub.current_period_end > now else now
        updates["current_period_end"] = base + timedelta(days=days)
        updates.setdefault("current_period_start", sub.current_period_start or now)
        updates.setdefault("status", SubscriptionStatus.ACTIVE)
        # En förlängd period stänger en öppen frist och en stoppad förnyelse --
        # annars hade kunden fått tillbaka åtkomsten men ändå spärrats av
        # fristen som låg kvar.
        updates["grace_until"] = None
        updates["grace_origin"] = None
    elif body.get("periodEnd"):
        end = parse_datetime(str(body["periodEnd"]))
        if end is None:
            raise licensing.LicensingError("invalid_date", "Datumet går inte att tolka.")
        updates["current_period_end"] = end

    if not updates:
        raise licensing.LicensingError("nothing_to_do", "Ange status eller förlängning.")

    Subscription.objects.filter(id=sub.id).update(**updates)
    sub.refresh_from_db()
    _record(
        principal, "admin_subscription_changed", company_id=company.id,
        subject_type="subscription", subject_id=sub.id,
        detail={"before": before, "after": {"status": sub.status, "periodEnd": _iso(sub.current_period_end)},
                "note": str(body.get("note", ""))[:300]},
    )
    return _json(request, {"ok": True, "status": sub.status, "periodEnd": _iso(sub.current_period_end)})


@csrf_exempt
@require_POST
@handle
def issue_code(request, company_id):
    """
    POST /api/admin/companies/<id>/pairing-code -- en anslutningskod åt
    kunden, när deras egen administratör inte kan skapa en. Samma regler som
    kundens egen väg: fem minuter, hashad, loggad.
    """
    principal = _staff(request, Perm.ADMIN_MANAGE)
    body = _body(request)
    company = _company_or_404(company_id)
    license = License.objects.filter(id=body.get("license_id"), company_id=company.id).first()
    if license is None:
        raise licensing.LicensingError("unknown_license", "Licensen finns inte.", status=404)
    vehicle = sessions.current_vehicle(license)
    if vehicle is None:
        raise licensing.LicensingError("no_vehicle", "Licensen har ingen bil.")
    issued = pairing.issue_code(
        license=license, vehicle=vehicle, created_by=principal.user_id,
        label=str(body.get("label", "Support"))[:80],
    )
    _record(
        principal, "admin_pairing_code_issued", company_id=company.id,
        subject_type="license", subject_id=license.id, detail={"plate": vehicle.plate},
    )
    return _json(request, {"ok": True, **issued.as_dict()})


@csrf_exempt
@require_POST
@handle
def block_approval(request, approval_id):
    """POST /api/admin/approvals/<id>/block -- spärra en telefon åt kunden."""
    principal = _staff(request, Perm.ADMIN_MANAGE)
    approval = DeviceApproval.objects.filter(id=approval_id).first()
    if approval is None:
        raise licensing.LicensingError("unknown_approval", "Telefonen finns inte.", status=404)
    reason = str(_body(request).get("reason", "admin_block"))[:200]
    pairing.block_device(approval=approval, actor_user_id=principal.user_id, reason=reason)
    _record(
        principal, "admin_device_blocked", company_id=approval.company_id,
        subject_type="approval", subject_id=approval.id, detail={"reason": reason},
    )
    return _json(request, {"ok": True})


@csrf_exempt
@require_POST
@handle
def test_push(request, company_id):
    """
    POST /api/admin/companies/<id>/test-push -- samma kontroll som
    `manage.py send_test_push`, genom samma mottagargrind som riktiga notiser.
    """
    from django.conf import settings

    from billing import fcm
    from fleet.push_gate import can_receive

    principal = _staff(request, Perm.ADMIN_MANAGE)
    company = _company_or_404(company_id)
    service_account = fcm.load_service_account(settings.FIREBASE_SERVICE_ACCOUNT_JSON)
    if not service_account:
        raise licensing.LicensingError(
            "no_fcm", "Den här containern saknar FIREBASE_SERVICE_ACCOUNT_JSON.", status=503
        )
    access_token = fcm.get_access_token(service_account)

    results = []
    for device in Device.objects.filter(company_id=company.id):
        label = device.label or str(device.id)[:8]
        if not device.push_token:
            results.append({"device": label, "sent": False, "reason": "no_push_token"})
            continue
        verdict = can_receive(device, {})
        if not verdict.ok:
            results.append({"device": label, "sent": False, "reason": verdict.reason})
            continue
        res = fcm.send_push(
            service_account, access_token, token=device.push_token,
            title="TaxiTips", body="Testnotis från support.", data={"kind": "test"},
        )
        results.append({"device": label, "sent": bool(res.get("ok")),
                        "reason": "" if res.get("ok") else str(res.get("status"))})
    _record(
        principal, "admin_test_push", company_id=company.id, subject_type="company",
        subject_id=company.id, detail={"sent": sum(1 for r in results if r["sent"])},
    )
    return _json(request, {"ok": True, "results": results})


# ---------------------------------------------------------------------------
# Notiser
# ---------------------------------------------------------------------------


@require_GET
@handle
def notifications(request):
    """
    GET /api/admin/notifications?status=&company= -- notisloggen.

    Bara titel, text, status och fel -- aldrig enhetens token.
    """
    _staff(request, Perm.ADMIN_VIEW)
    rows = PushDelivery.objects.all().order_by("-created_at")
    status = request.GET.get("status")
    if status:
        rows = rows.filter(status=status)
    company_id = request.GET.get("company")
    if company_id:
        device_ids = list(Device.objects.filter(company_id=company_id).values_list("id", flat=True))
        rows = rows.filter(device_id__in=device_ids)
    rows = list(rows[:_LIST_LIMIT])

    labels = {
        str(d.id): (d.label, str(d.company_id))
        for d in Device.objects.filter(id__in=[r.device_id for r in rows])
    }
    names = {
        str(c.id): c.name
        for c in Company.objects.filter(id__in={v[1] for v in labels.values()})
    }
    out = []
    for r in rows:
        label, cid = labels.get(str(r.device_id), ("", ""))
        out.append({
            "id": str(r.id), "title": r.title, "body": r.body, "status": r.status,
            "error": r.error, "attempts": r.attempts, "device": label,
            "company": names.get(cid, ""), "createdAt": _iso(r.created_at),
            "sentAt": _iso(r.sent_at),
        })
    return _json(request, {"ok": True, "notifications": out})


# ---------------------------------------------------------------------------
# Evenemang
# ---------------------------------------------------------------------------


@require_GET
@handle
def events(request):
    """GET /api/admin/events?q=&hidden=1&days=14 -- kommande evenemang."""
    from events.models import Event

    _staff(request, Perm.ADMIN_VIEW)
    today = timezone.localdate()
    days = max(1, min(int(request.GET.get("days") or 14), 120))
    rows = Event.objects.filter(
        start_date__gte=today, start_date__lte=today + timedelta(days=days)
    ).order_by("start_date", "start_at")
    q = (request.GET.get("q") or "").strip()
    if q:
        rows = rows.filter(Q(name__icontains=q) | Q(venue_name__icontains=q) | Q(city__icontains=q))
    if request.GET.get("hidden") == "1":
        rows = rows.exclude(hidden_reason="")
    rows = list(rows[:_LIST_LIMIT])
    return _json(request, {
        "ok": True,
        "events": [
            {"id": e.id, "name": e.name, "source": e.source, "category": e.category,
             "startDate": e.start_date.isoformat(), "startAt": _iso(e.start_at),
             "venue": e.venue_name, "city": e.city, "region": e.region,
             "attendance": e.attendance, "hidden": bool(e.hidden_reason),
             "hiddenReason": e.hidden_reason, "url": e.url}
            for e in rows
        ],
    })


@csrf_exempt
@require_POST
@handle
def event_visibility(request, event_id):
    """
    POST /api/admin/events/<id>/visibility  {"hidden": true, "reason": "..."}

    Döljer eller visar ett evenemang för förarna. Skälet är obligatoriskt när
    något döljs -- `hidden_reason` är både flaggan och förklaringen.
    """
    from events.models import Event

    principal = _staff(request, Perm.ADMIN_MANAGE)
    body = _body(request)
    event = Event.objects.filter(id=event_id).first()
    if event is None:
        raise licensing.LicensingError("unknown_event", "Evenemanget finns inte.", status=404)
    if body.get("hidden"):
        reason = str(body.get("reason") or "").strip()[:200]
        if not reason:
            raise licensing.LicensingError("reason_required", "Ange varför evenemanget döljs.")
        new_reason = f"admin: {reason}"
    else:
        new_reason = ""
    Event.objects.filter(id=event.id).update(hidden_reason=new_reason)
    _record(
        principal, "admin_event_visibility", subject_type="event", subject_id=event.id,
        detail={"hidden": bool(new_reason), "reason": new_reason, "name": event.name[:120]},
    )
    return _json(request, {"ok": True, "hidden": bool(new_reason)})


# ---------------------------------------------------------------------------
# Granskningar
# ---------------------------------------------------------------------------


@require_GET
@handle
def reviews(request):
    """GET /api/admin/reviews?status=open -- riskärenden över alla bolag."""
    _staff(request, Perm.ADMIN_VIEW)
    rows = ChangeReview.objects.all().order_by("-created_at")
    status = request.GET.get("status", "open")
    if status:
        rows = rows.filter(status=status)
    rows = list(rows[:_LIST_LIMIT])
    names = {str(c.id): c.name for c in Company.objects.filter(id__in={r.company_id for r in rows})}
    return _json(request, {
        "ok": True,
        "reviews": [
            {"id": str(r.id), "company": names.get(str(r.company_id), ""),
             "companyId": str(r.company_id), "kind": r.kind, "status": r.status,
             "message": r.customer_message, "detail": r.detail,
             "createdAt": _iso(r.created_at), "resolvedAt": _iso(r.resolved_at)}
            for r in rows
        ],
    })


@csrf_exempt
@require_POST
@handle
def resolve_review(request, review_id):
    """POST /api/admin/reviews/<id>/resolve  {"approved": true, "note": "..."}"""
    principal = _staff(request, Perm.ADMIN_MANAGE)
    body = _body(request)
    review = ChangeReview.objects.filter(id=review_id).first()
    if review is None:
        raise licensing.LicensingError("unknown_review", "Ärendet finns inte.", status=404)
    risk.resolve_review(
        review, approved=bool(body.get("approved")), resolved_by=principal.user_id,
        note=str(body.get("note", ""))[:500],
    )
    return _json(request, {"ok": True, "status": review.status})
