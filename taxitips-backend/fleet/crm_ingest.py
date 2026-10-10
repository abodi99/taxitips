"""
Webbformulären på taxitips.se.

Både nyhetsbrevet och genomgången landar i CRM och i Hostinger Reach.
Anropet kommer från sidan själv, inte från en mellanliggande webbserver.
"""

from __future__ import annotations

import logging
import re

from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.api import _json
from fleet import crm, ratelimit, reach
from fleet.admin_api import _body, handle

log = logging.getLogger(__name__)

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _client_ip(request) -> str:
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.META.get("REMOTE_ADDR") or "")[:64]


def _form_cors(response, request):
    """Marknadssidan får anropa just det här formuläret."""
    origin = request.headers.get("Origin", "")
    allowed = [o for o in getattr(settings, "WEB_FORM_ORIGINS", []) if o]
    if origin and origin in allowed:
        response["Access-Control-Allow-Origin"] = origin
        response["Vary"] = "Origin"
        response["Access-Control-Allow-Headers"] = "Content-Type, Accept"
        response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    return response


@csrf_exempt
@require_POST
@handle
def web_lead(request):
    """POST /api/crm/lead — nyhetsbrev eller genomgång."""
    ip = _client_ip(request) or "unknown"
    try:
        ratelimit.enforce(ratelimit.WEB_LEAD, ip)
        ratelimit.enforce(ratelimit.WEB_LEAD_ALL, "all")
    except ratelimit.RateLimited:
        return _form_cors(
            _json(request, {"ok": False, "reason": "rate_limited", "message": "För många försök. Vänta en stund."}, status=429),
            request,
        )

    body = _body(request)
    kind = str(body.get("kind") or "contact").strip()
    if kind not in ("contact", "newsletter"):
        kind = "contact"
    email = str(body.get("email") or "").strip().lower()
    name = str(body.get("name") or "").strip()[:200]
    company = str(body.get("company") or "").strip()[:200]
    message = str(body.get("message") or "").strip()[:5000]
    page = str(body.get("page") or "")[:500]

    if not _EMAIL.match(email) or len(email) > 254:
        return _form_cors(
            _json(request, {"ok": False, "reason": "invalid_email", "message": "Ogiltig e-post."}, status=422),
            request,
        )

    if kind == "newsletter":
        name = name or "Nyhetsbrev"
        message = message or "Vill ha nyhetsbrevet från taxitips.se."
        source = "taxitips_web_newsletter"
        tag = settings.REACH_TAG_NEWSLETTER
        note = "Nyhetsbrev från taxitips.se"
    else:
        if not name or len(message) < 10:
            return _form_cors(
                _json(request, {"ok": False, "reason": "invalid_fields", "message": "Ogiltiga fält."}, status=422),
                request,
            )
        source = str(body.get("source") or "taxitips_web_contact")[:100]
        tag = settings.REACH_TAG_CONTACT
        note = "\n".join(
            part for part in (
                f"Bolag: {company}" if company else "",
                message,
                f"Sida: {page}" if page else "",
            ) if part
        )[:2000]

    lead = crm.ingest_web_lead(
        name=name,
        email=email,
        company=company,
        message=message,
        source=source,
        page=page,
    )
    try:
        reach_result = reach.save_contact(email=email, name=name, note=note, tag=tag)
    except Exception:
        log.exception("reach: kunde inte spara %s", email)
        reach_result = {"ok": False, "reason": "reach_failed"}

    return _form_cors(
        _json(request, {
            "ok": True,
            "leadId": str(lead.id),
            "dealId": str(lead.id),
            "reach": reach_result,
        }),
        request,
    )
