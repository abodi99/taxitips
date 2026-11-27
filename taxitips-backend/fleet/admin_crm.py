"""
Separat CRM-modul i adminwebben — pipeline, deals, konton, kontakter, anteckningar.

Läsa: ADMIN_VIEW. Skapa/ändra: ADMIN_SELL.
Ingen automatisk synk från Stripe/självregistrering.
"""

from __future__ import annotations

from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.api import _json
from fleet import crm, crm_tasks, outreach
from fleet.admin_api import _body, _company_or_404, _record, _staff, handle
from fleet.models import CrmCampaign, CrmCampaignRecipient, CrmDeal, CrmDealStage, OutboxMessage
from fleet.roles import Perm

# ValueError-skäl från crm/crm_tasks → begripligt fel i UI:t.
_MESSAGES = {
    "invalid_stage": "Ogiltigt steg.",
    "body_required": "Skriv en anteckning.",
    "title_required": "Skriv vad som ska göras.",
    "invalid_date": "Ogiltigt datum.",
    "invalid_status": "Ogiltig status.",
    "invalid_assignee": "Den ansvariga finns inte i personalen.",
    "contact_required": "Ange namn, e-post eller telefon.",
    "invalid_action": "Okänd åtgärd.",
}


def _bad(request, reason: str, status: int = 400):
    return _json(
        request,
        {"ok": False, "reason": reason, "message": _MESSAGES.get(reason, "Ogiltig uppgift.")},
        status=status,
    )


def _not_found(request, what: str = "Affären"):
    return _json(
        request,
        {"ok": False, "reason": "not_found", "message": f"{what} hittades inte."},
        status=404,
    )


def _author(principal) -> str:
    return crm_tasks.staff_label(principal.user_id) or "Admin"


@require_GET
@handle
def crm_status(request):
    """GET /api/admin/crm/status"""
    _staff(request, Perm.ADMIN_VIEW)
    open_count = CrmDeal.objects.exclude(stage__in=crm.CLOSED_STAGES).count()
    return _json(request, {"ok": True, "openDeals": open_count, "openLeads": open_count})


def _int_param(request, key: str, default: int) -> int:
    try:
        return int(request.GET.get(key) or default)
    except (TypeError, ValueError):
        return default


@require_GET
@handle
def pipeline(request):
    """
    GET /api/admin/crm/pipeline?stage=&q=&tag=&tag=&city=&form=&phone=1&email=1
        &sort=&limit=&offset=

    Alla filter AND:as; `tag` kan upprepas (segment:a, lan:12, call:1,
    medlem:taxiforbundet …). `sort` = updated|name|city|priority|stage, med
    "-" för fallande (standard -updated). `board=1` ger kolumner per steg.
    """
    _staff(request, Perm.ADMIN_SELL)
    stages = [{"id": v, "label": label} for v, label in CrmDealStage.choices]
    if request.GET.get("board"):
        return _json(request, {"ok": True, **crm.pipeline_board()})
    stage = str(request.GET.get("stage") or "").strip()
    if stage and stage not in CrmDealStage.values:
        return _json(
            request,
            {"ok": False, "reason": "invalid_stage", "message": "Ogiltigt steg."},
            status=400,
        )
    q = str(request.GET.get("q") or "").strip()[:200]
    tags = [str(t).strip()[:64] for t in request.GET.getlist("tag") if str(t).strip()][:8]
    city = str(request.GET.get("city") or "").strip()[:100]
    legal_form = str(request.GET.get("form") or "").strip()[:64]
    has_phone = request.GET.get("phone") == "1"
    has_email = request.GET.get("email") == "1"
    sort = str(request.GET.get("sort") or "").strip()[:20]
    page = crm.pipeline_page(
        sort=sort,
        stage=stage or None,
        q=q,
        tags=tags,
        city=city,
        legal_form=legal_form,
        has_phone=has_phone,
        has_email=has_email,
        limit=_int_param(request, "limit", crm.PIPELINE_PAGE),
        offset=_int_param(request, "offset", 0),
    )
    return _json(request, {
        "ok": True,
        "stages": stages,
        "q": q,
        "tag": tags[0] if tags else "",
        "tags": tags,
        "city": city,
        "form": legal_form,
        "phone": has_phone,
        "email": has_email,
        "facets": crm.pipeline_facets(),
        **page,
    })


