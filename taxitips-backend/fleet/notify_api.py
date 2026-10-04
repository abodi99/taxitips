"""
Kundportalens notisinställningar: företagets administratör ser och ändrar
notiserna för företagets förartelefoner, per telefon, och sätter en standard
som nya telefoner får. Reglerna står i fleet/notify_settings.py.

Läsa kräver VIEW_COMPANY, ändra kräver MANAGE_DEVICES -- samma behörighet som
att koppla och spärra telefoner. En förare (rollen `driver`) har ingen av dem;
hen ändrar sin egen telefon i appen (/api/notify-prefs).
"""

from __future__ import annotations

from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from billing.models import Device
from core.api import _json
from fleet import audit, licensing, notify_settings
from fleet.api import _body, _principal, handle
from fleet.roles import Perm


@require_GET
@handle
def notify_settings_view(request):
    """GET /api/fleet/notify-settings -- standarden, varje telefon och katalogerna."""
    principal = _principal(request, Perm.VIEW_COMPANY)
    if not principal.company_id:
        return _json(request, {"ok": False, "reason": "no_company"}, status=403)
    payload = notify_settings.overview(principal.company_id)
    return _json(request, {
        "ok": True, **payload, "canManage": principal.can(Perm.MANAGE_DEVICES),
    })


@csrf_exempt
@require_POST
@handle
def device_notify_prefs(request, device_id):
    """
    POST /api/fleet/devices/<id>/notify-prefs -- samma fält som förarens
    /api/notify-prefs (`preset`, `categories`, `minLevel`, `weak`,
    `quietHours`, `maxPerHour`, `counties`, `enabled`, `pauseHours` ...).
    En telefon i ett annat företag finns inte (404).
    """
    principal = _principal(request, Perm.MANAGE_DEVICES)
    device = Device.objects.filter(id=device_id, company_id=principal.company_id).first()
    if device is None:
        raise licensing.LicensingError("unknown_device", "Telefonen finns inte.", status=404)
    body = _body(request)
    prefs = notify_settings.update_device(device, body)
    row = notify_settings.phone_row(device)
    audit.record(
        "device_notify_prefs_changed", company_id=principal.company_id,
        actor_user_id=principal.user_id, actor_kind="customer",
        subject_type="device", subject_id=device.id,
        detail=notify_settings.audit_detail(body, prefs, row["entitledCounties"]),
    )
    return _json(request, {"ok": True, "phone": row})


@csrf_exempt
@require_POST
@handle
def notify_default(request):
    """
    POST /api/fleet/notify-default -- företagets standard för nya telefoner.
    `applyToPhones: true` skriver reglerna på alla företagets telefoner också.
    """
    principal = _principal(request, Perm.MANAGE_DEVICES)
    body = _body(request)
    rules, changed = notify_settings.set_company_default(
        principal.company_id, body, actor_user_id=principal.user_id,
        apply_to_phones=body.get("applyToPhones") is True,
    )
    audit.record(
        "company_notify_default_changed", company_id=principal.company_id,
        actor_user_id=principal.user_id, actor_kind="customer",
        subject_type="company", subject_id=principal.company_id,
        detail={**notify_settings.audit_detail(body, rules), "phonesChanged": changed},
    )
    return _json(request, {"ok": True, "default": rules, "phonesChanged": changed})
