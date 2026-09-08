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