@require_GET
@handle
def deal_detail(request, deal_id):
    """GET /api/admin/crm/deals/<id> — affär, anteckningar, kontakter, uppgifter."""
    principal = _staff(request, Perm.ADMIN_VIEW)
    deal = crm.get_deal(deal_id)
    if deal is None:
        return _json(
            request,
            {"ok": False, "reason": "not_found", "message": "Affären hittades inte."},
            status=404,
        )
    notes = crm.list_notes_for_targets(
        deal_id=deal.id,
        account_id=deal.account_id,
        person_id=deal.person_id,
        company_id=deal.company_id,
    )
    return _json(request, {
        "ok": True,
        "deal": crm.deal_row(deal),
        "notes": notes,
        "contacts": crm.contacts_for_deal(deal),
        "tasks": crm_tasks.tasks_for(deal=deal, company_id=deal.company_id),
        "staff": crm_tasks.staff_options(),
        "me": str(principal.user_id) if principal.user_id else None,
        "mail": _deal_mail(deal),
    })


def _deal_mail(deal) -> dict:
    """Säljmejlen till affären och var i serien bolaget är (fleet/outreach.py)."""
    recipient = (
        CrmCampaignRecipient.objects.filter(deal_id=deal.id)
        .select_related("campaign").order_by("-created_at").first()
    )
    return {
        "state": recipient.state if recipient else None,
        "stateLabel": recipient.get_state_display() if recipient else None,
        "campaign": recipient.campaign.name if recipient else None,
        "nextSendAt": recipient.next_send_at.isoformat() if recipient and recipient.next_send_at else None,
        "messages": outreach.messages(deal_id=deal.id, limit=20)["rows"],
    }


@csrf_exempt
@require_POST
@handle
def deal_create(request):
    """POST /api/admin/crm/deals — skapa account+person+deal eller bara deal."""
    _staff(request, Perm.ADMIN_SELL)
    body = _body(request)
    company_name = str(body.get("companyName") or body.get("accountName") or "")
    contact_name = str(body.get("contactName") or body.get("personName") or "")
    contact_email = str(body.get("contactEmail") or body.get("email") or "")
    contact_phone = str(body.get("contactPhone") or body.get("phone") or "")
    org_number = str(body.get("orgNumber") or "")
    county = str(body.get("county") or "")
    source = str(body.get("source") or "admin")
    stage = str(body.get("stage") or CrmDealStage.NEW)
    notes = str(body.get("notesSummary") or "")
    deal_name = str(body.get("name") or company_name or contact_name or "Affär")

    account = None
    person = None
    if body.get("accountId"):
        account = crm.get_account(body["accountId"])
    elif company_name or org_number:
        account = crm.create_account(
            name=company_name or contact_name,
            org_number=org_number,
            county=county,
            source=source,
        )
    if body.get("personId"):
        person = crm.get_person(body["personId"])
    elif contact_name or contact_email or contact_phone:
        person = crm.create_person(
            name=contact_name,
            email=contact_email,
            phone=contact_phone,
            account=account,
        )
    try:
        deal = crm.create_deal(
            name=deal_name,
            account=account,
            person=person,
            source=source,
            stage=stage,
            notes_summary=notes,
        )
    except ValueError:
        return _json(
            request,
            {"ok": False, "reason": "invalid_stage", "message": "Ogiltigt steg."},
            status=400,
        )
    deal = crm.get_deal(deal.id)
    return _json(request, {"ok": True, "deal": crm.deal_row(deal)})


