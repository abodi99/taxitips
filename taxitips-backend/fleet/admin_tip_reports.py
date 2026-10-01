"""
Tipprapporter från förare -- /api/admin/tip-reports/...

Listas för personal med ADMIN_VIEW. Avsluta eller undertrycka tipset kräver
ADMIN_SUPPORT (samma som supportchatten: rätta fel utan att flytta pengar).
"""

from __future__ import annotations

import uuid

from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.api import _json
from core.models import Opportunity, OpportunityReport
from core import tip_reports
from fleet.admin_api import _body, _iso, _staff, handle
from fleet.roles import Perm

LIST_LIMIT = 200


def _report_or_404(report_id) -> OpportunityReport:
    report = (
        OpportunityReport.objects.select_related("opportunity")
        .filter(id=report_id)
        .first()
    )
    if report is None:
        raise tip_reports.TipReportError("unknown_report", "Rapporten finns inte.", status=404)
    return report


@require_GET
@handle
def summary(request):
    """GET /api/admin/tip-reports/summary -- antal öppna, för menyn."""
    _staff(request, Perm.ADMIN_VIEW)
    open_count = OpportunityReport.objects.filter(status=OpportunityReport.Status.OPEN).count()
    return _json(request, {"ok": True, "open": open_count})


@require_GET
@handle
def list_reports(request):
    """GET /api/admin/tip-reports?status=open|resolved|all"""
    _staff(request, Perm.ADMIN_VIEW)
    status = request.GET.get("status") or "open"
    rows = OpportunityReport.objects.select_related("opportunity").order_by("-created_at")
    if status in OpportunityReport.Status.values:
        rows = rows.filter(status=status)
    found = list(rows[:LIST_LIMIT])
    return _json(
        request,
        {
            "ok": True,
            "reports": [tip_reports.report_row(r) for r in found],
            "open": OpportunityReport.objects.filter(status=OpportunityReport.Status.OPEN).count(),
        },
    )


@require_GET
@handle
def report_detail(request, report_id):
    """GET /api/admin/tip-reports/<id> -- rapport med tipssammanhang."""
    _staff(request, Perm.ADMIN_VIEW)
    report = _report_or_404(report_id)
    opp = report.opportunity
    events = []
    if opp is not None:
        from core.models import SourceEvent

        events = list(
            SourceEvent.objects.filter(id__in=[str(i) for i in (opp.source_event_ids or [])])[:20]
        )
    return _json(
        request,
        {
            "ok": True,
            "report": tip_reports.report_row(report),
            "sourceEvents": [
                {
                    "source": se.source,
                    "externalId": se.external_id,
                    "fetchedAt": _iso(se.fetched_at),
                    "raw": se.raw,
                }
                for se in events
            ],
        },
    )


@csrf_exempt
@require_POST
@handle
def resolve_report(request, report_id):
    """
    POST /api/admin/tip-reports/<id>/resolve
    {"note": "...", "suppressTip": false}
    """
    principal = _staff(request, Perm.ADMIN_SUPPORT)
    report = _report_or_404(report_id)
    if report.status != OpportunityReport.Status.OPEN:
        return _json(request, {"ok": True, "status": report.status, "alreadyResolved": True})
    body = _body(request)
    note = str(body.get("note") or "").strip()
    suppress = bool(body.get("suppressTip"))
    tip_reports.resolve_report(
        report,
        staff_user_id=uuid.UUID(str(principal.user_id)),
        note=note,
        suppress_tip=suppress,
    )
    report.refresh_from_db()
    return _json(request, {"ok": True, "status": report.status, "suppressed": suppress})


@csrf_exempt
@require_POST
@handle
def suppress_opportunity(request, opportunity_id):
    """
    POST /api/admin/opportunities/<uuid>/suppress {"note": "..."}

    Tar bort tipset och avslutar alla öppna rapporter mot det.
    """
    principal = _staff(request, Perm.ADMIN_SUPPORT)
    opp = Opportunity.objects.filter(id=opportunity_id).first()
    if opp is None:
        raise tip_reports.TipReportError("unknown_opportunity", "Tipset finns inte.", status=404)
    body = _body(request)
    note = str(body.get("note") or "").strip()
    from django.utils import timezone

    now = timezone.now()
    tip_reports.suppress_opportunity(
        opp, staff_user_id=uuid.UUID(str(principal.user_id)), note=note
    )
    OpportunityReport.objects.filter(
        opportunity_id=opp.id,
        status=OpportunityReport.Status.OPEN,
    ).update(
        status=OpportunityReport.Status.RESOLVED,
        resolved_at=now,
        resolved_by=principal.user_id,
        resolution_note=note[:2000],
    )
    return _json(request, {"ok": True, "suppressed": True})
