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

from billing.models import Company, CompanyMember, Device
from core.api import _json
from core.models import OpportunityFeedback, OpportunityFavorite, OpportunityReport, PushDelivery
from fleet import accounts
from fleet.admin_api import _body, _company_or_404, _iso, _record, _staff, handle
from fleet.models import (
    AccountBlock, AuditEvent, ClientActivity, ClientError, CompanyProfile,
    DriverInvite, KnownAccount, StaffRole, VerificationStatus,
)
from fleet.roles import Perm
_LIMIT = 100
_LOG_LIMIT = 40

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
    from fleet.admin_activity import activity_for_user

    return {
        "userId": str(user_id), "email": email, "lastSeenAt": _iso(last_seen),
        # Senaste inloggning, appversion och telefon (fleet/client_activity.py).
        "client": activity_for_user(user_id),
        "memberships": memberships,
        "staffRole": staff.role if staff and staff.is_active else "",
        "blocked": accounts.block_row(block) if block else None,
    }


def _device_ids_for_user(user_id) -> list:
    """
    Telefoner knutna till kontot: devices.user_id (ägare/admin-appen) och
    telefoner som löst in förarinbjudan med samma konto.
    """
    ids = {str(d) for d in Device.objects.filter(user_id=user_id).values_list("id", flat=True)}
    invite_ids = DriverInvite.objects.filter(
        Q(consumed_by_user=user_id) | Q(auth_user_id=user_id),
        consumed_by_device__isnull=False,
    ).values_list("consumed_by_device", flat=True)
    ids.update(str(d) for d in invite_ids if d)
    return list(ids)


def _prefs_summary(prefs) -> dict:
    prefs = prefs if isinstance(prefs, dict) else {}
    categories = prefs.get("categories") if isinstance(prefs.get("categories"), dict) else {}
    return {
        "counties": list(prefs.get("counties") or prefs.get("regions") or []),
        "categoriesOff": [k for k, v in categories.items() if v is False],
        "minLevel": str(prefs.get("minLevel") or prefs.get("level") or "all"),
        "pausedUntil": prefs.get("pausedUntil") or None,
        "notificationsOff": (
            prefs.get("notifications") is False
            or prefs.get("enabled") is False
            or prefs.get("notificationsEnabled") is False
        ),
    }


def _device_rows(user_id) -> list[dict]:
    from fleet.admin_activity import activity_row

    device_ids = _device_ids_for_user(user_id)
    if not device_ids:
        return []
    devices = list(Device.objects.filter(id__in=device_ids).order_by("-last_seen_at")[:50])
    names = {
        str(c.id): c.name
        for c in Company.objects.filter(id__in=[d.company_id for d in devices])
    }
    activities = {
        str(a.subject_id): a
        for a in ClientActivity.objects.filter(
            subject_kind="device", subject_id__in=[d.id for d in devices],
        )
    }
    out = []
    for d in devices:
        act = activity_row(activities.get(str(d.id)))
        out.append({
            "id": str(d.id),
            "label": d.label or "",
            "kind": d.kind or "",
            "hasPush": bool((d.push_token or "").strip()),
            "lastSeenAt": _iso(d.last_seen_at),
            "createdAt": _iso(d.created_at),
            "companyId": str(d.company_id),
            "companyName": names.get(str(d.company_id), ""),
            "linkedToAccount": bool(d.user_id) and str(d.user_id) == str(user_id),
            "platform": (act or {}).get("platform") if act else "",
            "deviceModel": (act or {}).get("deviceModel") if act else "",
            "osVersion": (act or {}).get("osVersion") if act else "",
            "appVersion": (act or {}).get("appVersion") if act else "",
            "prefs": _prefs_summary(d.notify_prefs),
            "client": act,
        })
    return out


def _device_tokens_for_user(user_id) -> list[str]:
    device_ids = _device_ids_for_user(user_id)
    if not device_ids:
        return []
    return [
        t for t in Device.objects.filter(id__in=device_ids).values_list("token", flat=True)
        if t
    ]


_FEEDBACK_LABEL = {
    OpportunityFeedback.Verdict.FARE: "Fick körning",
    OpportunityFeedback.Verdict.EMPTY: "Ingen kund",
    OpportunityFeedback.Verdict.HEADING: "Kör dit",
}


