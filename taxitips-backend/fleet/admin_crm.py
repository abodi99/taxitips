"""
Separat CRM-modul i adminwebben — pipeline, deals, konton, kontakter, anteckningar.

Läsa: ADMIN_VIEW. Skapa/ändra: ADMIN_SELL.
Ingen automatisk synk från Stripe/självregistrering.
"""

from __future__ import annotations

from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from core.api import _json
from fleet import crm
from fleet.admin_api import _body, _company_or_404, _staff, handle
from fleet.models import CrmDeal, CrmDealStage
from fleet.roles import Perm


@require_GET
@handle
def crm_status(request):
    """GET /api/admin/crm/status"""
    _staff(request, Perm.ADMIN_VIEW)
    open_count = CrmDeal.objects.exclude(stage__in=crm.CLOSED_STAGES).count()
    return _json(request, {"ok": True, "openDeals": open_count, "openLeads": open_count})


@require_GET
@handle
def pipeline(request):
    """GET /api/admin/crm/pipeline?stage=…&board=1"""
    _staff(request, Perm.ADMIN_SELL)
    if str(request.GET.get("board") or "") in ("1", "true", "yes"):
        board = crm.pipeline_board()
        return _json(request, {"ok": True, **board})
    stage = str(request.GET.get("stage") or "").strip()
    if stage and stage not in CrmDealStage.values:
        return _json(
            request,
            {"ok": False, "reason": "invalid_stage", "message": "Ogiltigt steg."},
            status=400,
        )
    return _json(request, {
        "ok": True,
        "stages": [{"id": v, "label": label} for v, label in CrmDealStage.choices],
        "rows": crm.pipeline_deals(stage=stage or None),
    })


@require_GET
@handle
def deal_detail(request, deal_id):
    """GET /api/admin/crm/deals/<id>"""
    _staff(request, Perm.ADMIN_VIEW)
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
    })


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
            author_label=getattr(principal, "email", None) or "Admin",
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
    """GET /api/admin/companies/<id>/crm — valfri länk, ingen required widget."""
    _staff(request, Perm.ADMIN_VIEW)
    _company_or_404(company_id)
    return _json(request, {"ok": True, **crm.crm_summary_for_company(company_id)})


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
            author_label=getattr(principal, "email", None) or "Admin",
        )
    except ValueError:
        return _json(
            request,
            {"ok": False, "reason": "body_required", "message": "Skriv en anteckning."},
            status=400,
        )
    return _json(request, {"ok": True, "note": crm.note_row(note)})