@csrf_exempt
@require_POST
@handle
def deal_update(request, deal_id):
    """POST /api/admin/crm/deals/<id>/update"""
    _staff(request, Perm.ADMIN_SELL)
    deal = crm.get_deal(deal_id)
    if deal is None:
        return _json(
            request,
            {"ok": False, "reason": "not_found", "message": "Affären hittades inte."},
            status=404,
        )
    body = _body(request)
    try:
        crm.update_deal(deal, body)
    except ValueError:
        return _json(
            request,
            {"ok": False, "reason": "invalid_stage", "message": "Ogiltigt steg."},
            status=400,
        )
    # Uppdatera kopplad person/konto om fält skickas
    if deal.person_id and any(
        k in body for k in ("contactName", "contactEmail", "contactPhone", "personName", "email", "phone")
    ):
        person = crm.get_person(deal.person_id)
        if person:
            crm.update_person(person, {
                "name": body.get("contactName") or body.get("personName") or person.name,
                "email": body.get("contactEmail") or body.get("email") or person.email,
                "phone": body.get("contactPhone") or body.get("phone") or person.phone,
            })
    if deal.account_id and any(k in body for k in ("companyName", "accountName", "orgNumber", "county")):
        account = crm.get_account(deal.account_id)
        if account:
            crm.update_account(account, {
                "name": body.get("companyName") or body.get("accountName") or account.name,
                "orgNumber": body.get("orgNumber") if "orgNumber" in body else account.org_number,
                "county": body.get("county") if "county" in body else account.county,
            })
    deal = crm.get_deal(deal_id)
    return _json(request, {"ok": True, "deal": crm.deal_row(deal)})


@csrf_exempt
@require_POST
@handle
def deal_link_company(request, deal_id):
    """
    POST /api/admin/crm/deals/<id>/link-company
    {"companyId": "…", "stage": "won"} — koppla befintlig TaxiTips-kund.
    """
    _staff(request, Perm.ADMIN_SELL)
    deal = crm.get_deal(deal_id)
    if deal is None:
        return _json(
            request,
            {"ok": False, "reason": "not_found", "message": "Affären hittades inte."},
            status=404,
        )
    body = _body(request)
    fleet_id = body.get("companyId")
    if not fleet_id:
        return _json(
            request,
            {"ok": False, "reason": "company_required", "message": "Ange kund."},
            status=400,
        )
    _company_or_404(fleet_id)
    stage = str(body.get("stage") or CrmDealStage.WON)
    crm.link_deal_to_company(deal, fleet_id, stage=stage)
    deal = crm.get_deal(deal_id)
    return _json(request, {"ok": True, "deal": crm.deal_row(deal)})


@csrf_exempt
@require_POST
@handle
def deal_note(request, deal_id):
    """POST /api/admin/crm/deals/<id>/notes {"title","body"}"""
    principal = _staff(request, Perm.ADMIN_SELL)
    deal = crm.get_deal(deal_id)
    if deal is None:
        return _json(
            request,
            {"ok": False, "reason": "not_found", "message": "Affären hittades inte."},
            status=404,
        )
    body = _body(request)
    title = str(body.get("title") or "Anteckning")
    text = str(body.get("body") or "").strip()
    if not text:
        return _json(
            request,
            {"ok": False, "reason": "body_required", "message": "Skriv en anteckning."},
            status=400,
        )
    try:
        note = crm.create_note(
            deal_id=deal.id,
            account_id=deal.account_id,
            person_id=deal.person_id,
            company_id=deal.company_id,
            title=title,
            body=text,
            author_user_id=getattr(principal, "user_id", None),
            author_label=_author(principal),
        )
    except ValueError:
        return _json(
            request,
            {"ok": False, "reason": "body_required", "message": "Skriv en anteckning."},
            status=400,
        )
    return _json(request, {"ok": True, "note": crm.note_row(note)})


