"""
Rapporter om felaktiga tips från förare och personalens hantering.

Föraren skickar via POST /api/tip-reports. Personalen listar och kan antingen
avfärda rapporten (tipset var korrekt) eller undertrycka tipset så att det
försvinner ur flödet utan att pipelinen skriver tillbaka det.
"""

from __future__ import annotations

import uuid

from django.db import transaction
from django.utils import timezone

from core.models import Opportunity, OpportunityReport


class TipReportError(Exception):
    def __init__(self, reason: str, message: str, *, status: int = 400):
        self.reason = reason
        self.message = message
        self.status = status


def suppress_opportunity(
    opportunity: Opportunity,
    *,
    staff_user_id: uuid.UUID,
    note: str = "",
) -> None:
    """
    Tar bort tipset ur förarflödet. Pipelinen får inte skriva över beslutet
    (se core/repository.py).
    """
    now = timezone.now()
    Opportunity.objects.filter(pk=opportunity.pk, suppressed_at__isnull=True).update(
        suppressed_at=now,
        suppressed_by=staff_user_id,
        suppression_note=(note or "")[:2000],
        expired_reason="staff_suppressed",
        end_time=now,
        demand_score=0,
        updated_at=now,
    )


def resolve_report(
    report: OpportunityReport,
    *,
    staff_user_id: uuid.UUID,
    note: str = "",
    suppress_tip: bool = False,
) -> None:
    """Avslutar en rapport; valfritt undertrycker tipset och alla öppna rapporter."""
    now = timezone.now()
    with transaction.atomic():
        if suppress_tip:
            opp = report.opportunity
            if opp is not None:
                suppress_opportunity(opp, staff_user_id=staff_user_id, note=note)
            OpportunityReport.objects.filter(
                opportunity_id=report.opportunity_id,
                status=OpportunityReport.Status.OPEN,
            ).update(
                status=OpportunityReport.Status.RESOLVED,
                resolved_at=now,
                resolved_by=staff_user_id,
                resolution_note=(note or "")[:2000],
            )
        else:
            OpportunityReport.objects.filter(pk=report.pk).update(
                status=OpportunityReport.Status.RESOLVED,
                resolved_at=now,
                resolved_by=staff_user_id,
                resolution_note=(note or "")[:2000],
            )


def report_row(report: OpportunityReport, *, opportunity: Opportunity | None = None) -> dict:
    opp = opportunity if opportunity is not None else report.opportunity
    return {
        "id": str(report.id),
        "status": report.status,
        "reason": report.reason,
        "createdAt": report.created_at.isoformat() if report.created_at else None,
        "deviceToken": report.device_token[:8] + "…" if report.device_token else "",
        "reporterUserId": str(report.reporter_user_id) if report.reporter_user_id else None,
        "resolvedAt": report.resolved_at.isoformat() if report.resolved_at else None,
        "resolutionNote": report.resolution_note or "",
        "opportunity": _opportunity_brief(opp) if opp else None,
    }


def _opportunity_brief(o: Opportunity) -> dict:
    return {
        "id": str(o.id),
        "title": o.title,
        "summary": o.summary,
        "kind": o.kind,
        "mode": o.mode,
        "demandScore": o.demand_score,
        "ruleId": o.rule_id,
        "region": o.region,
        "lat": o.lat,
        "lon": o.lon,
        "startTime": o.start_time.isoformat() if o.start_time else None,
        "endTime": o.end_time.isoformat() if o.end_time else None,
        "suppressedAt": o.suppressed_at.isoformat() if o.suppressed_at else None,
        "expiredReason": o.expired_reason,
    }
