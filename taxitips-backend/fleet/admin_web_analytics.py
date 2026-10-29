"""
Adminwebben: besöksstatistik för taxitips.se och appen (Firebase/Google Analytics 4).

Läsa räcker med ADMIN_VIEW. Hämtningen, nycklarna och cachen bor i
core/web_analytics.py; här finns bara behörigheten och parametrarna.
"""

from __future__ import annotations

from django.views.decorators.http import require_GET

from core import web_analytics
from core.api import _json
from fleet.admin_api import _staff, handle
from fleet.roles import Perm


@require_GET
@handle
def web_analytics_view(request):
    """
    GET /api/admin/web-analytics?days=1|7|30|90&scope=web|all&fresh=1
    `scope=all` tar med appen (iOS/Android) i GA4. `fresh` hoppar över
    serverns cache på fem minuter.
    """
    _staff(request, Perm.ADMIN_VIEW)
    try:
        days = int(request.GET.get("days", 30))
    except ValueError:
        days = 30
    result = web_analytics.report(
        days, request.GET.get("scope", "web"), fresh=request.GET.get("fresh") == "1",
    )
    response = _json(request, {"ok": True, **result})
    response["Cache-Control"] = "no-store"
    return response
