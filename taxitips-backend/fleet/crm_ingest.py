"""
Webleads från taxitips-web/server.mjs — server-side, med delad hemlighet.
"""

from __future__ import annotations

from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.api import _json
from fleet import crm
from fleet.admin_api import _body, handle


def _authorized(request) -> bool:
    secret = getattr(settings, "CRM_LEAD_INGEST_SECRET", "") or ""
    if not secret:
        return False
    header = request.headers.get("X-Crm-Lead-Secret", "")
    return header == secret


@csrf_exempt
@require_POST
@handle
def web_lead(request):
    """POST /api/crm/lead — samma fält som taxitips-web /api/lead."""
    if not _authorized(request):
        return _json(
            request,
            {"ok": False, "reason": "not_configured", "message": "Lead-ingest är av."},
            status=503,
        )
    body = _body(request)
    name = str(body.get("name") or "").strip()
    email = str(body.get("email") or "").strip().lower()
    message = str(body.get("message") or "").strip()
    if not name or not email or len(message) < 10:
        return _json(
            request,
            {"ok": False, "reason": "invalid_fields", "message": "Ogiltiga fält."},
            status=422,
        )
    lead = crm.ingest_web_lead(
        name=name[:200],
        email=email,
        company=str(body.get("company") or "").strip()[:200],
        message=message[:5000],
        source=str(body.get("source") or "taxitips_web")[:100],
        page=str(body.get("page") or "")[:500],
    )
    return _json(request, {"ok": True, "leadId": str(lead.id), "dealId": str(lead.id)})
