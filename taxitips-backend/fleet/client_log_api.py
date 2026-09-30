"""
POST /api/client-log -- appens felrapporter.

Appen skickar hit (taxitips-app/lib/client_log.dart):

* **krascher** -- `FlutterError.onError` och `PlatformDispatcher.onError`;
* **misslyckade kritiska flöden** -- inloggning, registrering, parkoppling,
  flödet som inte laddar.

    {"kind": "crash"|"flow", "flow": "login", "message": "...", "stack": "...",
     "errorType": "SocketException", "fatal": false, "status": 503,
     "reason": "internal_error", "requestId": "..."}

**Vem får skicka.** En förartelefon (X-Device-Token) eller ett inloggat konto
(Supabase-JWT) -- då hamnar felet på rätt telefon och företag. Utan någon av
dem tas rapporten ändå emot, men med en snävare gräns per nät och utan
koppling till någon: ett fel VID inloggningen kommer per definition från
någon som inte är inloggad, och det är just de felen supporten behöver se.

**Vad som sparas.** Texten tvättas från tokens, e-post, telefonnummer,
personnummer och koordinater (fleet/client_activity.scrub) och kapas.
Kroppen får vara högst 16 KiB. Inga fria fält: bara de ovan. Rensas efter 30
dygn. Se docs/loggning.md.

Svaret är alltid kort och säger ingenting om vad som sparades -- appen ska
inte vänta på det eller visa det.
"""

from __future__ import annotations

import json
import re

from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.api import _json
from fleet import access, accounts, client_activity, ratelimit
from fleet.models import ClientError

MAX_BODY = 16 * 1024

_FLOW = re.compile(r"^[a-z0-9_.:\-]{1,64}$")
_REASON = re.compile(r"^[a-z0-9_]{1,64}$")
_REQUEST_ID = re.compile(r"^[A-Za-z0-9\-]{1,64}$")
_ERROR_TYPE = re.compile(r"[^A-Za-z0-9_<>.,?\s\-]")


def _caller(request):
    """(user_id, device, company_id) ur VERIFIERADE credentials, annars tomt."""
    from core.entitlement import verify_supabase_jwt

    device = None
    token = request.headers.get("X-Device-Token") or ""
    if token:
        device, _credential, _how = access.device_for_token(token)
    user_id = None
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        payload = verify_supabase_jwt(auth[7:].strip())
        if payload:
            accounts.seen(payload)
            user_id = str(payload.get("sub") or "") or None
    company_id = None
    if device is not None:
        company_id = device.company_id
    elif user_id:
        company_id = client_activity._company_for_user(user_id)
    return user_id, device, company_id


@csrf_exempt
@require_POST
def client_log(request):
    try:
        declared = int(request.META.get("CONTENT_LENGTH") or 0)
    except ValueError:
        declared = 0
    if declared > MAX_BODY:
        return _json(request, {"ok": False, "reason": "too_large"}, status=413)
    raw = request.body or b""
    if len(raw) > MAX_BODY:
        return _json(request, {"ok": False, "reason": "too_large"}, status=413)
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        return _json(request, {"ok": False, "reason": "invalid_json"}, status=400)
    if not isinstance(body, dict):
        return _json(request, {"ok": False, "reason": "invalid_json"}, status=400)

    kind = str(body.get("kind") or "")
    if kind not in (ClientError.Kind.CRASH, ClientError.Kind.FLOW):
        return _json(request, {"ok": False, "reason": "invalid_kind"}, status=400)

    user_id, device, company_id = _caller(request)
    if device is not None:
        identity, limit = f"device:{device.id}", ratelimit.CLIENT_LOG
    elif user_id:
        identity, limit = f"user:{user_id}", ratelimit.CLIENT_LOG
    else:
        ip = client_activity.coarse_ip(client_activity._client_ip(request)) or "okänd"
        identity, limit = f"ip:{ip}", ratelimit.CLIENT_LOG_ANON
    try:
        ratelimit.enforce(limit, identity)
        ratelimit.enforce(ratelimit.CLIENT_LOG_ALL, "all")
    except ratelimit.RateLimited:
        return _json(request, {"ok": False, "reason": "rate_limited"}, status=429)

    flow = str(body.get("flow") or "").strip().lower()
    status = body.get("status")
    try:
        status = int(status) if status is not None else None
        if status is not None and not 0 <= status <= 999:
            status = None
    except (TypeError, ValueError):
        status = None
    reason = str(body.get("reason") or "").strip().lower()
    request_id = str(body.get("requestId") or "").strip()

    client_activity.record_client_error(
        request=request,
        kind=kind,
        flow=flow if _FLOW.match(flow) else "unknown",
        message=body.get("message") or "",
        stack=body.get("stack") or "",
        error_type=_ERROR_TYPE.sub("", str(body.get("errorType") or ""))[:80],
        fatal=body.get("fatal") is True,
        http_status=status,
        reason=reason if _REASON.match(reason) else "",
        request_id=request_id if _REQUEST_ID.match(request_id) else "",
        user_id=user_id,
        device_id=device.id if device is not None else None,
        company_id=company_id,
    )
    return _json(request, {"ok": True}, status=202)