def _feedback_rows(tokens: list[str]) -> list[dict]:
    """🚕/👍/👎 — knutet till telefonens installations-token, inte Auth-id."""
    if not tokens:
        return []
    rows = list(
        OpportunityFeedback.objects.filter(device_token__in=tokens)
        .select_related("opportunity")
        .order_by("-created_at")[:_LOG_LIMIT]
    )
    out = []
    for r in rows:
        o = r.opportunity
        out.append({
            "id": str(r.id),
            "verdict": r.verdict,
            "verdictLabel": _FEEDBACK_LABEL.get(r.verdict, r.verdict),
            "createdAt": _iso(r.created_at),
            "opportunityId": str(r.opportunity_id),
            "title": (o.title if o else "") or "",
            "kind": (o.kind if o else "") or "",
            "region": (o.region if o else "") or "",
            "demandScore": o.demand_score if o else None,
        })
    return out


def _tip_report_rows(user_id, tokens: list[str]) -> list[dict]:
    """Felaktigt tips — via inloggat konto eller samma telefoner."""
    q = Q(reporter_user_id=user_id)
    if tokens:
        q |= Q(device_token__in=tokens)
    rows = list(
        OpportunityReport.objects.filter(q)
        .select_related("opportunity")
        .order_by("-created_at")[:_LOG_LIMIT]
    )
    out = []
    for r in rows:
        o = r.opportunity
        out.append({
            "id": str(r.id),
            "status": r.status,
            "reason": r.reason or "",
            "createdAt": _iso(r.created_at),
            "resolvedAt": _iso(r.resolved_at),
            "resolutionNote": r.resolution_note or "",
            "opportunityId": str(r.opportunity_id),
            "title": (o.title if o else "") or "",
            "kind": (o.kind if o else "") or "",
            "region": (o.region if o else "") or "",
        })
    return out


def _notification_rows(device_ids) -> list[dict]:
    if not device_ids:
        return []
    rows = list(
        PushDelivery.objects.filter(device_id__in=device_ids).order_by("-created_at")[:_LOG_LIMIT]
    )
    labels = {
        str(d.id): d.label
        for d in Device.objects.filter(id__in=[r.device_id for r in rows])
    }
    return [
        {
            "id": str(r.id),
            "title": r.title,
            "body": r.body,
            "status": r.status,
            "error": r.error,
            "attempts": r.attempts,
            "deviceId": str(r.device_id),
            "device": labels.get(str(r.device_id), ""),
            "createdAt": _iso(r.created_at),
            "sentAt": _iso(r.sent_at),
        }
        for r in rows
    ]


def _owner_keys_for_user(user_id, device_ids=None) -> list[str]:
    """
    Favoriternas nycklar för kontot: user:<uuid> (inloggad ägare) och
    device:<uuid> per knuten telefon. Aldrig rå token.
    """
    keys = [f"user:{user_id}"]
    for did in (device_ids if device_ids is not None else _device_ids_for_user(user_id)):
        keys.append(f"device:{did}")
    return keys


def _favorite_rows(user_id, device_ids=None) -> list[dict]:
    """Sparade tips (OpportunityFavorite) knutna till kontots telefoner/JWT."""
    keys = _owner_keys_for_user(user_id, device_ids)
    rows = list(
        OpportunityFavorite.objects.filter(owner_key__in=keys)
        .select_related("opportunity")
        .order_by("-created_at")[:_LOG_LIMIT]
    )
    out = []
    for r in rows:
        o = r.opportunity
        snap = r.snapshot if isinstance(r.snapshot, dict) else {}
        title = (o.title if o else "") or snap.get("title") or ""
        kind = (o.kind if o else "") or snap.get("kind") or ""
        region = (o.region if o else "") or snap.get("region") or ""
        score = o.demand_score if o else snap.get("demand_score")
        # owner_key är device:<uuid> eller user:<uuid> — visa typ, aldrig hemlighet.
        owner = r.owner_key or ""
        if owner.startswith("device:"):
            owner_label = f"Telefon {owner[7:15]}"
        elif owner.startswith("user:"):
            owner_label = "Inloggat konto"
        else:
            owner_label = "Okänd"
        out.append({
            "id": str(r.id),
            "createdAt": _iso(r.created_at),
            "opportunityId": str(r.opportunity_id) if r.opportunity_id else None,
            "externalId": r.opportunity_external_id or "",
            "title": title,
            "kind": kind,
            "region": region,
            "demandScore": score,
            "purged": o is None,
            "ownerKind": "device" if owner.startswith("device:") else (
                "user" if owner.startswith("user:") else "other"
            ),
            "ownerLabel": owner_label,
            "note": r.note or "",
        })
    return out


