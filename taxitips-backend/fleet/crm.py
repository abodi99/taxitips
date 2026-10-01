"""
Separat CRM-modul — account, person, deal och anteckningar.

Ingen koppling till självregistrering, Stripe eller prov. `company_id` på
en deal sätts bara via manuell länk / skapa kund i admin.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from django.db.models import Q
from django.utils import timezone

from fleet.models import (
    CrmAccount,
    CrmDeal,
    CrmDealStage,
    CrmNote,
    CrmPerson,
)

log = logging.getLogger(__name__)

NOTE_LIMIT = 40
_ORG_RE = re.compile(r"\D")

CLOSED_STAGES = frozenset({
    CrmDealStage.WON,
    CrmDealStage.LOST,
    CrmDealStage.CHURNED,
})

OPEN_STAGES = [
    CrmDealStage.NEW,
    CrmDealStage.SCREENING,
    CrmDealStage.MEETING,
    CrmDealStage.PROPOSAL,
]


def _normalize_org(org: str) -> str:
    return _ORG_RE.sub("", org or "")


def _iso(dt) -> str | None:
    if dt is None:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.utc)
    return dt.isoformat()


def _tid(value: str | None) -> str | None:
    v = (value or "").strip()
    return v or None


def account_row(account: CrmAccount) -> dict[str, Any]:
    return {
        "id": str(account.id),
        "name": account.name or "",
        "orgNumber": account.org_number or "",
        "county": account.county or "",
        "domain": account.domain or "",
        "source": account.source or "",
        "twentyId": account.twenty_id,
        "createdAt": _iso(account.created_at),
        "updatedAt": _iso(account.updated_at),
    }


def person_row(person: CrmPerson) -> dict[str, Any]:
    return {
        "id": str(person.id),
        "accountId": str(person.account_id) if person.account_id else None,
        "name": person.name or "",
        "email": person.email or "",
        "phone": person.phone or "",
        "title": person.title or "",
        "twentyId": person.twenty_id,
        "createdAt": _iso(person.created_at),
        "updatedAt": _iso(person.updated_at),
    }


def deal_row(deal: CrmDeal, *, account: CrmAccount | None = None,
             person: CrmPerson | None = None) -> dict[str, Any]:
    acc = account
    per = person
    if acc is None and deal.account_id:
        acc = getattr(deal, "account", None)
    if per is None and deal.person_id:
        per = getattr(deal, "person", None)
    return {
        "id": str(deal.id),
        "name": deal.name or "",
        "stage": deal.stage,
        "amountOre": deal.amount_ore,
        "notesSummary": deal.notes_summary or "",
        "source": deal.source or "",
        "companyId": str(deal.company_id) if deal.company_id else None,
        "accountId": str(deal.account_id) if deal.account_id else None,
        "personId": str(deal.person_id) if deal.person_id else None,
        "account": account_row(acc) if acc is not None else None,
        "person": person_row(per) if per is not None else None,
        "twentyId": deal.twenty_id,
        "createdAt": _iso(deal.created_at),
        "updatedAt": _iso(deal.updated_at),
    }


def note_row(note: CrmNote) -> dict[str, Any]:
    return {
        "id": str(note.id),
        "accountId": str(note.account_id) if note.account_id else None,
        "personId": str(note.person_id) if note.person_id else None,
        "dealId": str(note.deal_id) if note.deal_id else None,
        "companyId": str(note.company_id) if note.company_id else None,
        "title": note.title or "Anteckning",
        "body": note.body,
        "authorLabel": note.author_label or "",
        "createdAt": _iso(note.created_at),
    }


def pipeline_deals(*, stage: str | None = None, limit: int = 120) -> list[dict]:
    qs = (
        CrmDeal.objects.select_related("account", "person")
        .order_by("-updated_at")
    )
    if stage:
        qs = qs.filter(stage=stage)
    else:
        qs = qs.exclude(stage__in=CLOSED_STAGES)
    return [deal_row(d) for d in qs[:limit]]


def pipeline_board(*, limit_per_stage: int = 40) -> dict:
    """Kolumner per öppet steg + stängda (won/lost) för översikt."""
    columns = []
    for st in list(OPEN_STAGES) + [CrmDealStage.WON, CrmDealStage.LOST]:
        rows = pipeline_deals(stage=st, limit=limit_per_stage)
        columns.append({
            "id": st,
            "label": dict(CrmDealStage.choices).get(st, st),
            "rows": rows,
        })
    return {
        "stages": [{"id": v, "label": label} for v, label in CrmDealStage.choices],
        "columns": columns,
    }


def get_deal(deal_id) -> CrmDeal | None:
    return (
        CrmDeal.objects.select_related("account", "person")
        .filter(id=deal_id)
        .first()
    )


def get_account(account_id) -> CrmAccount | None:
    return CrmAccount.objects.filter(id=account_id).first()


def get_person(person_id) -> CrmPerson | None:
    return CrmPerson.objects.filter(id=person_id).first()


def deal_for_company(company_id) -> CrmDeal | None:
    return (
        CrmDeal.objects.select_related("account", "person")
        .filter(company_id=company_id)
        .order_by("-updated_at")
        .first()
    )


def find_open_deal(*, email: str = "", org_number: str = "") -> CrmDeal | None:
    email = (email or "").strip().lower()
    org = _normalize_org(org_number)
    qs = CrmDeal.objects.select_related("account", "person").exclude(stage__in=CLOSED_STAGES)
    if email:
        by_email = qs.filter(person__email__iexact=email).order_by("-updated_at").first()
        if by_email:
            return by_email
    if org:
        by_org = qs.filter(account__org_number=org).order_by("-updated_at").first()
        if by_org:
            return by_org
    return None


def create_account(
    *,
    name: str = "",
    org_number: str = "",
    county: str = "",
    domain: str = "",
    source: str = "",
    twenty_id: str | None = None,
) -> CrmAccount:
    return CrmAccount.objects.create(
        name=(name or "")[:500],
        org_number=_normalize_org(org_number),
        county=(county or "")[:32],
        domain=(domain or "")[:255],
        source=(source or "")[:100],
        twenty_id=_tid(twenty_id),
    )


def create_person(
    *,
    name: str = "",
    email: str = "",
    phone: str = "",
    title: str = "",
    account: CrmAccount | None = None,
    twenty_id: str | None = None,
) -> CrmPerson:
    return CrmPerson.objects.create(
        account=account,
        name=(name or "")[:500],
        email=(email or "").strip().lower()[:320],
        phone=(phone or "")[:80],
        title=(title or "")[:200],
        twenty_id=_tid(twenty_id),
    )


def create_deal(
    *,
    name: str = "",
    stage: str = CrmDealStage.NEW,
    account: CrmAccount | None = None,
    person: CrmPerson | None = None,
    amount_ore: int | None = None,
    notes_summary: str = "",
    source: str = "",
    company_id=None,
    twenty_id: str | None = None,
) -> CrmDeal:
    if stage not in CrmDealStage.values:
        raise ValueError("invalid_stage")
    return CrmDeal.objects.create(
        name=(name or "")[:500],
        stage=stage,
        account=account,
        person=person,
        amount_ore=amount_ore,
        notes_summary=(notes_summary or "")[:4000],
        source=(source or "")[:100],
        company_id=company_id,
        twenty_id=_tid(twenty_id),
    )


def update_account(account: CrmAccount, data: dict) -> CrmAccount:
    fields: list[str] = []
    mapping = {
        "name": "name",
        "orgNumber": "org_number",
        "county": "county",
        "domain": "domain",
        "source": "source",
    }
    for key, attr in mapping.items():
        if key not in data:
            continue
        val = data[key]
        if attr == "org_number":
            val = _normalize_org(str(val or ""))
        else:
            val = str(val or "")
        setattr(account, attr, val)
        fields.append(attr)
    if fields:
        fields.append("updated_at")
        account.save(update_fields=fields)
    return account


def update_person(person: CrmPerson, data: dict) -> CrmPerson:
    fields: list[str] = []
    mapping = {
        "name": "name",
        "email": "email",
        "phone": "phone",
        "title": "title",
    }
    for key, attr in mapping.items():
        if key not in data:
            continue
        val = str(data[key] or "")
        if attr == "email":
            val = val.strip().lower()
        setattr(person, attr, val)
        fields.append(attr)
    if "accountId" in data:
        aid = data.get("accountId")
        person.account_id = aid or None
        fields.append("account_id")
    if fields:
        fields.append("updated_at")
        person.save(update_fields=fields)
    return person


def update_deal(deal: CrmDeal, data: dict) -> CrmDeal:
    fields: list[str] = []
    if "name" in data:
        deal.name = str(data.get("name") or "")[:500]
        fields.append("name")
    if "stage" in data:
        stage = str(data.get("stage") or "")
        if stage not in CrmDealStage.values:
            raise ValueError("invalid_stage")
        deal.stage = stage
        fields.append("stage")
    if "notesSummary" in data:
        deal.notes_summary = str(data.get("notesSummary") or "")[:4000]
        fields.append("notes_summary")
    if "source" in data:
        deal.source = str(data.get("source") or "")[:100]
        fields.append("source")
    if "amountOre" in data:
        raw = data.get("amountOre")
        deal.amount_ore = int(raw) if raw is not None and raw != "" else None
        fields.append("amount_ore")
    if "companyId" in data:
        deal.company_id = data.get("companyId") or None
        fields.append("company_id")
    if "accountId" in data:
        deal.account_id = data.get("accountId") or None
        fields.append("account_id")
    if "personId" in data:
        deal.person_id = data.get("personId") or None
        fields.append("person_id")
    if fields:
        fields.append("updated_at")
        deal.save(update_fields=fields)
    return deal


def link_deal_to_company(deal: CrmDeal, company_id, *, stage: str | None = None) -> CrmDeal:
    deal.company_id = company_id
    fields = ["company_id", "updated_at"]
    if stage and stage in CrmDealStage.values:
        deal.stage = stage
        fields.append("stage")
    deal.save(update_fields=fields)
    return deal


def list_notes_for_deal(deal_id, *, limit: int = NOTE_LIMIT) -> list[dict]:
    notes = CrmNote.objects.filter(deal_id=deal_id).order_by("-created_at")[:limit]
    return [note_row(n) for n in notes]


def list_notes_for_company(company_id, *, limit: int = NOTE_LIMIT) -> list[dict]:
    notes = (
        CrmNote.objects.filter(company_id=company_id)
        .order_by("-created_at")[:limit]
    )
    return [note_row(n) for n in notes]


def list_notes_for_targets(
    *,
    deal_id=None,
    account_id=None,
    person_id=None,
    company_id=None,
    limit: int = NOTE_LIMIT,
) -> list[dict]:
    q = Q()
    if deal_id:
        q |= Q(deal_id=deal_id)
    if account_id:
        q |= Q(account_id=account_id)
    if person_id:
        q |= Q(person_id=person_id)
    if company_id:
        q |= Q(company_id=company_id)
    if not q:
        return []
    notes = CrmNote.objects.filter(q).order_by("-created_at")[:limit]
    return [note_row(n) for n in notes]


def create_note(
    *,
    body: str,
    title: str = "",
    account_id=None,
    person_id=None,
    deal_id=None,
    company_id=None,
    author_user_id=None,
    author_label: str = "",
    twenty_id: str | None = None,
) -> CrmNote:
    text = body.strip()
    if not text:
        raise ValueError("body_required")
    if not any([account_id, person_id, deal_id, company_id]):
        raise ValueError("target_required")
    return CrmNote.objects.create(
        account_id=account_id,
        person_id=person_id,
        deal_id=deal_id,
        company_id=company_id,
        author_user_id=author_user_id,
        author_label=(author_label or "")[:320],
        title=(title or "Anteckning")[:200],
        body=text[:12000],
        twenty_id=_tid(twenty_id),
    )


def crm_summary_for_company(company_id) -> dict:
    deal = deal_for_company(company_id)
    return {
        "linked": deal is not None,
        "deal": deal_row(deal) if deal else None,
        "notes": list_notes_for_company(company_id),
    }


def ingest_web_lead(
    *,
    name: str,
    email: str,
    company: str = "",
    message: str = "",
    source: str = "taxitips_web",
    page: str = "",
) -> CrmDeal:
    """Weblead från taxitips.se → account + person + deal i steg `new`."""
    existing = find_open_deal(email=email)
    summary = message.strip()[:2000]
    if page:
        summary = f"{summary}\n\nSida: {page}".strip()
    if existing:
        if summary and summary not in (existing.notes_summary or ""):
            existing.notes_summary = f"{existing.notes_summary}\n\n{summary}".strip()[:4000]
            existing.save(update_fields=["notes_summary", "updated_at"])
        return existing
    account = create_account(name=company or name, source=source)
    person = create_person(name=name, email=email, account=account)
    return create_deal(
        name=company or f"Lead — {name}" or "Weblead",
        account=account,
        person=person,
        source=source,
        notes_summary=summary,
        stage=CrmDealStage.NEW,
    )


def upsert_from_twenty_account(*, twenty_id: str, **fields) -> CrmAccount:
    tid = _tid(twenty_id)
    if not tid:
        raise ValueError("twenty_id_required")
    existing = CrmAccount.objects.filter(twenty_id=tid).first()
    if existing:
        update_account(existing, {
            "name": fields.get("name", existing.name),
            "orgNumber": fields.get("org_number", existing.org_number),
            "county": fields.get("county", existing.county),
            "domain": fields.get("domain", existing.domain),
            "source": fields.get("source", existing.source),
        })
        return existing
    return create_account(twenty_id=tid, **fields)


def upsert_from_twenty_person(*, twenty_id: str, account: CrmAccount | None = None,
                              **fields) -> CrmPerson:
    tid = _tid(twenty_id)
    if not tid:
        raise ValueError("twenty_id_required")
    existing = CrmPerson.objects.filter(twenty_id=tid).first()
    if existing:
        data = {
            "name": fields.get("name", existing.name),
            "email": fields.get("email", existing.email),
            "phone": fields.get("phone", existing.phone),
            "title": fields.get("title", existing.title),
        }
        if account is not None:
            data["accountId"] = str(account.id)
        update_person(existing, data)
        return existing
    return create_person(twenty_id=tid, account=account, **fields)


def upsert_from_twenty_deal(*, twenty_id: str, account: CrmAccount | None = None,
                            person: CrmPerson | None = None, **fields) -> CrmDeal:
    tid = _tid(twenty_id)
    if not tid:
        raise ValueError("twenty_id_required")
    existing = CrmDeal.objects.filter(twenty_id=tid).first()
    stage = fields.get("stage", CrmDealStage.NEW)
    if existing:
        update_deal(existing, {
            "name": fields.get("name", existing.name),
            "stage": stage,
            "notesSummary": fields.get("notes_summary", existing.notes_summary),
            "source": fields.get("source", existing.source),
            "amountOre": fields.get("amount_ore", existing.amount_ore),
            "accountId": str(account.id) if account else existing.account_id,
            "personId": str(person.id) if person else existing.person_id,
        })
        return existing
    return create_deal(
        twenty_id=tid,
        account=account,
        person=person,
        name=fields.get("name", ""),
        stage=stage,
        notes_summary=fields.get("notes_summary", ""),
        source=fields.get("source", "twenty"),
        amount_ore=fields.get("amount_ore"),
    )