# Bakåtkompatibla alias (gamla /leads-vägar → deals)
lead_detail = deal_detail
lead_create = deal_create
lead_update = deal_update
lead_link_company = deal_link_company
lead_note = deal_note


@require_GET
@handle
def company_crm(request, company_id):
    """GET /api/admin/companies/<id>/crm — affär, uppgifter och anteckningar (valfritt)."""
    principal = _staff(request, Perm.ADMIN_VIEW)
    _company_or_404(company_id)
    return _json(request, {
        "ok": True,
        **crm.crm_summary_for_company(company_id),
        "companyId": str(company_id),
        "staff": crm_tasks.staff_options(),
        "me": str(principal.user_id) if principal.user_id else None,
    })


@csrf_exempt
@require_POST
@handle
def company_crm_note(request, company_id):
    """POST /api/admin/companies/<id>/crm/notes"""
    principal = _staff(request, Perm.ADMIN_SELL)
    company = _company_or_404(company_id)
    body = _body(request)
    title = str(body.get("title") or "Anteckning")
    text = str(body.get("body") or "").strip()
    if not text:
        return _json(
            request,
            {"ok": False, "reason": "body_required", "message": "Skriv en anteckning."},
            status=400,
        )
    deal = crm.deal_for_company(company.id)
    try:
        note = crm.create_note(
            company_id=company.id,
            deal_id=deal.id if deal else None,
            account_id=deal.account_id if deal else None,
            title=title,
            body=text,
            author_user_id=getattr(principal, "user_id", None),
            author_label=_author(principal),
        )
    except ValueError:
        return _json(
            request,
            {"ok": False, "reason": "body_required", "message": "Skriv en anteckning."},
            status=400,
        )
    return _json(request, {"ok": True, "note": crm.note_row(note)})


# ---------------------------------------------------------------------------
# Anteckningar: redigera
# ---------------------------------------------------------------------------


@csrf_exempt
@require_POST
@handle
def note_update(request, note_id):
    """POST /api/admin/crm/notes/<id>/update {"title","body"} — tidigare text i revisionsloggen."""
    principal = _staff(request, Perm.ADMIN_SELL)
    note = crm.get_note(note_id)
    if note is None:
        return _not_found(request, "Anteckningen")
    body = _body(request)
    before = {"title": note.title, "body": note.body}
    try:
        crm.update_note(
            note,
            title=body.get("title") if "title" in body else None,
            body=body.get("body") if "body" in body else None,
            editor_label=_author(principal),
        )
    except ValueError as exc:
        return _bad(request, str(exc))
    _record(
        principal, "crm_note_edited", company_id=note.company_id,
        subject_type="crm_note", subject_id=note.id, detail={"before": before},
    )
    return _json(request, {"ok": True, "note": crm.note_row(note)})


# ---------------------------------------------------------------------------
# Kontakter
# ---------------------------------------------------------------------------


@require_GET
@handle
def people_search(request):
    """GET /api/admin/crm/people?q=…&excludeAccount=… — befintliga kontakter att koppla."""
    _staff(request, Perm.ADMIN_SELL)
    q = str(request.GET.get("q") or "").strip()[:100]
    exclude = str(request.GET.get("excludeAccount") or "").strip() or None
    return _json(request, {"ok": True, "rows": crm.search_people(q, exclude_account_id=exclude)})


@csrf_exempt
@require_POST
@handle
def deal_contact_add(request, deal_id):
    """
    POST /api/admin/crm/deals/<id>/contacts
    {"name","email","phone","title","primary"} skapar ny, {"personId"} kopplar befintlig.
    """
    _staff(request, Perm.ADMIN_SELL)
    deal = crm.get_deal(deal_id)
    if deal is None:
        return _not_found(request)
    body = _body(request)
    if body.get("personId"):
        person = crm.get_person(body["personId"])
        if person is None:
            return _not_found(request, "Kontakten")
        crm.link_contact(deal, person)
    else:
        try:
            crm.add_contact(deal, body)
        except ValueError as exc:
            return _bad(request, str(exc))
    deal = crm.get_deal(deal_id)
    return _json(request, {"ok": True, "contacts": crm.contacts_for_deal(deal)})


