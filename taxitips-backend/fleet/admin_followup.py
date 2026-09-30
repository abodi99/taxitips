"""
Uppföljning av prov i adminwebben: listan säljaren ringer från.

Varje prov som pågår, väntar på första telefonen eller slutat de senaste
`ENDED_WINDOW_DAYS` dagarna utan att bli kund -- med kontaktuppgifterna,
dagarna kvar, om kunden redan sparat kort, flaggorna från registreringen
(fleet/signup_checks.flags) och säljarens senaste anteckning.

**Ordningen är arbetsordningen.** Först de som säljaren lovat att ringa och
vars tid är inne, sedan de vars prov tar slut snart, sedan de som redan tagit
slut. En lista i bokstavsordning hade låtit det brådskande hamna längst ner.

Läsa: `ADMIN_VIEW`. Skriva en anteckning: `ADMIN_SELL` -- säljaren ska kunna
göra det utan plattformsadministratörens tvåfaktor, och en anteckning flyttar
varken pengar eller rättigheter.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from billing.models import Company
from core.api import _json
from fleet import commerce, orgnr, signup_checks, trials
from fleet.admin_api import _body, _company_or_404, _iso, _record, _staff, handle
from fleet.models import (
    CompanyProfile, DeviceApproval, OutboxMessage, SalesFollowUp, Subscription,
    SubscriptionStatus, Trial,
)
from fleet.roles import Perm

ENDED_WINDOW_DAYS = 60
STOCKHOLM = ZoneInfo("Europe/Stockholm")


def _stage(trial: Trial, now) -> str:
    if trial.status == Trial.Status.PENDING:
        return "not_started"
    if trial.status == Trial.Status.ACTIVE:
        if trial.ends_at and trial.ends_at - now <= timedelta(days=3):
            return "ending"
        return "active"
    return "ended"


def _priority(row: dict, now) -> tuple:
    follow = row["followUp"]
    due = follow["nextContactAt"]
    if follow["outcome"] in ("not_interested", "customer", "wrong_details"):
        return (4, row["endsAt"] or "")
    if due and due <= now.isoformat():
        return (0, due)
    order = {"ending": 1, "ended": 2, "active": 3, "not_started": 3}
    return (order.get(row["stage"], 3), row["endsAt"] or "9999")


@require_GET
@handle
def followups(request):
    """GET /api/admin/followups -- provföretagen, i den ordning de ska ringas."""
    _staff(request, Perm.ADMIN_VIEW)
    now = timezone.now()
    trials_qs = Trial.objects.filter(
        status__in=[Trial.Status.PENDING, Trial.Status.ACTIVE],
    ) | Trial.objects.filter(
        status=Trial.Status.ENDED, ends_at__gte=now - timedelta(days=ENDED_WINDOW_DAYS),
    )
    from fleet import archive

    hidden = archive.archived_ids()
    latest: dict = {}
    for trial in trials_qs.exclude(source=Trial.Source.COUPON).order_by("created_at"):
        if trial.company_id not in hidden:
            latest[trial.company_id] = trial
    # Ett prov som slutat och sedan köpts (portalen, efter provslut) är inte
    # längre någon att sälja till.
    paying = set(
        Subscription.objects.filter(
            company_id__in=list(latest), status=SubscriptionStatus.ACTIVE,
        ).values_list("company_id", flat=True)
    )
    for company_id in paying:
        if latest[company_id].status == Trial.Status.ENDED:
            latest.pop(company_id)
    ids = list(latest)

    companies = {c.id: c for c in Company.objects.filter(id__in=ids)}
    profiles = {p.company_id: p for p in CompanyProfile.objects.filter(company_id__in=ids)}
    notes = {f.company_id: f for f in SalesFollowUp.objects.filter(company_id__in=ids)}
    phones = {}
    for approval in DeviceApproval.objects.filter(
        company_id__in=ids, status=DeviceApproval.Status.ACTIVE
    ).values_list("company_id", flat=True):
        phones[approval] = phones.get(approval, 0) + 1
    mails: dict = {}
    for message in OutboxMessage.objects.filter(
        company_id__in=ids, category__startswith="trial_", status=OutboxMessage.Status.SENT,
    ).order_by("sent_at"):
        mails.setdefault(message.company_id, []).append({
            "subject": message.subject, "sentAt": _iso(message.sent_at),
        })

    # Andra som försökt registrera samma organisationsnummer
    # (registration.report_duplicate_attempt): en kollega eller en främling.
    from fleet.models import AuditEvent

    duplicates: dict = {}
    for event in AuditEvent.objects.filter(
        company_id__in=ids, action="duplicate_signup_attempt",
    ).order_by("-created_at")[:500]:
        duplicates.setdefault(event.company_id, []).append(event)

    rows = []
    for company_id, trial in latest.items():
        company = companies.get(company_id)
        if company is None:
            continue
        profile = profiles.get(company_id)
        note = notes.get(company_id)
        commit = commerce.trial_commit_status(company_id)
        registry = (profile.registry if profile else {}) or {}
        days_left = (
            (trial.ends_at - now).total_seconds() / 86400 if trial.ends_at else None
        )
        rows.append({
            "companyId": str(company_id),
            "name": company.name,
            "legalName": (profile.legal_name if profile else "") or company.name,
            "orgNumber": orgnr.format_se(profile.org_number) if profile else (company.org_number or ""),
            "kind": signup_checks.org_kind(profile.org_number) if profile and profile.org_number else "",
            "contactName": profile.contact_name if profile else "",
            "phone": profile.contact_phone if profile else "",
            "email": (profile.contact_email if profile else "") or company.email or "",
            "registryCity": ((registry.get("address") or {}).get("city") or ""),
            "sni": registry.get("sni") or [],
            "source": trial.source,
            "trialStatus": trial.status,
            "stage": _stage(trial, now),
            "startedAt": _iso(trial.started_at),
            "endsAt": _iso(trial.ends_at),
            "daysLeft": round(days_left, 1) if days_left is not None else None,
            "cars": trials.trial_vehicle_count(trial),
            "vehicleLimit": trial.vehicle_limit,
            "phonesConnected": phones.get(company_id, 0),
            "committed": commit["committed"],
            "cardOnFile": commit["cardOnFile"],
            "mails": mails.get(company_id, []),
            "flags": signup_checks.flags(profile) + [
                {
                    "code": "duplicate_signup_attempt", "level": "warn",
                    "text": f"{(e.detail or {}).get('email', 'Okänd')} försökte registrera "
                            f"samma org.nr {e.created_at:%Y-%m-%d}. Kollega eller främling?",
                }
                for e in duplicates.get(company_id, [])[:3]
            ],
            "verificationStatus": profile.verification_status if profile else "",
            "createdAt": _iso(company.created_at),
            "followUp": {
                "outcome": note.outcome if note else SalesFollowUp.Outcome.NOT_CONTACTED,
                "note": note.note if note else "",
                "nextContactAt": _iso(note.next_contact_at) if note else None,
                "lastContactAt": _iso(note.last_contact_at) if note else None,
                "attempts": note.contact_attempts if note else 0,
                "updatedAt": _iso(note.updated_at) if note else None,
            },
        })
    rows.sort(key=lambda r: _priority(r, now))
    return _json(request, {
        "ok": True,
        "followUps": rows,
        "outcomes": [{"id": v, "label": label} for v, label in SalesFollowUp.Outcome.choices],
    })


@csrf_exempt
@require_POST
@handle
def update_followup(request, company_id):
    """
    POST /api/admin/followups/<company_id>
        {"outcome": "call_back", "note": "...", "nextContactAt": "2026-10-03T10:00",
         "contacted": true}

    `contacted` räknar upp försöken och sätter senaste kontakten till nu.
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
    if "note" in body:
        follow.note = str(body.get("note") or "")[:4000]
    if "nextContactAt" in body:
        raw = str(body.get("nextContactAt") or "").strip()
        when = None
        if raw:
            # Ett datum utan klockslag är "ring den dagen", kl. 09 svensk tid --
            # inte midnatt UTC, som hade blivit kvällen innan.
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
            "outcome": follow.outcome, "contacted": bool(body.get("contacted")),
            "next_contact_at": _iso(follow.next_contact_at),
        },
    )
    return _json(request, {"ok": True, "outcome": follow.outcome,
                           "attempts": follow.contact_attempts,
                           "nextContactAt": _iso(follow.next_contact_at)})
