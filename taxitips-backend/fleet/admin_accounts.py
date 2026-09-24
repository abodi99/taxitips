"""
Adminwebbens kontohantering: hitta ett konto, spärra eller häva, stäng av ett
företag, hantera ett företags inloggade medlemmar och plattformens personal.

Läsa kräver ADMIN_VIEW (support). Allt som ändrar kräver ADMIN_MANAGE
(platform_admin) -- en spärr stänger en betalande kund ute, och det är inte
en säljares beslut. Varje ändring skrivs i revisionsloggen.

Spärrarnas logik och var de biter: fleet/accounts.py.
"""

from __future__ import annotations

import uuid

from django.db.models import Q
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from billing.models import Company, CompanyMember
from core.api import _json
from fleet import accounts
from fleet.admin_api import _body, _company_or_404, _iso, _record, _staff, handle
from fleet.models import AccountBlock, CompanyProfile, KnownAccount, StaffRole, VerificationStatus
from fleet.roles import Perm

_LIMIT = 100

MEMBER_ROLES = ("company_owner", "company_admin")
MEMBER_STATUSES = ("active", "disabled")


def _account_row(user_id, email: str, last_seen=None) -> dict:
    memberships = [
        {"companyId": str(m.company_id), "role": m.role, "status": m.status}
        for m in CompanyMember.objects.filter(user_id=user_id)
    ]
    names = {
        str(c.id): c.name
        for c in Company.objects.filter(id__in=[m["companyId"] for m in memberships])
    }
    for m in memberships:
        m["companyName"] = names.get(m["companyId"], "")
    staff = StaffRole.objects.filter(user_id=user_id).first()
    block = accounts.account_block(user_id=user_id, email=email)
    return {
        "userId": str(user_id), "email": email, "lastSeenAt": _iso(last_seen),
        "memberships": memberships,
        "staffRole": staff.role if staff and staff.is_active else "",
        "blocked": accounts.block_row(block) if block else None,
    }


@require_GET
@handle
def search(request):
    """
    GET /api/admin/accounts?q= -- konton efter e-post eller företagsnamn.

    Katalogen bygger på inloggningar som servern sett (fleet/accounts.py), så
    ett konto som aldrig anropat servern syns inte här. En spärr på dess
    e-postadress gäller ändra.
    """
    _staff(request, Perm.ADMIN_VIEW)
    q = (request.GET.get("q") or "").strip()
    rows = KnownAccount.objects.all().order_by("-last_seen_at")
    if q:
        company_ids = list(Company.objects.filter(name__icontains=q).values_list("id", flat=True)[:50])
        member_users = CompanyMember.objects.filter(company_id__in=company_ids).values_list(
            "user_id", flat=True
        )
        rows = rows.filter(Q(email__icontains=q.lower()) | Q(user_id__in=list(member_users)))
    rows = list(rows[:_LIMIT])
    return _json(request, {
        "ok": True,
        "accounts": [_account_row(r.user_id, r.email, r.last_seen_at) for r in rows],
    })


@require_GET
@handle
def blocks(request):
    """GET /api/admin/blocks?all=1 -- aktiva spärrar (eller alla, med hävda)."""
    _staff(request, Perm.ADMIN_VIEW)
    rows = AccountBlock.objects.all().order_by("-created_at")
    if request.GET.get("all") != "1":
        rows = rows.filter(lifted_at__isnull=True)
    rows = list(rows[:_LIMIT])
    company_names = {
        str(c.id): c.name
        for c in Company.objects.filter(
            id__in=[r.value for r in rows if r.kind == AccountBlock.Kind.COMPANY]
        )
    }
    user_emails = accounts.emails_for([r.value for r in rows if r.kind == AccountBlock.Kind.USER])
    out = []
    for r in rows:
        row = accounts.block_row(r)
        row["label"] = (
            company_names.get(r.value, r.value) if r.kind == AccountBlock.Kind.COMPANY
            else user_emails.get(r.value, r.value) if r.kind == AccountBlock.Kind.USER
            else r.value
        )
        out.append(row)
    return _json(request, {"ok": True, "blocks": out})


@csrf_exempt
@require_POST
@handle
def create_block(request):
    """POST /api/admin/blocks {"kind": "email"|"user"|"company", "value": "...", "reason": "..."}"""
    principal = _staff(request, Perm.ADMIN_MANAGE)
    body = _body(request)
    kind = str(body.get("kind") or "")
    value = body.get("value")
    company_id = None
    if kind == AccountBlock.Kind.COMPANY:
        company_id = str(_company_or_404(value).id)
    row = accounts.block(
        kind=kind, value=value, reason=str(body.get("reason") or ""),
        actor_user_id=principal.user_id, company_id=company_id,
    )
    return _json(request, {"ok": True, "block": accounts.block_row(row)}, status=201)


@csrf_exempt
@require_POST
@handle
def lift_block(request, block_id):
    """POST /api/admin/blocks/<id>/lift {"note": "..."}"""
    principal = _staff(request, Perm.ADMIN_MANAGE)
    row = accounts.lift(
        block_id, actor_user_id=principal.user_id, note=str(_body(request).get("note") or ""),
    )
    return _json(request, {"ok": True, "block": accounts.block_row(row)})