def _error_rows(user_id, device_ids=None) -> list[dict]:
    q = Q(user_id=user_id)
    if device_ids:
        q |= Q(device_id__in=device_ids)
    rows = list(ClientError.objects.filter(q).order_by("-last_at")[:_LOG_LIMIT])
    return [
        {
            "id": str(r.id),
            "lastAt": _iso(r.last_at),
            "occurrences": r.occurrences,
            "source": r.source,
            "kind": r.kind,
            "flow": r.flow,
            "errorType": r.error_type,
            "message": r.message,
            "fatal": r.fatal,
            "httpStatus": r.http_status,
            "reason": r.reason,
            "path": r.path,
            "appVersion": r.app_version,
            "platform": r.platform,
            "deviceModel": r.device_model,
            "deviceId": str(r.device_id) if r.device_id else None,
        }
        for r in rows
    ]


def _audit_rows(user_id) -> list[dict]:
    uid = str(user_id)
    rows = list(
        AuditEvent.objects.filter(
            Q(actor_user_id=user_id)
            | Q(subject_type="account", subject_id=uid)
            | Q(subject_type="member", subject_id=uid)
            | Q(subject_type="staff", subject_id=uid)
        ).order_by("-created_at")[:_LOG_LIMIT]
    )
    return [
        {
            "id": str(r.id),
            "at": _iso(r.created_at),
            "action": r.action,
            "actorKind": r.actor_kind,
            "subjectType": r.subject_type,
            "subjectId": r.subject_id,
            "companyId": str(r.company_id) if r.company_id else None,
            "detail": r.detail or {},
        }
        for r in rows
    ]


def _sole_owner_companies(user_id) -> list[dict]:
    """Företag där kontot är enda aktiva ägaren — får inte raderas då."""
    owned = CompanyMember.objects.filter(
        user_id=user_id, role="company_owner", status="active",
    )
    blocked = []
    for m in owned:
        others = CompanyMember.objects.filter(
            company_id=m.company_id, role="company_owner", status="active",
        ).exclude(user_id=user_id).exists()
        if others:
            continue
        company = Company.objects.filter(id=m.company_id).first()
        blocked.append({
            "companyId": str(m.company_id),
            "companyName": company.name if company else str(m.company_id),
        })
    return blocked


