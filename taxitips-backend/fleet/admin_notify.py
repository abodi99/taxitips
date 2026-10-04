"""
Adminwebbens notisinställningar för en kund: samma vy och samma regler som
kundens administratör har i portalen (fleet/notify_api.py, notify_settings.py),
för personal som hjälper en kund som ringer.

Läsa kräver ADMIN_VIEW, ändra ADMIN_SELL. Varje ändring loggas med `_record`
(actor_kind platform_admin), så att den går att skilja från något kunden själv
gjort.
"""

from __future__ import annotations

from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from billing.models import Device
from core.api import _json
from fleet import licensing, notify_settings
from fleet.admin_api import _body, _company_or_404, _record, _staff, handle
from fleet.roles import Perm


@require_GET
@handle
def company_notify_settings(request, company_id):
    """GET /api/admin/companies/<id>/notify-settings"""
    principal = _staff(request, Perm.ADMIN_VIEW)
    company = _company_or_404(company_id)
    return _json(request, {
        "ok": True, **notify_settings.overview(company.id),
        "canManage": principal.can(Perm.ADMIN_SELL),
    })


@csrf_exempt
@require_POST
@handle
def device_notify_prefs(request, company_id, device_id):
    """POST /api/admin/companies/<id>/devices/<device_id>/notify-prefs"""
    principal = _staff(request, Perm.ADMIN_SELL)
    company = _company_or_404(company_id)
    device = Device.objects.filter(id=device_id, company_id=company.id).first()
    if device is None:
        raise licensing.LicensingError("unknown_device", "Telefonen finns inte.", status=404)
    body = _body(request)
    prefs = notify_settings.update_device(device, body)
    row = notify_settings.phone_row(device)
    _record(
        principal, "admin_device_notify_prefs_changed", company_id=company.id,
        subject_type="device", subject_id=device.id,
        detail=notify_settings.audit_detail(body, prefs, row["entitledCounties"]),
    )
    return _json(request, {"ok": True, "phone": row})


@csrf_exempt
@require_POST
@handle
def company_notify_default(request, company_id):
    """POST /api/admin/companies/<id>/notify-default {..., "applyToPhones": bool}"""
    principal = _staff(request, Perm.ADMIN_SELL)
    company = _company_or_404(company_id)
    body = _body(request)
    rules, changed = notify_settings.set_company_default(
        company.id, body, actor_user_id=principal.user_id,
        apply_to_phones=body.get("applyToPhones") is True,
    )
    _record(
        principal, "admin_company_notify_default_changed", company_id=company.id,
        subject_type="company", subject_id=company.id,
        detail={**notify_settings.audit_detail(body, rules), "phonesChanged": changed},
    )
    return _json(request, {"ok": True, "default": rules, "phonesChanged": changed})
