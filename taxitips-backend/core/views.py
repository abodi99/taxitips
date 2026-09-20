from django.conf import settings
from django.db import connection
from django.http import JsonResponse


def health(request):
    """
    Hälsokontroll för Coolify. Verifierar att databasen svarar -- en
    tjänst som inte når sin databas är inte frisk, även om processen lever.
    """
    db_host = settings.DATABASES["default"].get("HOST")
    try:
        with connection.cursor() as cur:
            cur.execute("select 1")
            cur.fetchone()
    except Exception as exc:
        return JsonResponse(
            {
                "ok": False,
                "service": "taxitips-backend",
                "db_host": db_host,
                "error": str(exc)[:200],
            },
            status=503,
        )
    return JsonResponse({"ok": True, "service": "taxitips-backend", "db_host": db_host})


def pipeline_health(request):
    """
    Pipelinens hälsa för övervakning utifrån: 503 när beat stått still eller en
    kärnkälla inte hämtat inom sin gräns. Se core/pipeline_health.py.

    Kopplas inte som healthcheck för webbcontainern: en stillastående beat är
    inget fel i webbprocessen, och att starta om den hjälper inte.
    """
    from core.pipeline_health import evaluate

    try:
        report = evaluate()
    except Exception as exc:
        report = {"ok": False, "problems": ["database"], "error": type(exc).__name__}
    response = JsonResponse(report, status=200 if report["ok"] else 503)
    response["Cache-Control"] = "no-store"
    return response