@csrf_exempt
@require_POST
@handle
def deal_contact_action(request, deal_id, person_id, action):
    """POST /api/admin/crm/deals/<id>/contacts/<pid>/(primary|unlink)"""
    _staff(request, Perm.ADMIN_SELL)
    deal = crm.get_deal(deal_id)
    if deal is None:
        return _not_found(request)
    person = crm.get_person(person_id)
    if person is None:
        return _not_found(request, "Kontakten")
    if action == "primary":
        crm.link_contact(deal, person)
        crm.set_primary_contact(deal, person)
    elif action == "unlink":
        crm.unlink_contact(deal, person)
    else:
        return _bad(request, "invalid_action")
    deal = crm.get_deal(deal_id)
    return _json(request, {"ok": True, "contacts": crm.contacts_for_deal(deal)})


@csrf_exempt
@require_POST
@handle
def person_update(request, person_id):
    """POST /api/admin/crm/people/<id>/update {"name","email","phone","title"}"""
    _staff(request, Perm.ADMIN_SELL)
    person = crm.get_person(person_id)
    if person is None:
        return _not_found(request, "Kontakten")
    body = _body(request)
    data = {k: body[k] for k in ("name", "email", "phone", "title") if k in body}
    crm.update_person(person, data)
    return _json(request, {"ok": True, "person": crm.person_row(person)})


# ---------------------------------------------------------------------------
# Uppgifter
# ---------------------------------------------------------------------------


@require_GET
@handle
def tasks(request):
    """
    GET /api/admin/crm/tasks?assignee=me|all|none|<userId>&status=open|todo|doing|done|all
    Översikt: lista, siffror per tidsfack och en rad per säljare.
    """
    principal = _staff(request, Perm.ADMIN_SELL)
    assignee = str(request.GET.get("assignee") or "me").strip()[:64]
    status = str(request.GET.get("status") or "open").strip()[:10]
    data = crm_tasks.dashboard(me=principal.user_id, assignee=assignee, status=status)
    return _json(request, {
        "ok": True, "me": str(principal.user_id) if principal.user_id else None, **data,
    })


@csrf_exempt
@require_POST
@handle
def task_create(request):
    """
    POST /api/admin/crm/tasks/create
    {"title","body","dueDate":"YYYY-MM-DD","assigneeUserId","dealId","companyId"}
    Utan assigneeUserId tilldelas den som skapar.
    """
    principal = _staff(request, Perm.ADMIN_SELL)
    body = _body(request)
    deal = None
    if body.get("dealId"):
        deal = crm.get_deal(body["dealId"])
        if deal is None:
            return _not_found(request)
    company_id = body.get("companyId") or None
    if company_id:
        _company_or_404(company_id)
        if deal is None:
            deal = crm.deal_for_company(company_id)
    assignee = body.get("assigneeUserId", principal.user_id)
    try:
        task = crm_tasks.create_task(
            title=str(body.get("title") or ""),
            body=str(body.get("body") or ""),
            due_date=body.get("dueDate"),
            assignee_user_id=assignee,
            deal=deal,
            company_id=company_id,
            person_id=body.get("personId") or None,
            created_by_user_id=principal.user_id,
        )
    except ValueError as exc:
        return _bad(request, str(exc))
    return _json(request, {"ok": True, "task": crm_tasks.task_row(task)})


@csrf_exempt
@require_POST
@handle
def task_update(request, task_id):
    """POST /api/admin/crm/tasks/<id>/update {"title","body","dueDate","status","assigneeUserId"}"""
    _staff(request, Perm.ADMIN_SELL)
    task = crm_tasks.get_task(task_id)
    if task is None:
        return _not_found(request, "Uppgiften")
    try:
        crm_tasks.update_task(task, _body(request))
    except ValueError as exc:
        return _bad(request, str(exc))
    return _json(request, {"ok": True, "task": crm_tasks.task_row(task)})