@csrf_exempt
@require_POST
@handle
def set_member(request, company_id, user_id):
    """
    POST /api/admin/companies/<id>/members/<user_id>
        {"status": "active"|"disabled", "role": "company_owner"|"company_admin"}

    Stänger av eller ändrar en inloggad medlem i ETT företag. Kontot finns kvar
    och kan höra till företaget igen; en spärr (ovan) gäller i stället alla
    företag och registreringar.
    """
    principal = _staff(request, Perm.ADMIN_MANAGE)
    company = _company_or_404(company_id)
    body = _body(request)
    member = CompanyMember.objects.filter(company_id=company.id, user_id=user_id).first()
    if member is None:
        raise accounts.AccountError("unknown_member", "Personen hör inte till företaget.", status=404)
    changes = {}
    status = body.get("status")
    if status is not None:
        if status not in MEMBER_STATUSES:
            raise accounts.AccountError("invalid_status", "Okänd status.")
        if status == "active" and CompanyMember.objects.filter(
            user_id=user_id, status="active"
        ).exclude(company_id=company.id).exists():
            # principal_for läser ETT medlemskap; två aktiva hade gjort det
            # slumpmässigt vilket företag personen ser.
            raise accounts.AccountError(
                "already_member", "Kontot är aktivt i ett annat företag.", status=409
            )
        changes["status"] = status
    role = body.get("role")
    if role is not None:
        if role not in MEMBER_ROLES:
            raise accounts.AccountError("invalid_role", "Okänd roll.")
        changes["role"] = role
    if not changes:
        raise accounts.AccountError("nothing_to_change", "Ange status eller roll.")
    CompanyMember.objects.filter(id=member.id).update(**changes)
    _record(
        principal, "admin_member_changed", company_id=company.id,
        subject_type="member", subject_id=user_id,
        detail={"before": {"status": member.status, "role": member.role}, "after": changes},
    )
    return _json(request, {"ok": True, **changes})


@csrf_exempt
@require_POST
@handle
def verify_company(request, company_id):
    """
    POST /api/admin/companies/<id>/verification {"status": "verified"|"rejected", "note": "..."}

    Självregistrerade företag börjar obekräftade (§7). Anteckningen säger HUR
    behörigheten kontrollerades, samma krav som när en säljare lägger upp
    företaget.
    """
    principal = _staff(request, Perm.ADMIN_SELL)
    company = _company_or_404(company_id)
    body = _body(request)
    status = str(body.get("status") or "")
    if status not in (VerificationStatus.VERIFIED, VerificationStatus.REJECTED):
        raise accounts.AccountError("invalid_status", "Välj verifierad eller avvisad.")
    note = str(body.get("note") or "").strip()[:1000]
    if not note:
        raise accounts.AccountError(
            "note_required", "Skriv hur behörigheten kontrollerades (eller varför den avvisas)."
        )
    updated = CompanyProfile.objects.filter(company_id=company.id).update(
        verification_status=status, verification_note=note,
    )
    if not updated:
        raise accounts.AccountError("profile_missing", "Företaget saknar profil.", status=404)
    _record(
        principal, "admin_company_verification", company_id=company.id,
        subject_type="company", subject_id=company.id, detail={"status": status, "note": note[:300]},
    )
    return _json(request, {"ok": True, "status": status})


# ---------------------------------------------------------------------------
# Plattformens personal
# ---------------------------------------------------------------------------


@require_GET
@handle
def staff(request):
    """GET /api/admin/staff -- vem som har en roll i plattformens personal."""
    _staff(request, Perm.ADMIN_VIEW)
    rows = list(StaffRole.objects.all().order_by("-is_active", "role"))
    emails = accounts.emails_for([r.user_id for r in rows])
    return _json(request, {
        "ok": True,
        "staff": [
            {"id": str(r.id), "userId": str(r.user_id), "email": emails.get(str(r.user_id), ""),
             "role": r.role, "active": r.is_active, "note": r.note, "createdAt": _iso(r.created_at)}
            for r in rows
        ],
        "roles": [{"value": v, "label": label} for v, label in StaffRole.Role.choices],
    })


@csrf_exempt
@require_POST
@handle
def set_staff(request):
    """
    POST /api/admin/staff {"email": "...", "role": "sales"|"support"|"platform_admin"|"", "note": "..."}

    Tom roll = ta bort rollen. Kontot måste ha loggat in minst en gång, så att
    e-postadressen går att knyta till ett verifierat konto-id.
    """
    principal = _staff(request, Perm.ADMIN_MANAGE)
    body = _body(request)
    email = accounts.normalize_email(body.get("email"))
    account = KnownAccount.objects.filter(email=email).order_by("-last_seen_at").first()
    if account is None:
        raise accounts.AccountError(
            "unknown_account",
            "Kontot har inte loggat in än. Be personen logga in i adminwebben en gång först.",
            status=404,
        )
    if str(account.user_id) == str(principal.user_id):
        raise accounts.AccountError("self_change", "Du kan inte ändra din egen roll.")
    role = str(body.get("role") or "")
    if role and role not in StaffRole.Role.values:
        raise accounts.AccountError("invalid_role", "Okänd roll.")
    existing = StaffRole.objects.filter(user_id=account.user_id).first()
    if not role:
        if existing is not None:
            StaffRole.objects.filter(id=existing.id).update(is_active=False)
    elif existing is None:
        StaffRole.objects.create(
            id=uuid.uuid4(), user_id=account.user_id, role=role,
            note=str(body.get("note") or "")[:300],
        )
    else:
        StaffRole.objects.filter(id=existing.id).update(role=role, is_active=True)
    _record(
        principal, "admin_staff_changed", subject_type="staff", subject_id=account.user_id,
        detail={"email": email, "role": role or None,
                "before": existing.role if existing and existing.is_active else None,
                "at": timezone.now().isoformat()},
    )
    return _json(request, {"ok": True, "role": role})
