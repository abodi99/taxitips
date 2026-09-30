"""
CORS-preflight för förar-API:t.

Varje anrop appen gör bär `X-Device-Token` eller `Authorization`, och en
egen header gör anropet "icke-enkelt": webbläsaren skickar då en OPTIONS-
fråga först och gör det riktiga anropet bara om den svarar. Våra vyer är
`@require_GET` och svarade 405 på den frågan, så Flutter web fick
"Failed to fetch" på varje hämtning -- utan att något syntes i Djangos
logg, eftersom 405 är ett helt normalt svar.

Mobilappen påverkas inte alls: den skickar ingen Origin och gör aldrig
någon preflight. Det är därför felet kunde finnas utan att märkas.
"""

from __future__ import annotations

from django.http import HttpResponse


class CorsPreflightMiddleware:
    """Svarar på OPTIONS mot /api/*, med samma origin-kontroll som vyerna."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "OPTIONS" and request.path.startswith("/api/"):
            from core.api import _cors

            response = _cors(HttpResponse(status=204), request)
            # Webbläsaren får slippa fråga om igen för varje anrop under en
            # timme. Kort nog att en ändrad origin-lista slår igenom under
            # samma arbetspass.
            if response.has_header("Access-Control-Allow-Origin"):
                response["Access-Control-Max-Age"] = "3600"
            return response
        return self.get_response(request)


# Headrarna appen skickar på varje anrop (taxitips-app/lib/client_info.dart).
# De måste stå i CORS-svaret, annars nekar webbläsaren varje anrop från
# Flutter web -- samma tysta "Failed to fetch" som preflighten ovan en gång gav.
CLIENT_HEADERS = ("X-App-Version", "X-App-Build", "X-App-Platform", "X-OS-Version", "X-Device-Model")


class RequestContextMiddleware:
    """
    Ett id per begäran, och en bokföring av serverfel.

    * `X-Request-Id` i varje svar och på varje loggrad under begäran
      (core/request_context.py, core/log_filters.ContextFormatter). En
      användare som ser ett fel kan läsa upp id:t; supporten hittar raden.
    * Ett 5xx från /api/ skrivs som ett serverfel i `fleet_client_error`, med
      id, sökväg och konto/telefon men utan feltext -- den står i loggen under
      samma id. Adminwebbens fellista visar då både appens och serverns fel.
    * CORS-svaret får appens metadataheaders och exponerar `X-Request-Id`.

    Ytterst i MIDDLEWARE, så att även en preflight och ett fel i en annan
    middleware får ett id.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from core import request_context

        ctx, token = request_context.begin(request)
        try:
            response = self.get_response(request)
            try:
                response["X-Request-Id"] = ctx.request_id
                allow = response.get("Access-Control-Allow-Headers")
                if allow:
                    missing = [h for h in CLIENT_HEADERS if h.lower() not in allow.lower()]
                    if missing:
                        response["Access-Control-Allow-Headers"] = ", ".join([allow, *missing])
                    expose = response.get("Access-Control-Expose-Headers", "")
                    if "x-request-id" not in expose.lower():
                        response["Access-Control-Expose-Headers"] = (
                            f"{expose}, X-Request-Id" if expose else "X-Request-Id"
                        )
                if response.status_code >= 500 and request.path.startswith("/api/"):
                    from fleet import client_activity

                    client_activity.record_server_error(ctx, response.status_code)
            except Exception:  # noqa: BLE001 -- bokföringen får aldrig ändra svaret
                import logging

                logging.getLogger(__name__).warning(
                    "core.middleware: kunde inte bokföra begäran", exc_info=True
                )
            return response
        finally:
            request_context.end(token)