@csrf_exempt
@require_POST
@handle
def task_delete(request, task_id):
    """POST /api/admin/crm/tasks/<id>/delete"""
    principal = _staff(request, Perm.ADMIN_SELL)
    task = crm_tasks.get_task(task_id)
    if task is None:
        return _not_found(request, "Uppgiften")
    _record(
        principal, "crm_task_deleted", company_id=task.company_id,
        subject_type="crm_task", subject_id=task.id,
        detail={"title": task.title, "status": task.status},
    )
    task.delete()
    return _json(request, {"ok": True})


# --- Säljutskick (fleet/outreach.py) ---------------------------------------


@require_GET
@handle
def outreach_overview(request):
    """GET /api/admin/crm/outreach — kampanjer, siffror och de senaste mejlen."""
    _staff(request, Perm.ADMIN_VIEW)
    from fleet import mailer, outreach_templates

    campaign_id = request.GET.get("campaign") or None
    offset = max(0, _int_param(request, "offset", 0))
    # Texterna för ett exempelbolag, i alla tre tilltal (bolagets storlek).
    templates = []
    event = outreach.local_event("Skåne län", timezone.now()) or outreach_templates.SAMPLE_EVENT
    for size in outreach_templates.SIZES:
        sample = outreach_templates.Context(
            company="Exempel Taxi AB", place="Malmö", first_name="Anna",
            unsubscribe_url="https://taxitips.se/avregistrera?t=exempel", size=size,
            event=event,
        )
        for step in range(1, outreach_templates.STEP_COUNT + 1):
            subject, body = outreach_templates.render(step, sample)
            score = outreach_templates.lix(outreach_templates.prose(body))
            templates.append({
                "step": step, "size": size, "sizeLabel": outreach_templates.SIZE_LABEL[size],
                "subject": subject, "body": body,
                "lix": score, "lixLabel": outreach_templates.lix_label(score),
            })
    return _json(request, {
        "ok": True,
        "enabled": outreach.enabled(),
        "configured": mailer.outreach_configured(),
        "mailbox": mailer.outreach_address(),
        "campaigns": [
            outreach.stats(c) for c in CrmCampaign.objects.order_by("-created_at")
        ],
        "messages": outreach.messages(campaign_id=campaign_id, limit=50, offset=offset),
        "offset": offset,
        "templates": templates,
    })


@require_GET
@handle
def outreach_message(request, message_id):
    """GET /api/admin/crm/outreach/messages/<id> — ett skickat mejl i sin helhet."""
    _staff(request, Perm.ADMIN_VIEW)
    row = OutboxMessage.objects.filter(
        id=message_id, category__startswith=outreach.CATEGORY_PREFIX,
    ).first()
    if row is None:
        return _not_found(request, "Mejlet")
    return _json(request, {"ok": True, "message": outreach.message_row(row, with_body=True)})


@csrf_exempt
@require_POST
@handle
def outreach_campaign_action(request, campaign_id):
    """POST /api/admin/crm/outreach/campaigns/<id> {"action": "start"|"pause"|"resume"}"""
    principal = _staff(request, Perm.ADMIN_SELL)
    campaign = CrmCampaign.objects.filter(id=campaign_id).first()
    if campaign is None:
        return _not_found(request, "Kampanjen")
    action = str(_body(request).get("action") or "")
    if action in ("start", "resume"):
        outreach.resume(campaign)
    elif action == "pause":
        outreach.pause(campaign, f"pausad av {_author(principal)}", alert=False)
    else:
        return _bad(request, "invalid_action")
    _record(
        principal, "crm_outreach_campaign", subject_type="crm_campaign",
        subject_id=str(campaign.id), detail={"action": action, "slug": campaign.slug},
    )
    return _json(request, {"ok": True, "campaign": outreach.stats(campaign)})
