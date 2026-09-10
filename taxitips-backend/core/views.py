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
