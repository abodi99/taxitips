"""
Adminwebbens vy över appar och fel (admin.html, "Appar och fel").

* GET /api/admin/activity/clients -- per konto och telefon: senaste
  inloggning, senast sedd, appversion, plattform, OS och modell. Plus hur
  många som kör varje version, för att se när en gammal version dött ut.
* GET /api/admin/activity/errors -- appens krascher och misslyckade flöden,
  och serverns 5xx, nyast först.

Läsa kräver ADMIN_VIEW: det här är supportens verktyg. Inget här ändrar
något, och inget svar bär en token -- det finns ingen att bära
(fleet/client_activity.py sparar aldrig någon).
"""

from __future__ import annotations

from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone
from django.views.decorators.http import require_GET

from billing.models import Company, Device
from core.api import _json
from fleet import accounts
from fleet.admin_api import _iso, _staff, handle
from fleet.models import ClientActivity, ClientError, KnownAccount
from fleet.roles import Perm

_LIMIT = 200


def _uuid_or_none(value):
    import uuid

    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError):
        return None


def _days(request, default: int, maximum: int) -> int:
    try:
        days = int(request.GET.get("days") or default)
    except ValueError:
        days = default
    return max(1, min(days, maximum))


def _labels(user_ids, device_ids, company_ids):
    emails = accounts.emails_for([str(u) for u in user_ids if u])
    devices = {
        str(d.id): d
        for d in Device.objects.filter(id__in=[d for d in device_ids if d])
    }
    companies = {
        str(c.id): c.name
        for c in Company.objects.filter(id__in=[c for c in company_ids if c])
    }
    return emails, devices, companies


def activity_row(row: ClientActivity | None) -> dict | None:
    """En rad utan etiketter -- för kontolistan, som redan har e-posten."""
    if row is None:
        return None
    return {
        "kind": row.subject_kind,
        "id": str(row.subject_id),
        "companyId": str(row.company_id) if row.company_id else None,
        "firstSeenAt": _iso(row.first_seen_at),
        "lastSeenAt": _iso(row.last_seen_at),
        "lastLoginAt": _iso(row.last_login_at),
        "appVersion": row.app_version,
        "appBuild": row.app_build,
        "platform": row.platform,
        "osVersion": row.os_version,
        "deviceModel": row.device_model,
        "ipPrefix": row.ip_prefix,
        "country": row.country,
    }


def activity_for_user(user_id) -> dict | None:
    return activity_row(
        ClientActivity.objects.filter(subject_kind="user", subject_id=user_id).first()
    )


@require_GET
@handle
def clients(request):
    """
    GET /api/admin/activity/clients?company=&q=&platform=&kind=user|device&days=

    `days` begränsar till dem som hörts av de senaste N dygnen (standard: alla).
    """
    _staff(request, Perm.ADMIN_VIEW)
    rows = ClientActivity.objects.all().order_by("-last_seen_at")
    company = _uuid_or_none(request.GET.get("company"))
    if company:
        rows = rows.filter(company_id=company)
    kind = request.GET.get("kind") or ""
    if kind in ClientActivity.Kind.values:
        rows = rows.filter(subject_kind=kind)
    platform = (request.GET.get("platform") or "").lower()
    if platform:
        rows = rows.filter(platform=platform)
    if request.GET.get("days"):
        rows = rows.filter(last_seen_at__gte=timezone.now() - timedelta(days=_days(request, 30, 400)))
    q = (request.GET.get("q") or "").strip()
    if q:
        user_ids = list(
            KnownAccount.objects.filter(email__icontains=q.lower()).values_list("user_id", flat=True)[:200]
        )
        device_ids = list(Device.objects.filter(label__icontains=q).values_list("id", flat=True)[:200])
        company_ids = list(Company.objects.filter(name__icontains=q).values_list("id", flat=True)[:50])
        match = (
            Q(app_version__icontains=q) | Q(device_model__icontains=q) | Q(os_version__icontains=q)
            | Q(subject_kind="user", subject_id__in=user_ids)
            | Q(subject_kind="device", subject_id__in=device_ids)
            | Q(company_id__in=company_ids)
        )
        as_id = _uuid_or_none(q)
        if as_id:
            match |= Q(subject_id=as_id)
        rows = rows.filter(match)

    # Versionsfördelningen gäller samma urval men bara de senaste 30 dygnen:
    # en telefon som inte startats på ett halvår säger inget om vilka
    # versioner som är ute nu.
    recent = rows.filter(last_seen_at__gte=timezone.now() - timedelta(days=30)).exclude(app_version="")
    versions = [
        {"platform": v["platform"], "appVersion": v["app_version"], "count": v["n"]}
        for v in recent.values("platform", "app_version").annotate(n=Count("id")).order_by("-n")[:30]
    ]

    rows = list(rows[:_LIMIT])
    emails, devices, companies = _labels(
        [r.subject_id for r in rows if r.subject_kind == "user"],
        [r.subject_id for r in rows if r.subject_kind == "device"],
        [r.company_id for r in rows],
    )
    out = []
    for r in rows:
        item = activity_row(r)
        key = str(r.subject_id)
        if r.subject_kind == "user":
            item["label"] = emails.get(key, "")
        else:
            device = devices.get(key)
            item["label"] = device.label if device else ""
            item["deviceKind"] = device.kind if device else ""
        item["companyName"] = companies.get(str(r.company_id), "") if r.company_id else ""
        out.append(item)
    return _json(request, {"ok": True, "clients": out, "versions": versions, "limit": _LIMIT})


