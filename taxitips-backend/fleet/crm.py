"""
Separat CRM-modul — account, person, deal och anteckningar.

Ingen koppling till självregistrering, Stripe eller prov. `company_id` på
en deal sätts bara via manuell länk / skapa kund i admin.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from django.db.models import (
    Case, Count, Exists, F, IntegerField, OuterRef, Q, Subquery, TextField, Value, When,
)
from django.db.models.functions import Collate, Lower, NullIf
from django.utils import timezone

from fleet.models import (
    CrmAccount,
    CrmDeal,
    CrmDealStage,
    CrmNote,
    CrmPerson,
    CrmTag,
    CrmTagCategory,
    CrmTagging,
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
        "city": account.city or "",
        "legalForm": account.legal_form or "",
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
        "editedAt": _iso(note.edited_at),
        "editedByLabel": note.edited_by_label or "",
    }


PIPELINE_PAGE = 200
PIPELINE_MAX = 1000


def _tag_filter(slug: str) -> Q:
    """Affären eller dess konto bär taggen."""
    account_ids = CrmTagging.objects.filter(
        entity_type="account", tag__slug=slug,
    ).values("entity_id")
    deal_ids = CrmTagging.objects.filter(
        entity_type="deal", tag__slug=slug,
    ).values("entity_id")
    return Q(id__in=deal_ids) | Q(account_id__in=account_ids)


def _contact_filter(field: str) -> Q:
    """Affärens kontakt — eller någon kontakt på kontot — har fältet ifyllt."""
    people = CrmPerson.objects.filter(
        account_id=OuterRef("account_id"),
    ).exclude(**{field: ""})
    return Q(**{f"person__{field}__gt": ""}) | Q(Exists(people))


def _account_tag_order(*, category: str, slug_prefix: str = ""):
    """sort_order för kontots tagg i en kategori (segment A=1 … X=5, tier 1–6)."""
    qs = CrmTagging.objects.filter(
        entity_type="account",
        entity_id=OuterRef("account_id"),
        tag__category=category,
    )
    if slug_prefix:
        qs = qs.filter(tag__slug__startswith=slug_prefix)
    return Subquery(
        qs.order_by("tag__sort_order").values("tag__sort_order")[:1],
        output_field=IntegerField(),
    )


_STAGE_ORDER = Case(
    *[When(stage=v, then=Value(i)) for i, v in enumerate(CrmDealStage.values)],
    output_field=IntegerField(),
)

# Sortering: nyckel → (extra annoteringar, fält i stigande ordning).
# "-nyckel" vänder ordningen; tomma värden hamnar alltid sist.
_SV = "sv-x-icu"  # svensk ordning: Å Ä Ö efter Z (ICU, finns i Supabase-Postgres)
_SORT_BASE = {
    "_s_name": Collate(Lower(NullIf("account__name", Value("", output_field=TextField()))), _SV),
    "_s_deal": Collate(Lower("name"), _SV),
}
SORTS = {
    "updated": ({}, ["updated_at"]),
    "name": ({}, ["_s_name", "_s_deal"]),
    "city": (
        {"_s_city": Collate(Lower(NullIf("account__city", Value(""))), _SV)},
        ["_s_city", "_s_name"],
    ),
    "priority": (
        {
            "_s_call": _account_tag_order(category="call"),
            "_s_seg": _account_tag_order(category="segment", slug_prefix="segment:"),
        },
        ["_s_call", "_s_seg", "_s_name"],
    ),
    "stage": ({"_s_stage": _STAGE_ORDER}, ["_s_stage", "_s_name"]),
}
DEFAULT_SORT = "-updated"


def _apply_sort(qs, sort: str):
    raw = (sort or DEFAULT_SORT).strip()
    desc = raw.startswith("-")
    key = raw.lstrip("-")
    if key not in SORTS:
        key, desc = "updated", True
    extra, fields = SORTS[key]
    qs = qs.annotate(**_SORT_BASE, **extra)
    order = [
        F(f).desc(nulls_last=True) if desc else F(f).asc(nulls_last=True)
        for f in fields
    ]
    return qs.order_by(*order, "id")


def pipeline_queryset(
    *,
    stage: str | None = None,
    q: str = "",
    tags: list[str] | tuple[str, ...] = (),
    city: str = "",
    legal_form: str = "",
    has_phone: bool = False,
    has_email: bool = False,
    sort: str = "",
    all_stages: bool = False,
):
    """
    Alla filter AND:as. Utan steg visas bara öppna affärer; `all_stages`
    struntar i steget helt (för antal per steg).
    """
    qs = CrmDeal.objects.select_related("account", "person")
    if all_stages:
        pass
    elif stage:
        qs = qs.filter(stage=stage)
    else:
        qs = qs.exclude(stage__in=CLOSED_STAGES)
    query = (q or "").strip()
    if query:
        qs = qs.filter(
            Q(name__icontains=query)
            | Q(notes_summary__icontains=query)
            | Q(account__name__icontains=query)
            | Q(account__org_number__icontains=_normalize_org(query) or query)
            | Q(account__county__icontains=query)
            | Q(account__city__icontains=query)
            | Q(person__name__icontains=query)
            | Q(person__email__icontains=query)
            | Q(person__phone__icontains=query)
        )
    for slug in dict.fromkeys(t.strip() for t in tags if t and t.strip()):
        qs = qs.filter(_tag_filter(slug))
    if (city or "").strip():
        qs = qs.filter(account__city__iexact=city.strip())
    if (legal_form or "").strip():
        qs = qs.filter(account__legal_form__iexact=legal_form.strip())
    if has_phone:
        qs = qs.filter(_contact_filter("phone"))
    if has_email:
        qs = qs.filter(_contact_filter("email"))
    return _apply_sort(qs, sort)


def pipeline_deals(
    *,
    stage: str | None = None,
    q: str = "",
    tag: str = "",
    limit: int = 500,
) -> list[dict]:
    qs = pipeline_queryset(stage=stage, q=q, tags=[tag] if tag else [])
    return [deal_row(d) for d in qs[:limit]]


def _stage_counts(**filters) -> dict[str, int]:
    """Antal per steg för samma filter (utom steget) — till flikarna."""
    filters.pop("stage", None)
    filters.pop("sort", None)
    qs = pipeline_queryset(all_stages=True, **filters).order_by()
    counts = {v: 0 for v in CrmDealStage.values}
    for row in qs.values("stage").annotate(n=Count("id")):
        counts[row["stage"]] = row["n"]
    counts[""] = sum(counts[s] for s in OPEN_STAGES)
    return counts


def _attach_tags(rows: list[dict]) -> None:
    """Kontots taggar (segment, ringordning, län …) på varje rad, i en fråga."""
    account_ids = {r["accountId"] for r in rows if r.get("accountId")}
    by_account: dict[str, list[dict]] = {}
    taggings = (
        CrmTagging.objects.filter(entity_type="account", entity_id__in=account_ids)
        .filter(tag__is_active=True)
        .select_related("tag")
        .order_by("tag__category", "tag__sort_order")
    )
    for t in taggings:
        by_account.setdefault(str(t.entity_id), []).append(tag_row(t.tag))
    for r in rows:
        r["tags"] = by_account.get(r.get("accountId") or "", [])


def pipeline_page(*, limit: int = PIPELINE_PAGE, offset: int = 0, **filters) -> dict:
    """En sida av pipelinen + totalt antal träffar och antal per steg."""
    limit = max(1, min(int(limit or PIPELINE_PAGE), PIPELINE_MAX))
    offset = max(0, int(offset or 0))
    qs = pipeline_queryset(**filters)
    rows = [deal_row(d) for d in qs[offset:offset + limit]]
    _attach_tags(rows)
    return {
        "total": qs.count(),
        "limit": limit,
        "offset": offset,
        "sort": filters.get("sort") or DEFAULT_SORT,
        "stageCounts": _stage_counts(**filters),
        "rows": rows,
    }


def pipeline_facets() -> dict:
    """Val till filterraden: orter, bolagsformer och taggar per kategori."""
    cities = (
        CrmAccount.objects.exclude(city="")
        .values_list("city", flat=True).distinct().order_by("city")
    )
    forms = (
        CrmAccount.objects.exclude(legal_form="")
        .values_list("legal_form", flat=True).distinct().order_by("legal_form")
    )
    tags = CrmTag.objects.filter(
        is_active=True,
        category__in=[CrmTagCategory.COUNTY, CrmTagCategory.CALL],
    ).order_by("category", "sort_order")
    grouped: dict[str, list[dict]] = {}
    for t in tags:
        grouped.setdefault(t.category, []).append(tag_row(t))
    return {
        "cities": list(cities),
        "legalForms": list(forms),
        "counties": grouped.get(CrmTagCategory.COUNTY, []),
        "callTiers": grouped.get(CrmTagCategory.CALL, []),
    }


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
    city: str = "",
    legal_form: str = "",
    domain: str = "",
    source: str = "",
    twenty_id: str | None = None,
) -> CrmAccount:
    return CrmAccount.objects.create(
        name=(name or "")[:500],
        org_number=_normalize_org(org_number),
        county=(county or "")[:32],
        city=(city or "").strip()[:100],
        legal_form=(legal_form or "").strip()[:64],
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
        "city": "city",
        "legalForm": "legal_form",
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
            if attr in ("city", "legal_form"):
                val = val.strip()[:CrmAccount._meta.get_field(attr).max_length]
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


def get_note(note_id) -> CrmNote | None:
    return CrmNote.objects.filter(id=note_id).first()


def update_note(note: CrmNote, *, title=None, body=None, editor_label: str = "") -> CrmNote:
    """Ändra rubrik/text. Returnerar anteckningen; tidigare text loggas av anroparen."""
    fields: list[str] = []
    if title is not None:
        note.title = (str(title).strip() or "Anteckning")[:200]
        fields.append("title")
    if body is not None:
        text = str(body).strip()
        if not text:
            raise ValueError("body_required")
        note.body = text[:12000]
        fields.append("body")
    if fields:
        note.edited_at = timezone.now()
        note.edited_by_label = (editor_label or "")[:320]
        note.save(update_fields=fields + ["edited_at", "edited_by_label"])
    return note


# ---- Kontakter -------------------------------------------------------------


def contacts_for_deal(deal: CrmDeal) -> list[dict]:
    """Alla kontakter på affärens konto; huvudkontakten först."""
    if deal.account_id:
        people = list(CrmPerson.objects.filter(account_id=deal.account_id).order_by("name"))
    else:
        people = []
    if deal.person_id and all(p.id != deal.person_id for p in people):
        primary = CrmPerson.objects.filter(id=deal.person_id).first()
        if primary:
            people.insert(0, primary)
    people.sort(key=lambda p: p.id != deal.person_id)
    rows = []
    for p in people:
        row = person_row(p)
        row["isPrimary"] = p.id == deal.person_id
        rows.append(row)
    return rows


def _ensure_account(deal: CrmDeal) -> CrmAccount:
    """Kontakter hör till ett konto — skapa ett av affärens namn om det saknas."""
    if deal.account_id:
        return deal.account
    account = create_account(name=deal.name or "Okänt bolag", source=deal.source or "admin")
    deal.account = account
    deal.save(update_fields=["account", "updated_at"])
    return account


def add_contact(deal: CrmDeal, data: dict) -> CrmPerson:
    name = str(data.get("name") or "").strip()
    email = str(data.get("email") or "").strip()
    phone = str(data.get("phone") or "").strip()
    if not (name or email or phone):
        raise ValueError("contact_required")
    account = _ensure_account(deal)
    person = create_person(
        name=name, email=email, phone=phone,
        title=str(data.get("title") or ""), account=account,
    )
    if not deal.person_id or data.get("primary"):
        set_primary_contact(deal, person)
    return person


def link_contact(deal: CrmDeal, person: CrmPerson) -> CrmPerson:
    """Koppla en befintlig kontakt till affärens konto."""
    account = _ensure_account(deal)
    if person.account_id != account.id:
        person.account = account
        person.save(update_fields=["account", "updated_at"])
    if not deal.person_id:
        set_primary_contact(deal, person)
    return person


def set_primary_contact(deal: CrmDeal, person: CrmPerson) -> CrmDeal:
    deal.person = person
    deal.save(update_fields=["person", "updated_at"])
    return deal


def unlink_contact(deal: CrmDeal, person: CrmPerson) -> None:
    """Ta bort kontakten från kontot (raden finns kvar och kan kopplas igen)."""
    if deal.account_id and person.account_id == deal.account_id:
        person.account = None
        person.save(update_fields=["account", "updated_at"])
    if deal.person_id == person.id:
        nxt = (
            CrmPerson.objects.filter(account_id=deal.account_id).exclude(id=person.id)
            .order_by("name").first()
            if deal.account_id else None
        )
        deal.person = nxt
        deal.save(update_fields=["person", "updated_at"])


def search_people(q: str, *, exclude_account_id=None, limit: int = 15) -> list[dict]:
    query = (q or "").strip()
    if len(query) < 2:
        return []
    qs = CrmPerson.objects.select_related("account").filter(
        Q(name__icontains=query) | Q(email__icontains=query) | Q(phone__icontains=query)
    )
    if exclude_account_id:
        qs = qs.exclude(account_id=exclude_account_id)
    out = []
    for p in qs.order_by("name")[:limit]:
        row = person_row(p)
        row["accountName"] = p.account.name if p.account_id and p.account else ""
        out.append(row)
    return out


def crm_summary_for_company(company_id) -> dict:
    from fleet import crm_tasks

    deal = deal_for_company(company_id)
    return {
        "linked": deal is not None,
        "deal": deal_row(deal) if deal else None,
        "notes": list_notes_for_company(company_id),
        "tasks": crm_tasks.tasks_for(deal=deal, company_id=company_id),
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


def tag_row(tag: CrmTag) -> dict[str, Any]:
    return {
        "slug": tag.slug,
        "category": tag.category,
        "label": tag.label,
    }


def list_tags_for(*, entity_type: str, entity_id) -> list[dict]:
    ids = CrmTagging.objects.filter(
        entity_type=entity_type, entity_id=entity_id,
    ).values_list("tag_id", flat=True)
    tags = CrmTag.objects.filter(id__in=ids, is_active=True).order_by("category", "sort_order")
    return [tag_row(t) for t in tags]


def ensure_tag(slug: str, *, category: str, label: str | None = None) -> CrmTag:
    tag, _ = CrmTag.objects.get_or_create(
        slug=slug,
        defaults={
            "category": category,
            "label": label or slug,
            "sort_order": 0,
            "is_active": True,
        },
    )
    return tag


def set_tags(
    *,
    entity_type: str,
    entity_id,
    slugs: list[str],
    origin: str = "manual",
    replace_categories: list[str] | None = None,
) -> None:
    """
    Sätter taggar på ett CRM-objekt. Om replace_categories anges tas befintliga
    taggar i de kategorierna bort först (en ICP, ett län, osv.).
    """
    if replace_categories:
        old = CrmTagging.objects.filter(
            entity_type=entity_type,
            entity_id=entity_id,
            tag__category__in=replace_categories,
        )
        old.delete()
    for slug in slugs:
        tag = CrmTag.objects.filter(slug=slug, is_active=True).first()
        if tag is None:
            continue
        CrmTagging.objects.get_or_create(
            tag=tag,
            entity_type=entity_type,
            entity_id=entity_id,
            defaults={"origin": origin[:32]},
        )


def find_account(*, org_number: str = "", name: str = "", twenty_id: str | None = None) -> CrmAccount | None:
    if twenty_id:
        acc = CrmAccount.objects.filter(twenty_id=twenty_id).first()
        if acc:
            return acc
    org = _normalize_org(org_number)
    if org:
        acc = CrmAccount.objects.filter(org_number=org).first()
        if acc:
            return acc
    n = (name or "").strip()
    if n:
        return CrmAccount.objects.filter(name__iexact=n).order_by("-updated_at").first()
    return None
