"""
Företagsrabatter som prismotorn tillämpar på billicenser.

Kuponger (`fleet.models.Coupon`) ger gratisdagar; den här modulen handlar om
lägre månadspris (procent eller fast belopp i ören). Endast en aktiv rabatt per
bolag.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from fleet import audit
from fleet.models import CompanyDiscount

MAX_PERCENT_BP = 10_000  # 100 %
MAX_FIXED_ORE = 10_000_000  # 100 000 kr/mån exkl. moms


class DiscountError(Exception):
    def __init__(self, reason: str, message: str, status: int = 400):
        super().__init__(reason)
        self.reason = reason
        self.message = message
        self.status = status


@dataclass(frozen=True)
class DiscountSpec:
    kind: str
    value: int
    description: str = ""


def active_discount(company_id, *, now=None) -> CompanyDiscount | None:
    now = now or timezone.now()
    row = (
        CompanyDiscount.objects.filter(company_id=company_id, is_active=True)
        .order_by("-created_at")
        .first()
    )
    if row is None:
        return None
    if row.valid_until and row.valid_until <= now:
        return None
    return row


def active_spec(company_id, *, now=None) -> DiscountSpec | None:
    row = active_discount(company_id, now=now)
    if row is None:
        return None
    return DiscountSpec(kind=row.kind, value=row.value, description=row.description or "")


def _validate(kind: str, value: int) -> None:
    if kind == CompanyDiscount.Kind.PERCENT_BP:
        if not 1 <= value <= MAX_PERCENT_BP:
            raise DiscountError("invalid_percent", "Procent: 0,01–100 %.")
    elif kind == CompanyDiscount.Kind.FIXED_ORE:
        if not 1 <= value <= MAX_FIXED_ORE:
            raise DiscountError("invalid_amount", "Belopp: 1 öre–100 000 kr/mån exkl. moms.")
    else:
        raise DiscountError("invalid_kind", "Rabatttyp saknas eller är ogiltig.")


@transaction.atomic
def set_discount(
    company_id,
    *,
    kind: str,
    value: int,
    description: str = "",
    valid_until=None,
    actor_user_id,
) -> CompanyDiscount:
    _validate(kind, int(value))
    CompanyDiscount.objects.filter(company_id=company_id, is_active=True).update(
        is_active=False, deactivated_at=timezone.now()
    )
    row = CompanyDiscount.objects.create(
        company_id=company_id,
        kind=kind,
        value=int(value),
        description=(description or "")[:300],
        valid_until=valid_until,
        created_by=actor_user_id,
    )
    audit.record(
        "company_discount_set",
        company_id=company_id,
        actor_user_id=actor_user_id,
        actor_kind="platform_admin",
        subject_type="company_discount",
        subject_id=row.id,
        detail={"kind": kind, "value": int(value), "validUntil": valid_until.isoformat() if valid_until else None},
    )
    return row


@transaction.atomic
def clear_discount(company_id, *, actor_user_id, reason: str = "") -> bool:
    updated = CompanyDiscount.objects.filter(company_id=company_id, is_active=True).update(
        is_active=False, deactivated_at=timezone.now()
    )
    if updated:
        audit.record(
            "company_discount_cleared",
            company_id=company_id,
            actor_user_id=actor_user_id,
            actor_kind="platform_admin",
            subject_type="company",
            subject_id=company_id,
            detail={"reason": (reason or "")[:300]},
        )
    return bool(updated)


def discount_row(row: CompanyDiscount | None) -> dict | None:
    if row is None:
        return None
    return {
        "id": str(row.id),
        "kind": row.kind,
        "value": row.value,
        "description": row.description,
        "validUntil": row.valid_until.isoformat() if row.valid_until else None,
        "active": row.is_active,
        "createdAt": row.created_at.isoformat(),
    }
