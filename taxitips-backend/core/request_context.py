"""
Vem och vad den pågående begäran gäller -- för loggen och felsökningen.

**Varför en kontextvariabel och inte ett fält på request.** Loggraden skrivs
långt ifrån vyn: i `handle()`-omslagen (fleet/api.py, fleet/admin_api.py), i
Djangos egen `django.request`-logger, i en källadapter. Ingen av dem har
begäran till hands, men alla behöver kunna säga *vilken* begäran felet hörde
till. Kontexten sätts av `RequestContextMiddleware` (core/middleware.py) och
fylls på av åtkomstkontrollen när den vet vem som frågar:

* `note_device()` -- från `fleet/access.py:device_for_token`, när en
  förartoken slagits upp;
* `note_user()` -- från `fleet/accounts.py:seen`, när en Supabase-JWT
  verifierats.

**Aldrig en token.** Kontexten bär id:n (konto, telefon, företag) och
begärans id, inget annat. En token i loggen är en token i varje system som
läser loggen.

Utanför en begäran (Celery, management-kommandon) finns ingen kontext, och
allt här är då tyst no-op.
"""

from __future__ import annotations

import contextvars
import uuid
from dataclasses import dataclass, field


@dataclass
class RequestContext:
    request_id: str
    method: str = ""
    path: str = ""
    user_id: str = ""
    device_id: str = ""
    company_id: str = ""
    # Den råa begäran, för att klientens metadata (X-App-*) ska kunna läsas
    # först när vi vet vem den gäller. Läses bara av fleet/client_activity.py.
    request: object | None = field(default=None, repr=False)


_current: contextvars.ContextVar[RequestContext | None] = contextvars.ContextVar(
    "taxitips_request_context", default=None
)


def new_request_id() -> str:
    # 16 hextecken räcker för att hitta en rad i en dags logg och är kort nog
    # att läsa upp i telefon.
    return uuid.uuid4().hex[:16]


def begin(request) -> tuple[RequestContext, contextvars.Token]:
    ctx = RequestContext(
        request_id=new_request_id(),
        method=getattr(request, "method", "") or "",
        path=(getattr(request, "path", "") or "")[:200],
        request=request,
    )
    return ctx, _current.set(ctx)


def end(token: contextvars.Token) -> None:
    try:
        _current.reset(token)
    except ValueError:
        # Annan kontext (t.ex. en tråd som ärvde variabeln): nollställ bara.
        _current.set(None)


def current() -> RequestContext | None:
    return _current.get()


def note_user(user_id) -> None:
    ctx = _current.get()
    if ctx is not None and user_id:
        ctx.user_id = str(user_id)


def note_device(device_id, company_id=None) -> None:
    ctx = _current.get()
    if ctx is None or not device_id:
        return
    ctx.device_id = str(device_id)
    if company_id and not ctx.company_id:
        ctx.company_id = str(company_id)


def log_suffix() -> str:
    """` [req=… path=… user=… device=…]` inne i en begäran, annars tom."""
    ctx = _current.get()
    if ctx is None:
        return ""
    parts = [f"req={ctx.request_id}"]
    if ctx.path:
        parts.append(f"path={ctx.path}")
    if ctx.user_id:
        parts.append(f"user={ctx.user_id}")
    if ctx.device_id:
        parts.append(f"device={ctx.device_id}")
    return " [" + " ".join(parts) + "]"
