"""
Supportchatten, personalens sida: /api/admin/support/...

Läsa kräver `ADMIN_VIEW`, svara och avsluta `ADMIN_SUPPORT` (alla
personalroller). Logiken bor i fleet/support.py.
"""

from __future__ import annotations

from django.db.models import Q
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.api import _json
from fleet import support
from fleet.admin_api import _body, _company_or_404, _staff, handle
from fleet.models import SupportThread
from fleet.roles import Perm

LIST_LIMIT = 200


def _thread_or_404(thread_id) -> SupportThread:
    thread = SupportThread.objects.filter(id=thread_id).first()
    if thread is None:
        raise support.SupportError("unknown_thread", "Konversationen finns inte.", status=404)
    return thread


def _detail(thread: SupportThread) -> dict:
    return {
        "thread": support.thread_row(thread, company_names=support.company_names([thread])),
        "messages": support.messages_for(thread),
    }


@require_GET
@handle
def threads(request):
    """
    GET /api/admin/support/threads?status=open|closed|all&companyId=...

    Väntande först (användaren har skrivit något ingen läst), sedan senast
    aktiva. `waiting` i svaret är samma fråga som räknaren i menyn.
    """
    _staff(request, Perm.ADMIN_VIEW)
    status = request.GET.get("status") or "open"
    rows = SupportThread.objects.exclude(last_message_at__isnull=True)
    if status in SupportThread.Status.values:
        rows = rows.filter(status=status)
    company_id = request.GET.get("companyId")
    if company_id:
        rows = rows.filter(company_id=company_id)
    q = (request.GET.get("q") or "").strip()
    if q:
        from billing.models import Company

        ids = list(Company.objects.filter(name__icontains=q).values_list("id", flat=True))
        rows = rows.filter(Q(requester_label__icontains=q) | Q(company_id__in=ids))
    found = list(rows.order_by("-last_message_at")[:LIST_LIMIT])
    names = support.company_names(found)
    out = [support.thread_row(t, company_names=names) for t in found]
    out.sort(key=lambda r: (not r["waiting"],))  # stabil: väntande först, annars tidsordning
    previews = _previews(found)
    for row in out:
        row["preview"] = previews.get(row["id"], "")
    return _json(request, {"ok": True, "threads": out, "waiting": support.waiting_threads().count()})


def _previews(threads) -> dict:
    """Senaste meddelandet per tråd, avkortat -- en fråga per sida, inte per rad."""
    from fleet.models import SupportMessage

    out: dict[str, str] = {}
    ids = [t.id for t in threads]
    for message in (
        SupportMessage.objects.filter(thread_id__in=ids)
        .order_by("thread_id", "-created_at").distinct("thread_id")
    ):
        text = message.body.replace("\n", " ")
        prefix = "Du: " if message.sender == SupportMessage.Sender.STAFF else ""
        out[str(message.thread_id)] = prefix + (text if len(text) <= 120 else text[:117] + "…")
    return out


@require_GET
@handle
def summary(request):
    """GET /api/admin/support/summary -- antal som väntar på svar, för menyn."""
    _staff(request, Perm.ADMIN_VIEW)
    return _json(request, {"ok": True, "waiting": support.waiting_threads().count()})


@require_GET
@handle
def thread_detail(request, thread_id):
    """GET /api/admin/support/threads/<id>[?markRead=1]"""
    principal = _staff(request, Perm.ADMIN_VIEW)
    thread = _thread_or_404(thread_id)
    # Bara den som kan svara markerar som läst. En läsbehörighet som tömde
    # "väntar på svar" hade kunnat gömma en fråga ingen besvarat.
    if request.GET.get("markRead") == "1" and principal.can(Perm.ADMIN_SUPPORT):
        support.mark_read_by_staff(thread)
        thread.refresh_from_db()
    return _json(request, {"ok": True, **_detail(thread)})


@csrf_exempt
@require_POST
@handle
def reply(request, thread_id):
    """POST /api/admin/support/threads/<id>/messages {"body": "..."}"""
    principal = _staff(request, Perm.ADMIN_SUPPORT)
    thread = _thread_or_404(thread_id)
    support.post_staff_message(thread, staff_user_id=principal.user_id, body=_body(request).get("body"))
    thread.refresh_from_db()
    return _json(request, {"ok": True, **_detail(thread)})


@csrf_exempt
@require_POST
@handle
def set_status(request, thread_id):
    """POST /api/admin/support/threads/<id>/status {"status": "open"|"closed"}"""
    principal = _staff(request, Perm.ADMIN_SUPPORT)
    thread = _thread_or_404(thread_id)
    support.set_status(thread, str(_body(request).get("status") or ""), staff_user_id=principal.user_id)
    return _json(request, {"ok": True, **_detail(thread)})


@csrf_exempt
@require_POST
@handle
def start_with_company(request, company_id):
    """
    POST /api/admin/companies/<id>/support -- öppna (eller hitta) konversationen
    med bolagets ägare, så att personalen kan skriva först.
    """
    principal = _staff(request, Perm.ADMIN_SUPPORT)
    company = _company_or_404(company_id)
    thread = support.thread_for_company_owner(company.id, staff_user_id=principal.user_id)
    return _json(request, {"ok": True, **_detail(thread)})
