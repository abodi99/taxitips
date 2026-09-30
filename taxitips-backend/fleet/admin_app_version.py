"""
Adminwebben: minsta och rekommenderade appversion per plattform.

Läsa räcker med ADMIN_VIEW (supporten behöver kunna svara "din app är för
gammal"). Ändra kräver ADMIN_MANAGE: en för hög minsta version stänger ute
varje förare på plattformen på en gång, så det är samma nivå som att ändra ett
abonnemang för hand -- och samma tvåfaktorskrav när det är påslaget.

Logiken och kontrollerna bor i core/app_version.py; här finns bara
behörigheten och revisionsraden.
"""

from __future__ import annotations

from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from core import app_version
from core.api import _json
from fleet.admin_api import _body, _record, _staff, handle
from fleet.api import _error
from fleet.roles import Perm


@csrf_exempt
@handle
def app_version_view(request):
    """
    GET  /api/admin/app-version -- gällande gränser och varifrån de kommer.
    POST /api/admin/app-version {"android": {"min", "recommended"},
                                 "ios": {"min", "recommended", "storeUrl"},
                                 "message": "..."}
    En nyckel som saknas lämnas orörd; en tom sträng tar bort gränsen.
    """
    if request.method == "GET":
        _staff(request, Perm.ADMIN_VIEW)
        response = _json(request, {"ok": True, **app_version.admin_state()})
        response["Cache-Control"] = "no-store"
        return response
    if request.method != "POST":
        return _json(
            request, {"ok": False, "reason": "method_not_allowed", "message": "GET eller POST."},
            status=405,
        )
    principal = _staff(request, Perm.ADMIN_MANAGE)
    try:
        before, after = app_version.update(_body(request), user_id=principal.user_id)
    except app_version.AppVersionError as exc:
        return _error(request, exc)
    _record(
        principal, "admin_app_version_changed", subject_type="app_version", subject_id="1",
        detail={"before": before, "after": after, "at": timezone.now().isoformat()},
    )
    return _json(request, {"ok": True, **app_version.admin_state()})