@require_GET
@handle
def search(request):
    """
    GET /api/admin/accounts?q= -- konton efter e-post eller företagsnamn.

    Katalogen bygger på inloggningar som servern sett (fleet/accounts.py), så
    ett konto som aldrig anropat servern syns inte här. En spärr på dess
    e-postadress gäller ändra. Utan q: de senast sedda (för användarlistan).
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
def detail(request, user_id):
    """
    GET /api/admin/accounts/<user_id> -- ett konto med medlemskap, telefoner
    (Firebase-push), notishistorik, app-/serverfel och revision.
    """
    _staff(request, Perm.ADMIN_VIEW)
    known = KnownAccount.objects.filter(user_id=user_id).order_by("-last_seen_at").first()
    if known is None:
        # Spärrat konto utan known-rad, eller medlemskap som aldrig anropat.
        emails = accounts.emails_for([user_id])
        email = emails.get(str(user_id), "")
        if not email and not CompanyMember.objects.filter(user_id=user_id).exists():
            raise accounts.AccountError("unknown_account", "Kontot finns inte i katalogen.", status=404)
        account = _account_row(user_id, email)
    else:
        account = _account_row(known.user_id, known.email, known.last_seen_at)
    devices = _device_rows(user_id)
    device_ids = [d["id"] for d in devices]
    tokens = _device_tokens_for_user(user_id)
    feedback = _feedback_rows(tokens)
    tip_reports = _tip_report_rows(user_id, tokens)
    favorites = _favorite_rows(user_id, device_ids)
    from fleet import device_swaps

    return _json(request, {
        "ok": True,
        "account": account,
        "devices": devices,
        "deviceSwaps": device_swaps.summary_for(user_id),
        "notifications": _notification_rows(device_ids),
        "favorites": favorites,
        "feedback": feedback,
        "tipReports": tip_reports,
        "feedbackSummary": {
            "fare": sum(1 for f in feedback if f["verdict"] == OpportunityFeedback.Verdict.FARE),
            "empty": sum(1 for f in feedback if f["verdict"] == OpportunityFeedback.Verdict.EMPTY),
            "heading": sum(1 for f in feedback if f["verdict"] == OpportunityFeedback.Verdict.HEADING),
            "reportsOpen": sum(1 for r in tip_reports if r["status"] == OpportunityReport.Status.OPEN),
            "reportsTotal": len(tip_reports),
            "favorites": len(favorites),
        },
        "errors": _error_rows(user_id, device_ids),
        "audit": _audit_rows(user_id),
    })


@csrf_exempt
@require_POST
@handle
def recovery_link(request, user_id):
    """
    POST /api/admin/accounts/<user_id>/recovery {"redirectTo": "…"}

    Engångslänk där personen sätter nytt lösenord (Supabase Auth recovery).
    Länken returneras till adminwebben -- mejlas inte automatiskt -- så att
    personalen kan skicka den i chatten eller kopiera den. Kräver
    SUPABASE_SERVICE_ROLE_KEY (samma som förarinbjudan).
    """
    from fleet import auth_admin

    principal = _staff(request, Perm.ADMIN_MANAGE)
    known = KnownAccount.objects.filter(user_id=user_id).order_by("-last_seen_at").first()
    email = (known.email if known else "") or accounts.emails_for([user_id]).get(str(user_id), "")
    if not email:
        raise accounts.AccountError(
            "unknown_email", "Kontot saknar e-postadress i katalogen.", status=404,
        )
    body = _body(request)
    redirect_to = str(body.get("redirectTo") or "https://taxitips.se/portal").strip()
    if not auth_admin.configured():
        raise accounts.AccountError(
            "auth_not_configured",
            "SUPABASE_SERVICE_ROLE_KEY saknas på servern — kan inte skapa lösenordslänk.",
            status=503,
        )
    try:
        link = auth_admin.invite_link(email, redirect_to)
    except auth_admin.AuthAdminError as exc:
        raise accounts.AccountError("link_failed", "Kunde inte skapa länken.", status=502) from exc
    _record(
        principal, "admin_account_recovery_link",
        subject_type="account", subject_id=user_id,
        detail={"email": email, "kind": link.kind},
    )
    return _json(request, {
        "ok": True, "email": email, "kind": link.kind, "url": link.url,
    })


@csrf_exempt
@require_POST
@handle
def allow_device_swap(request, user_id):
    """
    POST /api/admin/accounts/<user_id>/allow-device-swap {"note": "…"}

    Ger kontot ett extra telefonbyte den här kalendermånaden (Europe/Stockholm).
    Användaren byter sedan själv i appen; personalen tvingar inte länken.
    """
    from fleet import device_swaps

    principal = _staff(request, Perm.ADMIN_MANAGE)
    body = _body(request)
    note = str(body.get("note") or "").strip()[:300]
    result = device_swaps.grant_extra_swap(
        user_id=user_id, actor_user_id=principal.user_id, note=note,
    )
    _record(
        principal, "admin_device_swap_grant",
        subject_type="account", subject_id=user_id,
        detail={"month": result["month"], "remaining": result["remaining"], "note": note},
    )
    return _json(request, {"ok": True, "deviceSwaps": device_swaps.summary_for(user_id), **result})


@csrf_exempt
@require_POST
@handle
def test_push(request, user_id):
    """
    POST /api/admin/accounts/<user_id>/test-push

    Skickar en testnotis till kontots telefoner som har Firebase-token,
    genom samma mottagargrind som riktiga notiser.
    """
    from django.conf import settings

    from billing import fcm
    from fleet.push_gate import can_receive

    principal = _staff(request, Perm.ADMIN_MANAGE)
    device_ids = _device_ids_for_user(user_id)
    if not device_ids:
        raise accounts.AccountError(
            "no_devices", "Kontot har ingen telefon kopplad.", status=404,
        )
    service_account = fcm.load_service_account(settings.FIREBASE_SERVICE_ACCOUNT_JSON)
    if not service_account:
        raise accounts.AccountError(
            "no_fcm", "Servern saknar FIREBASE_SERVICE_ACCOUNT_JSON — kan inte skicka push.",
            status=503,
        )
    access_token = fcm.get_access_token(service_account)
    results = []
    for device in Device.objects.filter(id__in=device_ids):
        label = device.label or str(device.id)[:8]
        if not (device.push_token or "").strip():
            results.append({"device": label, "sent": False, "reason": "no_push_token"})
            continue
        verdict = can_receive(device, {})
        if not verdict.ok:
            results.append({"device": label, "sent": False, "reason": verdict.reason})
            continue
        res = fcm.send_push(
            service_account, access_token, token=device.push_token,
            title="TaxiTips", body="Testnotis från support.", data={"kind": "test"},
        )
        results.append({
            "device": label,
            "sent": bool(res.get("ok")),
            "reason": "" if res.get("ok") else str(res.get("status") or res.get("error") or ""),
        })
    _record(
        principal, "admin_account_test_push",
        subject_type="account", subject_id=user_id,
        detail={"sent": sum(1 for r in results if r["sent"]), "tried": len(results)},
    )
    return _json(request, {"ok": True, "results": results})


@csrf_exempt
@require_POST
@handle
def delete_account(request, user_id):
    """
    POST /api/admin/accounts/<user_id>/delete {"confirmEmail": "…"}

    Tar bort inloggningen (Supabase Auth), katalogen och medlemskapen.
    Vägrar om kontot är enda aktiva ägaren i något företag — överlåt eller
    arkivera företaget först. Supporttrådar och felrader behålls (utan inloggning).
    """
    from django.db import transaction

    from fleet import auth_admin

    principal = _staff(request, Perm.ADMIN_MANAGE)
    if str(user_id) == str(principal.user_id):
        raise accounts.AccountError("self_delete", "Du kan inte radera ditt eget konto.")

    known = KnownAccount.objects.filter(user_id=user_id).first()
    email = (known.email if known else "") or accounts.emails_for([user_id]).get(str(user_id), "")
    if not email and not CompanyMember.objects.filter(user_id=user_id).exists():
        raise accounts.AccountError("unknown_account", "Kontot finns inte i katalogen.", status=404)

    body = _body(request)
    confirm = accounts.normalize_email(body.get("confirmEmail"))
    if not confirm or confirm != accounts.normalize_email(email):
        raise accounts.AccountError(
            "confirm_mismatch",
            "Skriv kontots e-postadress för att bekräfta raderingen.",
        )

    sole = _sole_owner_companies(user_id)
    if sole:
        names = ", ".join(s["companyName"] for s in sole)
        raise accounts.AccountError(
            "sole_owner",
            f"Kontot är enda ägaren i: {names}. Överlåt ägarskapet eller arkivera företaget först.",
            status=409,
        )

    if not auth_admin.configured():
        raise accounts.AccountError(
            "auth_not_configured",
            "SUPABASE_SERVICE_ROLE_KEY saknas på servern — kan inte radera Auth-kontot.",
            status=503,
        )

    membership_count = CompanyMember.objects.filter(user_id=user_id).count()
    with transaction.atomic():
        CompanyMember.objects.filter(user_id=user_id).delete()
        StaffRole.objects.filter(user_id=user_id).update(is_active=False)
        KnownAccount.objects.filter(user_id=user_id).delete()
        ClientActivity.objects.filter(subject_kind="user", subject_id=user_id).delete()
        # Aktiva användarspärrar lyfts — Auth-kontot försvinner.
        AccountBlock.objects.filter(
            kind=AccountBlock.Kind.USER, value=str(user_id), lifted_at__isnull=True,
        ).update(lifted_at=timezone.now(), lifted_by=principal.user_id, lift_note="Konto raderat")
        _record(
            principal, "admin_account_deleted",
            subject_type="account", subject_id=user_id,
            detail={"email": email, "membershipsRemoved": membership_count},
        )

    try:
        auth_admin.delete_user(str(user_id))
    except auth_admin.AuthAdminError as exc:
        # Katalogen är redan borta; Auth kvar är allvarligt — rapportera.
        raise accounts.AccountError(
            "auth_delete_failed",
            "Kontot togs bort lokalt men Auth-raderingen misslyckades. Försök igen eller radera manuellt i Supabase.",
            status=502,
        ) from exc

    return _json(request, {"ok": True, "email": email})


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
