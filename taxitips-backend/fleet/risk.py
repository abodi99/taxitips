"""
Riskkontroller: när en ändring ska granskas innan den får göras i självservice.

**Vad de gör och inte gör.** De blockerar NÄSTA ändring, aldrig den åtkomst som
redan gäller. En enstaka risksignal får inte stänga av ett betalande företag
(§4) -- förarna fortsätter se tips medan ärendet granskas, och kunden ser en
begriplig status i stället för en tom lista.

Undantaget är konkret kontokapning, som inte är en räknad signal utan ett
beslut någon fattar: då spärras enheterna med `fleet.pairing.block_device`,
vilket är en annan väg med en annan revisionsrad.

Gränserna är konfigurerbara (`RiskConfig`). Startvärdena är de som står i
uppdraget: tre nya telefonanslutningar per bil på 24 timmar, sex övertaganden
på en timme, två separata bilbyten på 30 dagar.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from fleet.models import ChangeReview, License, RiskConfig, RiskSignal, Vehicle


class ReviewRequired(Exception):
    """Ändringen kräver granskning. Åtkomsten som gäller nu är oförändrad."""

    def __init__(self, review: ChangeReview):
        super().__init__(review.kind)
        self.review = review
        self.reason = "review_required"
        self.message = review.customer_message
        self.status = 409
        self.detail = {"reviewId": str(review.id), "reviewStatus": review.status}


@dataclass(frozen=True)
class Pressure:
    kind: str
    count: int
    limit: int

    @property
    def exceeded(self) -> bool:
        return self.count >= self.limit

    def as_dict(self) -> dict:
        return {"kind": self.kind, "count": self.count, "limit": self.limit,
                "exceeded": self.exceeded}


def pairing_pressure(vehicle: Vehicle, *, now=None) -> Pressure:
    now = now or timezone.now()
    config = RiskConfig.current()
    count = RiskSignal.objects.filter(
        vehicle=vehicle, kind=RiskSignal.Kind.PAIRING,
        created_at__gte=now - timedelta(hours=24),
    ).count()
    return Pressure("pairing_rate", count, config.new_pairings_per_vehicle_24h)


def takeover_pressure(license: License, *, now=None) -> Pressure:
    now = now or timezone.now()
    config = RiskConfig.current()
    count = RiskSignal.objects.filter(
        license=license, kind=RiskSignal.Kind.TAKEOVER,
        created_at__gte=now - timedelta(hours=1),
    ).count()
    # "fler än sex" -- alltså är sjunde övertagandet det som slår i taket.
    return Pressure("takeover_rate", count, config.takeovers_per_hour + 1)


def open_review(company_id, kind: str) -> ChangeReview | None:
    return ChangeReview.objects.filter(
        company_id=company_id, kind=kind, status=ChangeReview.Status.OPEN
    ).first()


def guard_pairing(vehicle: Vehicle, *, now=None) -> None:
    """
    Minst tre nya telefonanslutningar för samma bil på 24 timmar kräver extra
    administratörsverifiering för nästa ändring.
    """
    now = now or timezone.now()
    existing = open_review(vehicle.company_id, ChangeReview.Kind.PAIRING_RATE)
    if existing is not None:
        raise ReviewRequired(existing)

    pressure = pairing_pressure(vehicle, now=now)
    if not pressure.exceeded:
        return
    review = ChangeReview.objects.create(
        company_id=vehicle.company_id, vehicle=vehicle,
        kind=ChangeReview.Kind.PAIRING_RATE,
        customer_message=(
            f"{vehicle.plate} har fått {pressure.count} nya telefonanslutningar på ett dygn. "
            "Nästa anslutning behöver bekräftas av en behörig administratör. "
            "Förarna som kör nu påverkas inte."
        ),
        detail=pressure.as_dict(),
    )
    raise ReviewRequired(review)


def guard_takeover(license: License, *, now=None) -> None:
    """Fler än sex övertaganden under en timme kräver extra verifiering."""
    now = now or timezone.now()
    existing = open_review(license.company_id, ChangeReview.Kind.TAKEOVER_RATE)
    if existing is not None:
        raise ReviewRequired(existing)

    pressure = takeover_pressure(license, now=now)
    if not pressure.exceeded:
        return
    review = ChangeReview.objects.create(
        company_id=license.company_id, license=license,
        kind=ChangeReview.Kind.TAKEOVER_RATE,
        customer_message=(
            f"Licensen har bytt telefon {pressure.count} gånger den senaste timmen. "
            "Nästa byte behöver bekräftas av en behörig administratör. "
            "Föraren som kör nu påverkas inte."
        ),
        detail=pressure.as_dict(),
    )
    raise ReviewRequired(review)


def resolve_review(
    review: ChangeReview, *, approved: bool, resolved_by, note: str = "", now=None
) -> ChangeReview:
    from fleet import audit

    now = now or timezone.now()
    ChangeReview.objects.filter(id=review.id, status=ChangeReview.Status.OPEN).update(
        status=ChangeReview.Status.APPROVED if approved else ChangeReview.Status.REJECTED,
        resolved_at=now, resolved_by=resolved_by, resolution_note=note[:500],
    )
    review.refresh_from_db()
    audit.record(
        "review_resolved", company_id=review.company_id, actor_user_id=resolved_by,
        actor_kind="admin", subject_type="review", subject_id=review.id,
        detail={"kind": review.kind, "approved": approved, "note": note[:500]},
    )
    return review


def customer_status(company_id) -> list[dict]:
    """Begriplig status för kunden -- inte en intern kod (§4)."""
    return [
        {
            "id": str(r.id),
            "kind": r.kind,
            "status": r.status,
            "message": r.customer_message,
            "createdAt": r.created_at.isoformat(),
            "resolvedAt": r.resolved_at.isoformat() if r.resolved_at else None,
        }
        for r in ChangeReview.objects.filter(company_id=company_id).order_by("-created_at")[:20]
    ]
