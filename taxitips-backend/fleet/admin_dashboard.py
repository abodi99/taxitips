"""
Adminwebbens dashboard: hela tjänsten på en sida, ett avsnitt per perspektiv.

GET /api/admin/dashboard -- Ledning, Sälj, Support, Uppföljning, Drift och
Användning. Bara läsning, `ADMIN_VIEW`.

**Inget räknas om som redan räknas någon annanstans.** MRR kommer från samma
prismotor som Hem (`admin_api._monthly_ore`), risklägena från Uppföljningen
(`admin_followup`), datakällornas läge från statussidan (`admin_status._sources`,
som bara LÄSER `SourceStatus` -- ingen källa anropas härifrån) och de
försenade CRM-uppgifterna med samma regel som uppgiftsöversikten
(`crm_tasks`). Två definitioner av "betalande" eller "churn" hade gett två
sanningar på två sidor.

**Varje siffra säger vad den räknar.** Där en siffra bara går att räkna
ungefär står skälet i svaret (`basis`) och i vyn:

* MRR-linjen per vecka går inte att räkna ur dagens licenser -- en provbil som
  blev betald behåller sitt `created_at`, och abonnemangets status sparas utan
  historik. Varje betald beställning bär däremot månadsbeloppet prismotorn gav
  efter ändringen (`next_period_amount_ore`). Linjen är summan av varje bolags
  senaste sådana belopp vid veckans slut; dagens MRR räknas live som på Hem.
* Tipsen gallras efter sju dygn (`purge_old`), så tips per dag går bara sju
  dygn bakåt.

Arkiverade bolag (`fleet/archive.py`) räknas inte i lägesbilden -- de är dolda
överallt i adminwebben. I tratten och i veckotrenden räknas de: ett prov som
slutade utan köp och sedan arkiverades är ett riktigt bortfall, och utan det
hade konverteringen sett bättre ut än den är.

Inga hemligheter: inga tokens, inga hashar. E-post visas bara för konton som
slagit i telefonbytesgränsen, samma uppgift som Konton redan visar personalen.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.db.models import Count, Min, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone
from django.views.decorators.http import require_GET

from billing.models import Company
from core.api import _json
from core.models import (
    Opportunity, OpportunityFeedback, OpportunityReport, PushDelivery, SourceStatus,
)
from fleet import accounts, archive, crm_tasks, device_swaps, support
from fleet.admin_api import _iso, _monthly_ore, _staff, handle
from fleet.models import (
    ClientError,
    CrmTask,
    DeviceApproval,
    DeviceLinkEvent,
    DeviceSwapGrant,
    License,
    Order,
    OutboxMessage,
    Subscription,
    SubscriptionStatus,
    SupportThread,
    Trial,
    VehicleSession,
)
from fleet.roles import Perm

log = logging.getLogger(__name__)

STOCKHOLM = ZoneInfo("Europe/Stockholm")

TREND_WEEKS = 12
FUNNEL_DAYS = 90
TRIAL_ENDING_DAYS = 7
# Ett prov där ingen förare kört på så här länge har tappat fart: tre dygn är
# nästan halva provet (sju dygn).
INACTIVE_TRIAL_DAYS = 3
ACTIVE_DRIVER_DAYS = 7
# Gallringen tar tipsen efter sju dygn (core/repository.purge_old).
TIPS_DAYS = 7
OUTBOX_DAYS = 7
PUSH_DAYS = 7
LIST_LIMIT = 8

# Statusar där ett abonnemang betalar. Samma som Kunders filter "Betalande".
PAYING = (SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE)
PAID_ORDER = (Order.Status.PAID, Order.Status.APPLIED)
OPEN_TRIAL = (Trial.Status.PENDING, Trial.Status.ACTIVE)
OPEN_LICENSE = (License.Status.TRIAL, License.Status.ACTIVE, License.Status.PENDING_CANCEL)

# Hur länge en fråga väntat på svar, i fack som går att agera på.
WAIT_BUCKETS = (
    ("h1", "Under 1 h", 60),
    ("h4", "1–4 h", 4 * 60),
    ("h24", "4–24 h", 24 * 60),
    ("older", "Över ett dygn", None),
)


def _pct(part: int, whole: int) -> float | None:
    return round(100 * part / whole, 1) if whole else None


def _local_day(now) -> datetime:
    local = now.astimezone(STOCKHOLM)
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


def _week_starts(now) -> list[datetime]:
    """Måndag 00:00 (Stockholm) för de senaste TREND_WEEKS veckorna, äldst först."""
    today = _local_day(now)
    monday = today - timedelta(days=today.weekday())
    # Datumaritmetik i lokal tid och sedan en ny tidszonsättning: en vecka
    # över sommartidsbytet är 167 eller 169 timmar, inte 168.
    return [
        datetime.combine((monday - timedelta(weeks=i)).date(), datetime.min.time(), STOCKHOLM)
        for i in range(TREND_WEEKS - 1, -1, -1)
    ]


def _week_index(starts: list[datetime], when) -> int | None:
    if when is None or when < starts[0]:
        return None
    for i in range(len(starts) - 1, -1, -1):
        if when >= starts[i]:
            return i
    return None


def _company_rows(ids, names: dict) -> list[dict]:
    return [{"companyId": str(i), "name": names.get(i, "")} for i in ids]


# ---------------------------------------------------------------------------
# Ledning
# ---------------------------------------------------------------------------


def _paid_orders():
    """Betalda/verkställda beställningar med belopp: (bolag, när, månadsbelopp)."""
    out = []
    for company_id, paid_at, effective_at, created_at, monthly, total_now in Order.objects.filter(
        status__in=PAID_ORDER,
    ).values_list(
        "company_id", "paid_at", "effective_at", "created_at", "next_period_amount_ore",
        "total_now_ore",
    ):
        # En schemalagd minskning har ingen betalning; den gäller från
        # periodens slut (effective_at).
        out.append((company_id, paid_at or effective_at or created_at, monthly, total_now, paid_at))
    return out


def _ledning(now, hidden: set, paid_orders: list) -> dict:
    subs = Subscription.objects.select_related("price_version").exclude(company_id__in=hidden)
    active = subs.filter(status=SubscriptionStatus.ACTIVE)
    mrr = sum(_monthly_ore(s, now) for s in active)

    licenses = dict(
        License.objects.exclude(company_id__in=hidden)
        .filter(status__in=OPEN_LICENSE)
        .values_list("status").annotate(n=Count("id"))
    )

    starts = _week_starts(now)
    weeks = [
        {"weekStart": s.date().isoformat(), "newCompanies": 0, "newPaying": 0, "mrrOre": 0}
        for s in starts
    ]
    for created in Company.objects.filter(created_at__gte=starts[0]).values_list(
        "created_at", flat=True
    ):
        i = _week_index(starts, created)
        if i is not None:
            weeks[i]["newCompanies"] += 1

    # Ny betalande = veckan bolagets första betalning med belopp kom in.
    first_paid: dict = {}
    for company_id, _when, _monthly, total_now, paid_at in paid_orders:
        if paid_at and total_now > 0 and (
            company_id not in first_paid or paid_at < first_paid[company_id]
        ):
            first_paid[company_id] = paid_at
    for paid_at in first_paid.values():
        i = _week_index(starts, paid_at)
        if i is not None:
            weeks[i]["newPaying"] += 1

    # MRR vid veckans slut: varje bolags senaste månadsbelopp ur en betald
    # beställning, utom för abonnemang som hunnit avslutas (se docstringen).
    ended_at = {
        company_id: access_until or canceled_at
        for company_id, access_until, canceled_at in Subscription.objects.filter(
            status=SubscriptionStatus.CANCELED,
        ).values_list("company_id", "access_until", "canceled_at")
    }
    by_company: dict = {}
    for company_id, when, monthly, _total, _paid in paid_orders:
        by_company.setdefault(company_id, []).append((when, monthly))
    for rows in by_company.values():
        rows.sort(key=lambda r: r[0])
    for i, start in enumerate(starts):
        end = min(starts[i + 1], now) if i + 1 < len(starts) else now
        total = 0
        for company_id, rows in by_company.items():
            ended = ended_at.get(company_id, False)
            if ended is not False and (ended is None or ended <= end):
                continue
            latest = None
            for when, monthly in rows:
                if when > end:
                    break
                latest = monthly
            total += latest or 0
        weeks[i]["mrrOre"] = total

    return {
        "mrrOre": mrr,
        "companies": Company.objects.exclude(id__in=hidden).count(),
        "payingCompanies": subs.filter(status__in=PAYING).count(),
        "pastDue": subs.filter(status=SubscriptionStatus.PAST_DUE).count(),
        "carsPaid": licenses.get(License.Status.ACTIVE, 0) + licenses.get(License.Status.PENDING_CANCEL, 0),
        "carsTrial": licenses.get(License.Status.TRIAL, 0),
        "phonesApproved": DeviceApproval.objects.filter(
            status=DeviceApproval.Status.ACTIVE,
        ).exclude(company_id__in=hidden).count(),
        "activeDrivers": VehicleSession.objects.filter(
            last_seen_at__gte=now - timedelta(days=ACTIVE_DRIVER_DAYS),
        ).values("device_id").distinct().count(),
        "activeDriverDays": ACTIVE_DRIVER_DAYS,
        # Samma fråga som "Förare i tjänst nu" på Hem.
        "driversOnDuty": VehicleSession.objects.filter(ended_at__isnull=True).count(),
        "weeks": weeks,
        "mrrBasis": "paid_orders",
    }


# ---------------------------------------------------------------------------
# Sälj
# ---------------------------------------------------------------------------


def _funnel(now, hidden: set, paid_orders: list) -> dict:
    """
    Kohort: bolag registrerade de senaste FUNNEL_DAYS dagarna. Varje steg är en
    delmängd av det förra -- den som köpte utan prov räknas som att ha passerat
    provsteget, och antalet står för sig (`boughtWithoutTrial`).
    """
    cohort = set(
        Company.objects.filter(created_at__gte=now - timedelta(days=FUNNEL_DAYS))
        .values_list("id", flat=True)
    )
    started = set(
        Trial.objects.filter(company_id__in=cohort, started_at__isnull=False)
        .values_list("company_id", flat=True)
    )
    paid = {
        company_id for company_id, _w, _m, total_now, _p in paid_orders
        if company_id in cohort and total_now > 0
    } | set(
        Subscription.objects.filter(company_id__in=cohort, had_successful_payment=True)
        .values_list("company_id", flat=True)
    )
    passed_trial = started | paid
    registered = len(cohort)
    return {
        "windowDays": FUNNEL_DAYS,
        "registered": registered,
        "trialStarted": len(passed_trial),
        "paying": len(paid),
        "boughtWithoutTrial": len(paid - started),
        "archived": len(cohort & hidden),
        "rates": {
            "trialOfRegistered": _pct(len(passed_trial), registered),
            "payingOfTrial": _pct(len(paid), len(passed_trial)),
            "payingOfRegistered": _pct(len(paid), registered),
        },
    }


def _salj(now, hidden: set, paid_orders: list, open_trials: dict, names: dict) -> dict:
    ending = sorted(
        (t for t in open_trials.values()
         if t.status == Trial.Status.ACTIVE and t.ends_at and t.ends_at <= now + timedelta(days=TRIAL_ENDING_DAYS)),
        key=lambda t: t.ends_at,
    )

    # Registrerade senaste FUNNEL_DAYS, inte arkiverade och inte avslutade:
    # har de en bil, och sitter det en förare i den?
    canceled = set(
        Subscription.objects.filter(status=SubscriptionStatus.CANCELED).values_list("company_id", flat=True)
    )
    recent = list(
        Company.objects.filter(created_at__gte=now - timedelta(days=FUNNEL_DAYS))
        .exclude(id__in=hidden | canceled).order_by("-created_at").values_list("id", "name", "created_at")
    )
    ids = [r[0] for r in recent]
    with_car = set(
        License.objects.filter(company_id__in=ids, status__in=OPEN_LICENSE).values_list("company_id", flat=True)
    )
    with_driver = set(
        DeviceApproval.objects.filter(company_id__in=ids, status=DeviceApproval.Status.ACTIVE)
        .values_list("company_id", flat=True)
    )
    missing = []
    for company_id, name, created in recent:
        if company_id not in with_car:
            missing.append({"companyId": str(company_id), "name": name, "missing": "car", "createdAt": _iso(created)})
        elif company_id not in with_driver:
            missing.append({"companyId": str(company_id), "name": name, "missing": "driver", "createdAt": _iso(created)})

    # Samma regel som uppgiftsöversikten (crm_tasks.dashboard): öppen, datum före idag.
    day = crm_tasks.today()
    overdue = CrmTask.objects.filter(status__in=crm_tasks.OPEN_STATUSES, due_date__lt=day)
    per = [
        {"assignee": r["assignee_label"] or "", "count": r["n"]}
        for r in overdue.values("assignee_label").annotate(n=Count("id")).order_by("-n", "assignee_label")
    ]

    return {
        "funnel": _funnel(now, hidden, paid_orders),
        "trialsEnding": {
            "days": TRIAL_ENDING_DAYS,
            "count": len(ending),
            "rows": [
                {"companyId": str(t.company_id), "name": names.get(t.company_id, ""),
                 "endsAt": _iso(t.ends_at),
                 "daysLeft": round(max((t.ends_at - now).total_seconds(), 0) / 86400, 1)}
                for t in ending[:LIST_LIMIT]
            ],
        },
        "missingSetup": {
            "windowDays": FUNNEL_DAYS,
            "noCar": sum(1 for m in missing if m["missing"] == "car"),
            "noDriver": sum(1 for m in missing if m["missing"] == "driver"),
            "rows": missing[:LIST_LIMIT],
        },
        "crmOverdue": {
            "count": sum(p["count"] for p in per),
            "oldestDue": _iso(overdue.aggregate(m=Min("due_date"))["m"]),
            "perAssignee": per,
        },
    }


# ---------------------------------------------------------------------------
# Support
# ---------------------------------------------------------------------------


def _swap_limit(now) -> dict:
    """Konton som använt månadens telefonbyten (device_swaps.MONTHLY_LIMIT + extra)."""
    start, end = device_swaps.month_bounds(now)
    used = dict(
        DeviceLinkEvent.objects.filter(
            is_swap=True, admin_override=False, created_at__gte=start, created_at__lt=end,
        ).values_list("user_id").annotate(n=Count("id"))
    )
    grants = dict(
        DeviceSwapGrant.objects.filter(
            user_id__in=list(used), month_key=device_swaps.month_key(now),
        ).values_list("user_id").annotate(n=Count("id"))
    )
    hit = [
        (user_id, n, device_swaps.MONTHLY_LIMIT + grants.get(user_id, 0))
        for user_id, n in used.items()
        if n >= device_swaps.MONTHLY_LIMIT + grants.get(user_id, 0)
    ]
    hit.sort(key=lambda r: -r[1])
    emails = accounts.emails_for([str(u) for u, _n, _a in hit[:LIST_LIMIT]])
    return {
        "limit": device_swaps.MONTHLY_LIMIT,
        "month": device_swaps.month_key(now),
        "count": len(hit),
        "rows": [
            {"userId": str(u), "email": emails.get(str(u), ""), "used": n, "allowed": allowed}
            for u, n, allowed in hit[:LIST_LIMIT]
        ],
    }


def _support(now) -> dict:
    waiting = list(support.waiting_threads().values_list("last_customer_message_at", flat=True))
    buckets = {key: 0 for key, _label, _limit in WAIT_BUCKETS}
    for since in waiting:
        minutes = (now - since).total_seconds() / 60
        for key, _label, limit in WAIT_BUCKETS:
            if limit is None or minutes < limit:
                buckets[key] += 1
                break
    oldest = min(waiting) if waiting else None

    reports = OpportunityReport.objects.filter(status=OpportunityReport.Status.OPEN).aggregate(
        n=Count("id"), oldest=Min("created_at"),
    )

    # Rader, inte förekomster: samma fel räknas en gång per rad (fleet/client_activity.py
    # slår ihop upprepningar), precis som listan under "Appar och fel".
    errors = ClientError.objects.filter(last_at__gte=now - timedelta(days=7)).aggregate(
        app24=Count("id", filter=Q(source=ClientError.Source.APP, last_at__gte=now - timedelta(hours=24))),
        server24=Count("id", filter=Q(source=ClientError.Source.SERVER, last_at__gte=now - timedelta(hours=24))),
        app7=Count("id", filter=Q(source=ClientError.Source.APP)),
        server7=Count("id", filter=Q(source=ClientError.Source.SERVER)),
        crash7=Count("id", filter=Q(kind=ClientError.Kind.CRASH)),
    )

    return {
        "threadsOpen": SupportThread.objects.filter(
            status=SupportThread.Status.OPEN, last_message_at__isnull=False,
        ).count(),
        "threadsWaiting": len(waiting),
        "oldestWaitingSince": _iso(oldest),
        "waitBuckets": [
            {"key": key, "label": label, "count": buckets[key]} for key, label, _limit in WAIT_BUCKETS
        ],
        "tipReportsOpen": reports["n"],
        "oldestTipReportAt": _iso(reports["oldest"]),
        "errors": {
            "h24": {"app": errors["app24"], "server": errors["server24"]},
            "d7": {"app": errors["app7"], "server": errors["server7"], "crashes": errors["crash7"]},
        },
        # Egen savepoint: telefonbytestabellerna är nyare än resten av avsnittet.
        "swapLimit": _section("swapLimit", _swap_limit, now),
    }


# ---------------------------------------------------------------------------
# Uppföljning (risklägena ur admin_followup -- inte omräknade)
# ---------------------------------------------------------------------------


def _uppfoljning(now, hidden: set, risk: dict, open_trials: dict, names: dict) -> dict:
    from fleet import admin_followup

    open_orders = admin_followup._open_orders(now, hidden)
    by_segment: dict = {}
    for company_id, (segment, sub) in risk.items():
        by_segment.setdefault(segment, []).append((company_id, sub))

    # Prov utan aktivitet: öppet prov där ingen förare kört de senaste dagarna
    # (ett prov som väntar på första telefonen har per definition inte det).
    recent_drivers = set(
        VehicleSession.objects.filter(
            company_id__in=list(open_trials),
            last_seen_at__gte=now - timedelta(days=INACTIVE_TRIAL_DAYS),
        ).values_list("company_id", flat=True)
    )
    inactive = sorted(
        (t for cid, t in open_trials.items() if cid not in recent_drivers),
        key=lambda t: t.created_at,
    )

    # Churnrisk: förfallen betalning först, sedan uppsagda -- Uppföljningens ordning.
    at_risk = sorted(
        by_segment.get("past_due", []) + by_segment.get("pending_cancel", []),
        key=lambda r: (risk[r[0]][0] != "past_due", r[1].access_until or now),
    )
    return {
        "pastDue": len(by_segment.get("past_due", [])),
        "pendingCancel": len(by_segment.get("pending_cancel", [])),
        "churned": len(by_segment.get("churn", [])),
        "churnWindowDays": admin_followup.ENDED_WINDOW_DAYS,
        "unpaidOrders": {
            "companies": len(open_orders),
            "ore": sum(o.total_now_ore for rows in open_orders.values() for o in rows),
        },
        "inactiveTrials": {
            "days": INACTIVE_TRIAL_DAYS,
            "count": len(inactive),
            "rows": [
                {"companyId": str(t.company_id), "name": names.get(t.company_id, ""),
                 "status": t.status, "startedAt": _iso(t.started_at)}
                for t in inactive[:LIST_LIMIT]
            ],
        },
        "atRisk": [
            {"companyId": str(cid), "name": names.get(cid, ""), "segment": risk[cid][0],
             "accessUntil": _iso(sub.access_until)}
            for cid, sub in at_risk[:LIST_LIMIT]
        ],
    }


# ---------------------------------------------------------------------------
# Drift
# ---------------------------------------------------------------------------


def _drift(now) -> dict:
    from fleet import admin_status

    statuses = {s.source: s for s in SourceStatus.objects.all()}
    sources = [
        {"key": c["key"], "label": c["label"], "status": c["status"], "summary": c["summary"]}
        for c in admin_status._sources(statuses, now)
    ]
    counts: dict = {}
    for s in sources:
        counts[s["status"]] = counts.get(s["status"], 0) + 1

    categories: dict = {}
    for row in OutboxMessage.objects.filter(
        created_at__gte=now - timedelta(days=OUTBOX_DAYS),
    ).values("category", "status").annotate(n=Count("id")):
        entry = categories.setdefault(row["category"], {
            "category": row["category"], "sent": 0, "failed": 0, "pending": 0, "suppressed": 0,
        })
        entry[row["status"]] = entry.get(row["status"], 0) + row["n"]
    pending = OutboxMessage.objects.filter(status=OutboxMessage.Status.PENDING).aggregate(
        n=Count("id"), oldest=Min("created_at"),
    )

    since = _local_day(now) - timedelta(days=PUSH_DAYS - 1)
    push_status = dict(
        PushDelivery.objects.filter(created_at__gte=since)
        .values_list("status").annotate(n=Count("id"))
    )
    per_day = {
        (since + timedelta(days=i)).date().isoformat(): {"sent": 0, "failed": 0}
        for i in range(PUSH_DAYS)
    }
    for row in PushDelivery.objects.filter(
        created_at__gte=since, status__in=[PushDelivery.Status.SENT, PushDelivery.Status.FAILED],
    ).annotate(day=TruncDate("created_at", tzinfo=STOCKHOLM)).values("day", "status").annotate(n=Count("id")):
        key = row["day"].isoformat()
        if key in per_day:
            per_day[key][row["status"]] = row["n"]

    return {
        "sources": sources,
        "sourceCounts": counts,
        "outbox": {
            "days": OUTBOX_DAYS,
            "categories": sorted(
                categories.values(), key=lambda c: (-(c["failed"] + c["pending"]), c["category"])
            ),
            "pendingNow": pending["n"],
            "oldestPendingAt": _iso(pending["oldest"]),
        },
        "push": {
            "days": PUSH_DAYS,
            "byStatus": push_status,
            "perDay": [{"date": d, **v} for d, v in per_day.items()],
        },
    }


# ---------------------------------------------------------------------------
# Användning
# ---------------------------------------------------------------------------


def _anvandning(now) -> dict:
    def verdicts(since):
        return OpportunityFeedback.objects.filter(created_at__gte=since).aggregate(
            heading=Count("id", filter=Q(verdict=OpportunityFeedback.Verdict.HEADING)),
            fare=Count("id", filter=Q(verdict=OpportunityFeedback.Verdict.FARE)),
            empty=Count("id", filter=Q(verdict=OpportunityFeedback.Verdict.EMPTY)),
        )

    d7, d30 = verdicts(now - timedelta(days=7)), verdicts(now - timedelta(days=30))
    for block in (d7, d30):
        block["fareRate"] = _pct(block["fare"], block["fare"] + block["empty"])

    since = _local_day(now) - timedelta(days=TIPS_DAYS - 1)
    per_day = {
        (since + timedelta(days=i)).date().isoformat(): {"tips": 0, "road": 0}
        for i in range(TIPS_DAYS)
    }
    # Vägtipsen ligger i `context`, inte i förarens lista (AGENTS.md invariant 3):
    # de räknas för sig så att de inte blåser upp "tips".
    for row in (
        Opportunity.objects.filter(computed_at__gte=since, suppressed_at__isnull=True)
        .annotate(day=TruncDate("computed_at", tzinfo=STOCKHOLM))
        .values("day").annotate(
            tips=Count("id", filter=~Q(kind="road")), road=Count("id", filter=Q(kind="road")),
        )
    ):
        key = row["day"].isoformat()
        if key in per_day:
            per_day[key] = {"tips": row["tips"], "road": row["road"]}

    return {
        "feedback": {"d7": d7, "d30": d30},
        "tipsPerDay": [{"date": d, **v} for d, v in per_day.items()],
        "tipsRetentionDays": TIPS_DAYS,
    }


# ---------------------------------------------------------------------------
# Endpointen
# ---------------------------------------------------------------------------


def _kvalitet(now) -> dict:
    """
    Tipskvalitet och AI: månadens kostnad mot budgeten, dagens anrop per syfte,
    notiser som AI-grinden stoppade och den senaste nattrapporten
    (core/quality_report.py). Siffrorna räknas av koden, sammanfattningen av AI:n.
    """
    from core import ai_client
    from core.models import AiCall, QualityReport

    day_ago = now - timedelta(hours=24)
    calls = (
        AiCall.objects.filter(created_at__gte=day_ago)
        .values("purpose")
        .annotate(n=Count("id"), failed=Count("id", filter=Q(ok=False)), cost=Sum("cost_micro_usd"))
        .order_by("-n")
    )
    blocked = (
        Opportunity.objects.filter(notified_at__gte=day_ago)
        .extra(where=["reasons::text ilike %s"], params=["%AI stoppade notisen%"])
        .count()
    )
    latest = QualityReport.objects.order_by("-day").first()
    return {
        "aiEnabled": ai_client.unavailable_reason(now) is None,
        "aiBlockedReason": ai_client.unavailable_reason(now),
        "spend": ai_client.spend(now),
        "calls24h": [
            {"purpose": c["purpose"], "calls": c["n"], "failed": c["failed"],
             "costKr": round(ai_client.kronor(c["cost"] or 0), 2)}
            for c in calls
        ],
        "gateBlocked24h": blocked,
        "report": None if latest is None else {
            "day": latest.day.isoformat(),
            "summary": latest.summary,
            "suggestions": latest.suggestions,
            "notified": (latest.stats.get("notiser") or {}).get("tips"),
            "disagreements": (latest.stats.get("granskning") or {}).get("oeniga"),
            "examples": (latest.stats.get("granskning") or {}).get("exempel") or [],
        },
    }


def _section(name: str, fn, *args) -> dict:
    """
    Ett avsnitt i en egen savepoint. En tabell som saknas (migrationerna körs
    för sig i produktion, se AGENTS.md) eller ett fel i en fråga ska bli en
    rad text i det avsnittet -- inte ett 500 för hela sidan.
    """
    try:
        with transaction.atomic():
            return fn(*args)
    except Exception as exc:
        log.exception("admin_dashboard: avsnittet %s gick inte att räkna", name)
        return {"unavailable": True, "message": f"Gick inte att räkna ({type(exc).__name__})."}


def build(now=None) -> dict:
    from fleet import admin_followup

    now = now or timezone.now()
    hidden = archive.archived_ids()
    paid_orders = _paid_orders()
    # Öppna prov (väntar/pågår) per bolag, ur Uppföljningens urval: samma
    # bolag, samma undantag (kupong, redan betalande, arkiverade).
    open_trials = {
        cid: t for cid, t in admin_followup._trial_company_ids(now, hidden).items()
        if t.status in OPEN_TRIAL
    }
    risk = admin_followup._subscription_risk_ids(now, hidden)
    names = dict(
        Company.objects.filter(id__in=list(open_trials) + list(risk)).values_list("id", "name")
    )
    return {
        "ok": True,
        "currency": "SEK",
        "generatedAt": now.isoformat(),
        "ledning": _section("ledning", _ledning, now, hidden, paid_orders),
        "salj": _section("salj", _salj, now, hidden, paid_orders, open_trials, names),
        "support": _section("support", _support, now),
        "uppfoljning": _section("uppfoljning", _uppfoljning, now, hidden, risk, open_trials, names),
        "drift": _section("drift", _drift, now),
        "anvandning": _section("anvandning", _anvandning, now),
        "kvalitet": _section("kvalitet", _kvalitet, now),
    }


@require_GET
@handle
def dashboard(request):
    """GET /api/admin/dashboard -- hela tjänsten, ett avsnitt per perspektiv."""
    _staff(request, Perm.ADMIN_VIEW)
    response = _json(request, build())
    response["Cache-Control"] = "no-store"
    return response
