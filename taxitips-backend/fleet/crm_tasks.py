"""
Säljarens uppgifter i CRM — att göra kopplat till affär/konto/kontakt/kund.

Separat från uppföljningskön (SalesFollowUp), som gäller betalande kunder och
prov. Ingen koppling till Stripe eller självregistrering.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from django.db.models import Count, Q
from django.utils import timezone

from fleet import accounts
from fleet.models import CrmDeal, CrmTask, CrmTaskStatus, StaffRole

STOCKHOLM = ZoneInfo("Europe/Stockholm")
OPEN_STATUSES = (CrmTaskStatus.TODO, CrmTaskStatus.DOING)
TASK_LIMIT = 300
# Roller som kan få uppgifter tilldelade (supporten säljer inte).
ASSIGNABLE_ROLES = (StaffRole.Role.SALES, StaffRole.Role.PLATFORM_ADMIN)


def today() -> date:
    return timezone.now().astimezone(STOCKHOLM).date()


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def staff_label(user_id) -> str:
    """E-post för en i personalen (Principal saknar e-post)."""
    if not user_id:
        return ""
    return accounts.emails_for([user_id]).get(str(user_id), "")


def staff_options() -> list[dict]:
    """Säljare och plattformsadministratörer — valen i "Ansvarig"."""
    rows = list(
        StaffRole.objects.filter(is_active=True, role__in=ASSIGNABLE_ROLES)
        .order_by("created_at")
    )
    emails = accounts.emails_for([r.user_id for r in rows])
    out = [
        {
            "userId": str(r.user_id),
            "email": emails.get(str(r.user_id), ""),
            "role": r.role,
        }
        for r in rows
    ]
    return sorted(out, key=lambda r: (r["email"] or "~").lower())


def _bucket(task: CrmTask, day: date) -> str:
    if task.status == CrmTaskStatus.DONE:
        return "done"
    if task.due_date is None:
        return "nodate"
    if task.due_date < day:
        return "overdue"
    if task.due_date == day:
        return "today"
    if task.due_date <= day + timedelta(days=7):
        return "week"
    return "later"


def task_row(task: CrmTask, *, deal: CrmDeal | None = None, day: date | None = None) -> dict[str, Any]:
    day = day or today()
    row = {
        "id": str(task.id),
        "title": task.title,
        "body": task.body or "",
        "status": task.status,
        "dueDate": task.due_date.isoformat() if task.due_date else None,
        "bucket": _bucket(task, day),
        "assigneeUserId": str(task.assignee_user_id) if task.assignee_user_id else None,
        "assigneeLabel": task.assignee_label or "",
        "dealId": str(task.deal_id) if task.deal_id else None,
        "accountId": str(task.account_id) if task.account_id else None,
        "personId": str(task.person_id) if task.person_id else None,
        "companyId": str(task.company_id) if task.company_id else None,
        "createdByLabel": task.created_by_label or "",
        "completedAt": _iso(task.completed_at),
        "createdAt": _iso(task.created_at),
        "updatedAt": _iso(task.updated_at),
        "dealName": "",
    }
    if deal is not None:
        row["dealName"] = (deal.account.name if deal.account_id and deal.account else "") or deal.name
    return row


def _rows_with_deals(tasks: list[CrmTask]) -> list[dict]:
    deal_ids = {t.deal_id for t in tasks if t.deal_id}
    deals = {
        d.id: d
        for d in CrmDeal.objects.filter(id__in=deal_ids).select_related("account")
    }
    day = today()
    return [task_row(t, deal=deals.get(t.deal_id), day=day) for t in tasks]


def _parse_date(value) -> date | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw[:10])
    except ValueError as exc:
        raise ValueError("invalid_date") from exc


def _parse_status(value) -> str:
    status = str(value or "").strip()
    if status not in CrmTaskStatus.values:
        raise ValueError("invalid_status")
    return status


def _assignee(value) -> tuple[Any, str]:
    uid = str(value or "").strip()
    if not uid:
        return None, ""
    if not StaffRole.objects.filter(user_id=uid, is_active=True).exists():
        raise ValueError("invalid_assignee")
    return uid, staff_label(uid)


def create_task(
    *,
    title: str,
    body: str = "",
    due_date=None,
    status: str = CrmTaskStatus.TODO,
    assignee_user_id=None,
    deal: CrmDeal | None = None,
    company_id=None,
    person_id=None,
    created_by_user_id=None,
) -> CrmTask:
    text = (title or "").strip()
    if not text:
        raise ValueError("title_required")
    assignee, label = _assignee(assignee_user_id)
    status = _parse_status(status)
    return CrmTask.objects.create(
        title=text[:200],
        body=(body or "").strip()[:4000],
        status=status,
        due_date=_parse_date(due_date),
        assignee_user_id=assignee,
        assignee_label=label,
        deal_id=deal.id if deal else None,
        account_id=deal.account_id if deal else None,
        person_id=person_id or (deal.person_id if deal else None),
        company_id=company_id or (deal.company_id if deal else None),
        created_by_user_id=created_by_user_id,
        created_by_label=staff_label(created_by_user_id),
        completed_at=timezone.now() if status == CrmTaskStatus.DONE else None,
    )


def update_task(task: CrmTask, data: dict) -> CrmTask:
    fields: list[str] = []
    if "title" in data:
        title = str(data.get("title") or "").strip()
        if not title:
            raise ValueError("title_required")
        task.title = title[:200]
        fields.append("title")
    if "body" in data:
        task.body = str(data.get("body") or "").strip()[:4000]
        fields.append("body")
    if "dueDate" in data:
        task.due_date = _parse_date(data.get("dueDate"))
        fields.append("due_date")
    if "assigneeUserId" in data:
        task.assignee_user_id, task.assignee_label = _assignee(data.get("assigneeUserId"))
        fields += ["assignee_user_id", "assignee_label"]
    if "status" in data:
        status = _parse_status(data.get("status"))
        if status != task.status:
            task.status = status
            task.completed_at = timezone.now() if status == CrmTaskStatus.DONE else None
            fields += ["status", "completed_at"]
    if fields:
        fields.append("updated_at")
        task.save(update_fields=fields)
    return task


def get_task(task_id) -> CrmTask | None:
    return CrmTask.objects.filter(id=task_id).first()


def tasks_for(*, deal: CrmDeal | None = None, company_id=None, limit: int = 100) -> list[dict]:
    """Uppgifter på en affär (och dess konto) eller en TaxiTips-kund — öppna först."""
    q = Q()
    if deal is not None:
        q |= Q(deal_id=deal.id)
        if deal.account_id:
            q |= Q(account_id=deal.account_id)
    if company_id:
        q |= Q(company_id=company_id)
    if not q:
        return []
    # Öppna: närmast datum först, utan datum sist. Sedan de senast klara.
    open_tasks = list(CrmTask.objects.filter(q, status__in=OPEN_STATUSES)[:limit])
    open_tasks.sort(key=lambda t: (t.due_date is None, t.due_date or date.max, t.created_at))
    done = list(
        CrmTask.objects.filter(q, status=CrmTaskStatus.DONE)
        .order_by("-completed_at", "-updated_at")[:20]
    )
    return _rows_with_deals(open_tasks + done)


def _scope(assignee: str, me) -> Q:
    if assignee == "me":
        return Q(assignee_user_id=me)
    if assignee == "none":
        return Q(assignee_user_id__isnull=True)
    if assignee in ("", "all"):
        return Q()
    return Q(assignee_user_id=assignee)


def dashboard(*, me, assignee: str = "me", status: str = "open", limit: int = TASK_LIMIT) -> dict:
    """
    Uppgiftsöversikt: lista för vald säljare/status, siffror per tidsfack och
    en rad per säljare (öppna, försenade, pågår, klara senaste 7 dagarna).
    """
    day = today()
    week_ago = timezone.now() - timedelta(days=7)
    scope = _scope(assignee, me)
    base = CrmTask.objects.filter(scope)

    open_q = Q(status__in=OPEN_STATUSES)
    summary = base.aggregate(
        open=Count("id", filter=open_q),
        overdue=Count("id", filter=open_q & Q(due_date__lt=day)),
        today=Count("id", filter=open_q & Q(due_date=day)),
        week=Count("id", filter=open_q & Q(due_date__gt=day, due_date__lte=day + timedelta(days=7))),
        nodate=Count("id", filter=open_q & Q(due_date__isnull=True)),
        doing=Count("id", filter=Q(status=CrmTaskStatus.DOING)),
        doneWeek=Count("id", filter=Q(status=CrmTaskStatus.DONE, completed_at__gte=week_ago)),
    )

    if status == "open":
        listed = base.filter(open_q)
    elif status in CrmTaskStatus.values:
        listed = base.filter(status=status)
    else:
        listed = base
    if status == CrmTaskStatus.DONE:
        listed = listed.order_by("-completed_at", "-updated_at")
        tasks = list(listed[:limit])
    else:
        tasks = list(listed.order_by("due_date", "created_at")[:limit])
        tasks.sort(key=lambda t: (t.due_date is None, t.due_date or date.max))

    per = {
        str(r["assignee_user_id"]) if r["assignee_user_id"] else "": r
        for r in CrmTask.objects.values("assignee_user_id").annotate(
            open=Count("id", filter=open_q),
            overdue=Count("id", filter=open_q & Q(due_date__lt=day)),
            doing=Count("id", filter=Q(status=CrmTaskStatus.DOING)),
            doneWeek=Count("id", filter=Q(status=CrmTaskStatus.DONE, completed_at__gte=week_ago)),
        )
    }
    staff = staff_options()
    known = {s["userId"] for s in staff}
    # Uppgifter hos någon som inte längre är aktiv säljare ska ändå synas.
    extra = [uid for uid in per if uid and uid not in known]
    extra_emails = accounts.emails_for(extra)
    people = staff + [{"userId": uid, "email": extra_emails.get(uid, ""), "role": ""} for uid in extra]
    per_seller = []
    for s in people:
        r = per.get(s["userId"], {})
        per_seller.append({
            "userId": s["userId"],
            "email": s["email"],
            "open": r.get("open", 0),
            "overdue": r.get("overdue", 0),
            "doing": r.get("doing", 0),
            "doneWeek": r.get("doneWeek", 0),
        })
    unassigned = per.get("", {})
    if unassigned.get("open") or unassigned.get("doneWeek"):
        per_seller.append({
            "userId": "none",
            "email": "",
            "open": unassigned.get("open", 0),
            "overdue": unassigned.get("overdue", 0),
            "doing": unassigned.get("doing", 0),
            "doneWeek": unassigned.get("doneWeek", 0),
        })

    return {
        "today": day.isoformat(),
        "assignee": assignee,
        "status": status,
        "summary": summary,
        "rows": _rows_with_deals(tasks),
        "perSeller": per_seller,
        "staff": staff,
        "statuses": [{"id": v, "label": label} for v, label in CrmTaskStatus.choices],
    }


def open_count_for(user_id) -> int:
    if not user_id:
        return 0
    return CrmTask.objects.filter(assignee_user_id=user_id, status__in=OPEN_STATUSES).count()
