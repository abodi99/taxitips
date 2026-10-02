"""
Uppföljning i adminwebben: listan säljaren ringer från.

**Prov** som pågår, väntar på första telefonen eller slutat de senaste
`ENDED_WINDOW_DAYS` dagarna utan att bli betalande kund.

**Risk och churn:** förfallen betalning, uppsagt abonnemang som fortfarande
har åtkomst, och avslutade kunder som betalat -- med kundens angivna
uppsägningsorsak (PendingChange) och säljarens strukturerade avhoppsorsak.

Friska betalande abonnemang utan uppsägning syns inte här.

**Att betala:** beställningar som väntar på betalning eller misslyckats (utan
att en senare betalats), med belopp, ålder och betallänk. Plus en
betalningsöversikt: öppet belopp, förfallna och inbetalt den här månaden.

**Ordningen är arbetsordningen.** Utlovade samtal först, sedan det brådskande
(förfallen, avgår snart, prov tar slut), sedan prov som slutat och churn.

Läsa: `ADMIN_VIEW`. Skriva: `ADMIN_SELL`.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db.models import Q
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from billing.models import Company
from core.api import _json
from fleet import commerce, orgnr, signup_checks, trials
from fleet.admin_api import _body, _company_or_404, _iso, _record, _staff, handle
from fleet.models import (
    CompanyProfile,
    DeviceApproval,
    Order,
    OutboxMessage,
    PendingChange,
    SalesFollowUp,
    Subscription,
    SubscriptionStatus,
    Trial,
)
from fleet.roles import Perm

ENDED_WINDOW_DAYS = 60
STOCKHOLM = ZoneInfo("Europe/Stockholm")

CLOSED_OUTCOMES = frozenset({
    SalesFollowUp.Outcome.NOT_INTERESTED,
    SalesFollowUp.Outcome.WRONG_DETAILS,
    SalesFollowUp.Outcome.CUSTOMER,
})


def _trial_stage(trial: Trial, now) -> str:
    if trial.status == Trial.Status.PENDING:
        return "not_started"
    if trial.status == Trial.Status.ACTIVE:
        if trial.ends_at and trial.ends_at - now <= timedelta(days=3):
            return "ending"
        return "active"
    return "ended"


def _stated_cancel_reason(company_id) -> str:
    change = (
        PendingChange.objects.filter(
            company_id=company_id,
            kind=PendingChange.Kind.CANCEL_SUBSCRIPTION,
        )
        .order_by("-created_at")
        .first()
    )
    if change is None:
        return ""
    return str((change.payload or {}).get("reason") or "")[:500]


def _trial_company_ids(now, hidden: set) -> dict:
    trials_qs = Trial.objects.filter(
        status__in=[Trial.Status.PENDING, Trial.Status.ACTIVE],
    ) | Trial.objects.filter(
        status=Trial.Status.ENDED, ends_at__gte=now - timedelta(days=ENDED_WINDOW_DAYS),
    )
    latest: dict = {}
    for trial in trials_qs.exclude(source=Trial.Source.COUPON).order_by("created_at"):
        if trial.company_id not in hidden:
            latest[trial.company_id] = trial
    paying = set(
        Subscription.objects.filter(
            company_id__in=list(latest),
            status__in=[SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE],
        ).exclude(cancel_at_period_end=True).values_list("company_id", flat=True)
    )
    for company_id in paying:
        latest.pop(company_id, None)
    return latest


def _subscription_risk_ids(now, hidden: set) -> dict:
    """Bolag med förfallen betalning, uppsägning eller nyligen avslutat abonnemang."""
    window_start = now - timedelta(days=ENDED_WINDOW_DAYS)
    out: dict = {}

    # Uppsägning först; förfallen betalning vinner om båda gäller — den är
    # akutare och ska synas under "Avgår / betalning" med rätt pill.
    for sub in Subscription.objects.filter(
        cancel_at_period_end=True,
        status__in=[SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING, SubscriptionStatus.PAST_DUE],
    ).exclude(company_id__in=hidden):
        out[sub.company_id] = ("pending_cancel", sub)

    for sub in Subscription.objects.filter(status=SubscriptionStatus.PAST_DUE).exclude(
        company_id__in=hidden,
    ):
        out[sub.company_id] = ("past_due", sub)

    churned = Subscription.objects.filter(status=SubscriptionStatus.CANCELED).filter(
        Q(canceled_at__gte=window_start) | Q(access_until__gte=window_start),
    ).exclude(company_id__in=hidden)
    for sub in churned:
        # Bara den som faktiskt betalat (eller haft Stripe-abonnemang). Ett
        # avslutat "none"-abonnemang efter prov utan kort är inte churn.
        if sub.had_successful_payment or sub.stripe_subscription_id:
            out[sub.company_id] = ("churn", sub)
    return out


# En obetald beställning äldre än så räknas som förfallen i översikten. Stripe
# sparar förfallodagen på fakturan, inte vi; 14 dagar är standardvalet när
# säljaren skapar en faktura (admin_sales.create_order).
OVERDUE_AFTER_DAYS = 14


def _open_orders(now, hidden: set) -> dict:
    """
    company_id -> beställningar som ska betalas: väntar på betalning, eller
    misslyckades utan att en senare beställning betalats.
    """
    window_start = now - timedelta(days=ENDED_WINDOW_DAYS)
    last_paid = {}
    for company_id, paid_at in Order.objects.filter(
        status__in=[Order.Status.PAID, Order.Status.APPLIED], paid_at__gte=window_start,
    ).values_list("company_id", "paid_at"):
        if paid_at and (company_id not in last_paid or paid_at > last_paid[company_id]):
            last_paid[company_id] = paid_at
    out: dict = {}
    for order in Order.objects.filter(
        status__in=[Order.Status.PENDING_PAYMENT, Order.Status.FAILED],
        created_at__gte=window_start, total_now_ore__gt=0,
    ).exclude(company_id__in=hidden).order_by("created_at"):
        if order.status == Order.Status.FAILED and last_paid.get(order.company_id) and (
            last_paid[order.company_id] > order.created_at
        ):
            continue
        out.setdefault(order.company_id, []).append(order)
    return out


def _payment_order_row(order: Order, now, names: dict | None = None) -> dict:
    age = (now - order.created_at).days if order.created_at else 0
    row = {
        "id": str(order.id),
        "kind": order.kind,
        "kindLabel": Order.Kind(order.kind).label if order.kind in Order.Kind.values else order.kind,
        "status": order.status,
        "totalOre": order.total_now_ore,
        "createdAt": _iso(order.created_at),
        "paidAt": _iso(order.paid_at),
        "failedAt": _iso(order.failed_at),
        "failureReason": order.failure_reason,
        "ageDays": age,
        "overdue": order.status == Order.Status.FAILED or age >= OVERDUE_AFTER_DAYS,
        "paymentUrl": order.stripe_payment_url or None,
    }
    if names is not None:
        row["companyId"] = str(order.company_id)
        row["companyName"] = names.get(order.company_id, "")
    return row


def _payments_overview(now, hidden: set, open_orders: dict) -> dict:
    """Betalningsöversikten överst i fliken Betalningar."""
    local = now.astimezone(STOCKHOLM)
    month_start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    recent = list(
        Order.objects.filter(created_at__gte=now - timedelta(days=ENDED_WINDOW_DAYS), total_now_ore__gt=0)
        .exclude(company_id__in=hidden).order_by("-created_at")[:200]
    )
    names = {
        c.id: c.name for c in Company.objects.filter(id__in={o.company_id for o in recent})
    }
    open_list = [o for orders_ in open_orders.values() for o in orders_]
    paid_month = Order.objects.filter(
        status__in=[Order.Status.PAID, Order.Status.APPLIED], paid_at__gte=month_start,
    ).exclude(company_id__in=hidden)
    return {
        "summary": {
            "openOre": sum(o.total_now_ore for o in open_list),
            "openCount": len(open_list),
            "overdueCount": sum(
                1 for o in open_list
                if o.status == Order.Status.FAILED
                or (now - o.created_at).days >= OVERDUE_AFTER_DAYS
            ),
            "paidThisMonthOre": sum(paid_month.values_list("total_now_ore", flat=True)),
            "paidThisMonthCount": paid_month.count(),
            "pastDueSubscriptions": Subscription.objects.filter(
                status=SubscriptionStatus.PAST_DUE,
            ).exclude(company_id__in=hidden).count(),
        },
        "recent": [_payment_order_row(o, now, names) for o in recent],
        "overdueAfterDays": OVERDUE_AFTER_DAYS,
    }


def _priority(row: dict, now) -> tuple:
    follow = row["followUp"]
    due = follow["nextContactAt"]
    if follow["outcome"] in CLOSED_OUTCOMES:
        return (9, due or row.get("endsAt") or row.get("accessUntil") or "")
    if due and due <= now.isoformat():
        return (0, due)

    seg = row.get("segment", "trial")
    seg_order = {"past_due": 1, "unpaid": 1, "pending_cancel": 2, "trial": 3, "churn": 4}
    stage_order = {
        "payment_failed": 0, "unpaid": 0, "ending": 0, "leaving": 1, "ended": 2, "churned": 2,
        "not_started": 3, "active": 5,
    }
    return (
        seg_order.get(seg, 3),
        stage_order.get(row.get("stage", ""), 4),
        row.get("endsAt") or row.get("accessUntil") or "9999",
    )


def _follow_up_payload(note: SalesFollowUp | None) -> dict:
    return {
        "outcome": note.outcome if note else SalesFollowUp.Outcome.NOT_CONTACTED,
        "churnReason": (
            note.churn_reason if note and note.churn_reason
            else SalesFollowUp.ChurnReason.NOT_ASKED
        ),
        "note": note.note if note else "",
        "nextContactAt": _iso(note.next_contact_at) if note else None,
        "lastContactAt": _iso(note.last_contact_at) if note else None,
        "attempts": note.contact_attempts if note else 0,
        "updatedAt": _iso(note.updated_at) if note else None,
    }


def _enrich_rows(
    *,
    company_ids: list,
    trials_by_company: dict,
    subs_by_company: dict,
    companies: dict,
    profiles: dict,
    notes: dict,
    phones: dict,
    mails: dict,
    duplicates: dict,
    now,
    open_orders: dict | None = None,
) -> list[dict]:
    open_orders = open_orders or {}
    rows = []
    for company_id in company_ids:
        company = companies.get(company_id)
        if company is None:
            continue
        profile = profiles.get(company_id)
        note = notes.get(company_id)
        trial = trials_by_company.get(company_id)
        if company_id in subs_by_company:
            segment, sub = subs_by_company[company_id]
        elif trial is not None:
            segment, sub = "trial", None
        elif company_id in open_orders:
            segment, sub = "unpaid", None
        else:
            continue
        # En obetald beställning är det som ska göras nu -- utom när hela
        # abonnemanget redan är förfallet, som är akutare och har egen rad.
        if company_id in open_orders and segment != "past_due":
            segment = "unpaid"

        if segment == "trial" and trial is None:
            continue
        if segment == "unpaid" and sub is None:
            sub = Subscription.objects.filter(company_id=company_id).first()

        commit = commerce.trial_commit_status(company_id)
        registry = (profile.registry if profile else {}) or {}
        days_left = None
        stage = "active"
        ends_at = None
        trial_status = ""
        source = ""
        cars = 0
        vehicle_limit = 0

        if trial is not None and segment == "trial":
            stage = _trial_stage(trial, now)
            ends_at = trial.ends_at
            days_left = (
                (trial.ends_at - now).total_seconds() / 86400 if trial.ends_at else None
            )
            trial_status = trial.status
            source = trial.source
            cars = trials.trial_vehicle_count(trial)
            vehicle_limit = trial.vehicle_limit

        stated_reason = ""
        access_until = None
        subscription_status = ""
        if sub is not None:
            subscription_status = sub.status
            access_until = sub.access_until
            stated_reason = _stated_cancel_reason(company_id)
            if segment == "past_due":
                stage = "payment_failed"
            elif segment == "pending_cancel":
                stage = "leaving"
            elif segment == "churn":
                stage = "churned"
        if segment == "unpaid":
            stage = "unpaid"

        rows.append({
            "companyId": str(company_id),
            "segment": segment,
            "name": company.name,
            "legalName": (profile.legal_name if profile else "") or company.name,
            "orgNumber": orgnr.format_se(profile.org_number) if profile else (company.org_number or ""),
            "kind": signup_checks.org_kind(profile.org_number) if profile and profile.org_number else "",
            "contactName": profile.contact_name if profile else "",
            "phone": profile.contact_phone if profile else "",
            "email": (profile.contact_email if profile else "") or company.email or "",
            "registryCity": ((registry.get("address") or {}).get("city") or ""),
            "sni": registry.get("sni") or [],
            "source": source,
            "trialStatus": trial_status,
            "subscriptionStatus": subscription_status,
            "stage": stage,
            "startedAt": _iso(trial.started_at) if trial else None,
            "endsAt": _iso(ends_at),
            "accessUntil": _iso(access_until),
            "daysLeft": round(days_left, 1) if days_left is not None else None,
            "cars": cars,
            "vehicleLimit": vehicle_limit,
            "phonesConnected": phones.get(company_id, 0),
            "committed": commit["committed"],
            "cardOnFile": commit["cardOnFile"],
            "statedCancelReason": stated_reason,
            "mails": mails.get(company_id, []),
            "flags": signup_checks.flags(profile) + [
                {
                    "code": "duplicate_signup_attempt",
                    "level": "warn",
                    "text": f"{(e.detail or {}).get('email', 'Okänd')} försökte registrera "
                            f"samma org.nr {e.created_at:%Y-%m-%d}. Kollega eller främling?",
                }
                for e in duplicates.get(company_id, [])[:3]
            ],
            "verificationStatus": profile.verification_status if profile else "",
            "createdAt": _iso(company.created_at),
            "followUp": _follow_up_payload(note),
            "openOrders": [_payment_order_row(o, now) for o in open_orders.get(company_id, [])],
        })
    return rows


@require_GET
@handle
def followups(request):
    """GET /api/admin/followups -- prov, risk och churn i ringordning."""
    _staff(request, Perm.ADMIN_VIEW)
    now = timezone.now()
    from fleet import archive

    hidden = archive.archived_ids()
    latest_trials = _trial_company_ids(now, hidden)
    risk = _subscription_risk_ids(now, hidden)

    open_orders = _open_orders(now, hidden)

    trials_by_company = dict(latest_trials)
    subs_by_company = dict(risk)

    company_ids = list(dict.fromkeys(
        list(risk.keys()) + list(open_orders.keys()) + list(latest_trials.keys())
    ))

    companies = {c.id: c for c in Company.objects.filter(id__in=company_ids)}
    profiles = {p.company_id: p for p in CompanyProfile.objects.filter(company_id__in=company_ids)}
    notes = {f.company_id: f for f in SalesFollowUp.objects.filter(company_id__in=company_ids)}
    phones = {}
    for approval in DeviceApproval.objects.filter(
        company_id__in=company_ids, status=DeviceApproval.Status.ACTIVE
    ).values_list("company_id", flat=True):
        phones[approval] = phones.get(approval, 0) + 1
    mails: dict = {}
    for message in OutboxMessage.objects.filter(
        company_id__in=company_ids, category__startswith="trial_", status=OutboxMessage.Status.SENT,
    ).order_by("sent_at"):
        mails.setdefault(message.company_id, []).append({
            "subject": message.subject, "sentAt": _iso(message.sent_at),
        })

    from fleet.models import AuditEvent

    duplicates: dict = {}
    for event in AuditEvent.objects.filter(
        company_id__in=company_ids, action="duplicate_signup_attempt",
    ).order_by("-created_at")[:500]:
        duplicates.setdefault(event.company_id, []).append(event)

    rows = _enrich_rows(
        company_ids=company_ids,
        trials_by_company=trials_by_company,
        subs_by_company=subs_by_company,
        companies=companies,
        profiles=profiles,
        notes=notes,
        phones=phones,
        mails=mails,
        duplicates=duplicates,
        now=now,
        open_orders=open_orders,
    )
    rows.sort(key=lambda r: _priority(r, now))
    return _json(request, {
        "ok": True,
        "followUps": rows,
        "payments": _payments_overview(now, hidden, open_orders),
        "outcomes": [{"id": v, "label": label} for v, label in SalesFollowUp.Outcome.choices],
        "churnReasons": [
            {"id": v, "label": label} for v, label in SalesFollowUp.ChurnReason.choices
        ],
    })


@csrf_exempt
@require_POST
@handle
def update_followup(request, company_id):
    """
    POST /api/admin/followups/<company_id>
        {"outcome": "call_back", "churnReason": "price", "note": "...",
         "nextContactAt": "2026-10-03T10:00", "contacted": true}
    """
    principal = _staff(request, Perm.ADMIN_SELL)
    company = _company_or_404(company_id)
    body = _body(request)
    now = timezone.now()

    follow, _ = SalesFollowUp.objects.get_or_create(company_id=company.id)
    outcome = str(body.get("outcome") or follow.outcome)
    if outcome not in SalesFollowUp.Outcome.values:
        return _json(request, {"ok": False, "reason": "invalid_outcome",
                               "message": "Okänt utfall."}, status=400)
    follow.outcome = outcome
    if "churnReason" in body:
        churn = str(body.get("churnReason") or SalesFollowUp.ChurnReason.NOT_ASKED)
        if churn not in SalesFollowUp.ChurnReason.values:
            return _json(request, {"ok": False, "reason": "invalid_churn_reason",
                                   "message": "Okänd avhoppsorsak."}, status=400)
        follow.churn_reason = churn
    if "note" in body:
        follow.note = str(body.get("note") or "")[:4000]
    if "nextContactAt" in body:
        raw = str(body.get("nextContactAt") or "").strip()
        when = None
        if raw:
            day = parse_date(raw) if len(raw) == 10 else None
            if day is not None:
                when = datetime(day.year, day.month, day.day, 9, 0, tzinfo=STOCKHOLM)
            else:
                when = parse_datetime(raw)
                if when is None:
                    return _json(request, {"ok": False, "reason": "invalid_date",
                                           "message": "Datumet går inte att läsa."}, status=400)
                if timezone.is_naive(when):
                    when = when.replace(tzinfo=STOCKHOLM)
        follow.next_contact_at = when
    if body.get("contacted"):
        follow.contact_attempts += 1
        follow.last_contact_at = now
    follow.updated_by = principal.user_id
    follow.save()
    _record(
        principal, "sales_followup_updated", company_id=company.id,
        subject_type="company", subject_id=company.id,
        detail={
            "outcome": follow.outcome,
            "churn_reason": follow.churn_reason,
            "contacted": bool(body.get("contacted")),
            "next_contact_at": _iso(follow.next_contact_at),
        },
    )
    return _json(request, {
        "ok": True,
        "outcome": follow.outcome,
        "churnReason": follow.churn_reason,
        "attempts": follow.contact_attempts,
        "nextContactAt": _iso(follow.next_contact_at),
    })