@require_GET
@handle
def errors(request):
    """
    GET /api/admin/activity/errors?days=7&source=app|server&kind=crash|flow|server
        &flow=&platform=&company=&device=&user=&q=
    """
    _staff(request, Perm.ADMIN_VIEW)
    days = _days(request, 7, 30)
    since = timezone.now() - timedelta(days=days)
    rows = ClientError.objects.filter(last_at__gte=since)
    company = _uuid_or_none(request.GET.get("company"))
    if company:
        rows = rows.filter(company_id=company)
    device = _uuid_or_none(request.GET.get("device"))
    if device:
        rows = rows.filter(device_id=device)
    user = _uuid_or_none(request.GET.get("user"))
    if user:
        rows = rows.filter(user_id=user)
    source = request.GET.get("source") or ""
    if source in ClientError.Source.values:
        rows = rows.filter(source=source)
    kind = request.GET.get("kind") or ""
    if kind in ClientError.Kind.values:
        rows = rows.filter(kind=kind)
    platform = (request.GET.get("platform") or "").lower()
    if platform:
        rows = rows.filter(platform=platform)
    # Siffror per flöde för filterchippen, före flödesfiltret -- annars visar
    # chippen bara det valda flödet.
    flows = [
        {"flow": f["flow"], "count": f["n"]}
        for f in rows.values("flow").annotate(n=Count("id")).order_by("-n")[:20]
    ]
    flow = (request.GET.get("flow") or "").strip().lower()
    if flow:
        rows = rows.filter(flow=flow)
    q = (request.GET.get("q") or "").strip()
    if q:
        rows = rows.filter(
            Q(message__icontains=q) | Q(error_type__icontains=q) | Q(request_id=q)
            | Q(app_version__icontains=q) | Q(device_model__icontains=q) | Q(path__icontains=q)
        )
    total = rows.count()
    rows = list(rows.order_by("-last_at")[:_LIMIT])
    emails, devices, companies = _labels(
        [r.user_id for r in rows], [r.device_id for r in rows], [r.company_id for r in rows],
    )
    out = []
    for r in rows:
        device_row = devices.get(str(r.device_id)) if r.device_id else None
        out.append({
            "id": str(r.id),
            "createdAt": _iso(r.created_at),
            "lastAt": _iso(r.last_at),
            "occurrences": r.occurrences,
            "source": r.source,
            "kind": r.kind,
            "flow": r.flow,
            "errorType": r.error_type,
            "message": r.message,
            "stack": r.stack,
            "fatal": r.fatal,
            "httpStatus": r.http_status,
            "reason": r.reason,
            "requestId": r.request_id,
            "path": r.path,
            "companyId": str(r.company_id) if r.company_id else None,
            "companyName": companies.get(str(r.company_id), "") if r.company_id else "",
            "userId": str(r.user_id) if r.user_id else None,
            "userEmail": emails.get(str(r.user_id), "") if r.user_id else "",
            "deviceId": str(r.device_id) if r.device_id else None,
            "deviceLabel": device_row.label if device_row else "",
            "appVersion": r.app_version,
            "appBuild": r.app_build,
            "platform": r.platform,
            "osVersion": r.os_version,
            "deviceModel": r.device_model,
        })
    return _json(request, {
        "ok": True, "errors": out, "flows": flows, "total": total, "days": days, "limit": _LIMIT,
    })
