"""
Supportchatten, användarens sida: /api/support.

Samma form som resten av appens API (`_json`, `reason` + `message`). Vem som
skriver avgörs i fleet/support.py:requester_for -- kontot om appen är inloggad,
annars telefonen. En användare ser bara sin egen konversation; det finns inget
id i anropet att byta ut mot någon annans.
"""

from __future__ import annotations

from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.api import _json
from fleet import support
from fleet.api import _body, handle


def _payload(thread, *, messages: bool = True) -> dict:
    return {
        "thread": (
            {"id": str(thread.id), "status": thread.status} if thread is not None else None
        ),
        "messages": support.messages_for(thread) if (thread is not None and messages) else [],
        "unread": support.unread_for_customer(thread),
    }


@require_GET
@handle
def conversation(request):
    """
    GET /api/support[?markRead=1]

    Konversationen, eller en tom lista innan användaren skrivit något.
    `markRead=1` skickas av chattskärmen när den visas: då är supportens svar
    lästa. Listan och räknaren utan den flaggan ändrar ingenting.
    """
    requester = support.requester_for(request)
    thread = support.thread_for(requester)
    if thread is not None and request.GET.get("markRead") == "1":
        support.mark_read_by_customer(thread)
        thread.refresh_from_db()
    return _json(request, {"ok": True, **_payload(thread)})


@require_GET
@handle
def unread(request):
    """GET /api/support/unread -- bara antalet olästa svar, för en badge."""
    requester = support.requester_for(request)
    return _json(request, {"ok": True, "unread": support.unread_for_customer(support.thread_for(requester))})


@csrf_exempt
@require_POST
@handle
def send(request):
    """POST /api/support/messages {"body": "..."}"""
    requester = support.requester_for(request)
    thread, message = support.post_customer_message(requester, _body(request).get("body"))
    return _json(request, {"ok": True, "message": support.message_row(message), **_payload(thread)})
