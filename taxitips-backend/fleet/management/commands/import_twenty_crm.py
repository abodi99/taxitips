"""
Importera Twenty CRM → native fleet CRM (account / person / deal / note).

Idempotent via twenty_id. Körs lokalt först, sedan one-off i prod.

  TWENTY_API_KEY=… TWENTY_BASE_URL=https://taxitips.tw.a2m-tech.com \\
    manage.py import_twenty_crm [--dry-run] [--limit N]

Miljö:
  TWENTY_API_KEY   — API-nyckel från Twenty (Bearer)
  TWENTY_BASE_URL  — workspace-URL utan /rest (default taxitips.tw.a2m-tech.com)
"""

from __future__ import annotations

import logging
from typing import Any

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from fleet import crm
from fleet.models import CrmDealStage, CrmNote

log = logging.getLogger(__name__)

DEFAULT_BASE = "https://taxitips.tw.a2m-tech.com"

# Twenty opportunity stage → native
STAGE_MAP = {
    "NEW": CrmDealStage.NEW,
    "SCREENING": CrmDealStage.SCREENING,
    "MEETING": CrmDealStage.MEETING,
    "PROPOSAL": CrmDealStage.PROPOSAL,
    "CUSTOMER": CrmDealStage.WON,
    "WON": CrmDealStage.WON,
    "LOST": CrmDealStage.LOST,
    "CHURNED": CrmDealStage.CHURNED,
    # lowercase variants
    "new": CrmDealStage.NEW,
    "screening": CrmDealStage.SCREENING,
    "meeting": CrmDealStage.MEETING,
    "proposal": CrmDealStage.PROPOSAL,
    "customer": CrmDealStage.WON,
    "won": CrmDealStage.WON,
    "lost": CrmDealStage.LOST,
    "churned": CrmDealStage.CHURNED,
}


def _base_url() -> str:
    return (
        getattr(settings, "TWENTY_BASE_URL", None)
        or __import__("os").environ.get("TWENTY_BASE_URL")
        or DEFAULT_BASE
    ).rstrip("/")


def _api_key() -> str:
    return (
        getattr(settings, "TWENTY_API_KEY", None)
        or __import__("os").environ.get("TWENTY_API_KEY")
        or ""
    ).strip()


def _rows(payload: Any, key: str) -> list[dict]:
    """Twenty returnerar ibland {data:{companies:[…]}} och ibland {data:[…]}."""
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", payload)
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for k in (key, key.rstrip("s"), f"{key}s"):
            if isinstance(data.get(k), list):
                return [x for x in data[k] if isinstance(x, dict)]
        # GraphQL-ish edges
        for k, v in data.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return []


class Command(BaseCommand):
    help = "Importera Company/Person/Opportunity/Note från Twenty till native CRM."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limit", type=int, default=0, help="Max per objekttyp (0 = alla)")
        parser.add_argument(
            "--base-url", default="",
            help="Override TWENTY_BASE_URL",
        )

    def handle(self, *args, **opts):
        key = _api_key()
        if not key:
            raise CommandError(
                "TWENTY_API_KEY saknas. Sätt i miljön eller Coolify runtime env.",
            )
        base = (opts["base_url"] or _base_url()).rstrip("/")
        dry = bool(opts["dry_run"])
        limit = int(opts["limit"] or 0)
        session = requests.Session()
        session.headers.update({
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
        })

        companies = self._fetch_all(session, f"{base}/rest/companies", "companies", limit)
        people = self._fetch_all(session, f"{base}/rest/people", "people", limit)
        opps = self._fetch_all(
            session, f"{base}/rest/opportunities", "opportunities", limit,
        )
        notes = self._fetch_all(session, f"{base}/rest/notes", "notes", limit)

        self.stdout.write(
            f"Twenty: {len(companies)} bolag, {len(people)} personer, "
            f"{len(opps)} affärer, {len(notes)} anteckningar"
            + (" (dry-run)" if dry else ""),
        )
        if dry:
            for c in companies[:5]:
                self.stdout.write(f"  company {c.get('id')}: {c.get('name')}")
            for o in opps[:5]:
                self.stdout.write(
                    f"  opp {o.get('id')}: {o.get('name')} stage={o.get('stage')}",
                )
            return

        account_by_twenty: dict[str, Any] = {}
        for row in companies:
            tid = str(row.get("id") or "")
            if not tid:
                continue
            name = str(row.get("name") or "")
            domain = ""
            dom = row.get("domainName") or row.get("domain_name") or {}
            if isinstance(dom, dict):
                domain = str(dom.get("primaryLinkUrl") or dom.get("url") or "")
            elif isinstance(dom, str):
                domain = dom
            acc = crm.upsert_from_twenty_account(
                twenty_id=tid,
                name=name,
                org_number=str(row.get("idealCustomerProfile") or row.get("orgNumber") or "")[:32],
                domain=domain[:255],
                source="twenty",
            )
            account_by_twenty[tid] = acc

        person_by_twenty: dict[str, Any] = {}
        for row in people:
            tid = str(row.get("id") or "")
            if not tid:
                continue
            company_id = None
            link = row.get("companyId") or row.get("company")
            if isinstance(link, dict):
                company_id = str(link.get("id") or "")
            elif link:
                company_id = str(link)
            account = account_by_twenty.get(company_id) if company_id else None
            name = _person_name(row)
            emails = row.get("emails") or {}
            email = ""
            if isinstance(emails, dict):
                email = str(emails.get("primaryEmail") or emails.get("additionalEmails") or "")
                if isinstance(email, list):
                    email = email[0] if email else ""
            phones = row.get("phones") or {}
            phone = ""
            if isinstance(phones, dict):
                phone = str(phones.get("primaryPhoneNumber") or "")
            person = crm.upsert_from_twenty_person(
                twenty_id=tid,
                account=account,
                name=name,
                email=email,
                phone=phone,
                title=str(row.get("jobTitle") or "")[:200],
            )
            person_by_twenty[tid] = person

        deal_by_twenty: dict[str, Any] = {}
        for row in opps:
            tid = str(row.get("id") or "")
            if not tid:
                continue
            stage_raw = row.get("stage") or "NEW"
            if isinstance(stage_raw, dict):
                stage_raw = stage_raw.get("value") or stage_raw.get("name") or "NEW"
            stage = STAGE_MAP.get(str(stage_raw), CrmDealStage.NEW)
            company_id = _rel_id(row.get("companyId") or row.get("company"))
            person_id = _rel_id(
                row.get("pointOfContactId")
                or row.get("pointOfContact")
                or row.get("personId"),
            )
            amount = row.get("amount")
            amount_ore = None
            if isinstance(amount, dict):
                micros = amount.get("amountMicros")
                if micros is not None:
                    try:
                        amount_ore = int(round(int(micros) / 10_000))  # SEK micros → öre
                    except (TypeError, ValueError):
                        amount_ore = None
            deal = crm.upsert_from_twenty_deal(
                twenty_id=tid,
                account=account_by_twenty.get(company_id) if company_id else None,
                person=person_by_twenty.get(person_id) if person_id else None,
                name=str(row.get("name") or "Affär"),
                stage=stage,
                amount_ore=amount_ore,
                source="twenty",
            )
            deal_by_twenty[tid] = deal

        notes_created = 0
        for row in notes:
            tid = str(row.get("id") or "")
            if not tid:
                continue
            if CrmNote.objects.filter(twenty_id=tid).exists():
                continue
            title = str(row.get("title") or "Anteckning")[:200]
            body = _note_body(row)
            if not body.strip():
                continue
            # Targets: noteTarget relation eller flat companyId/personId/opportunityId
            targets = row.get("noteTargets") or row.get("targets") or []
            if isinstance(targets, dict):
                targets = targets.get("edges") or targets.get("data") or []
            account_id = person_id = deal_id = None
            for t in targets if isinstance(targets, list) else []:
                node = t.get("node") if isinstance(t, dict) and "node" in t else t
                if not isinstance(node, dict):
                    continue
                cid = _rel_id(node.get("companyId") or node.get("company"))
                pid = _rel_id(node.get("personId") or node.get("person"))
                oid = _rel_id(
                    node.get("opportunityId") or node.get("opportunity") or node.get("dealId"),
                )
                if cid and cid in account_by_twenty:
                    account_id = account_by_twenty[cid].id
                if pid and pid in person_by_twenty:
                    person_id = person_by_twenty[pid].id
                if oid and oid in deal_by_twenty:
                    deal_id = deal_by_twenty[oid].id
            if not any([account_id, person_id, deal_id]):
                # Fall back: first account if orphaned note
                continue
            crm.create_note(
                title=title,
                body=body,
                account_id=account_id,
                person_id=person_id,
                deal_id=deal_id,
                author_label="Twenty",
                twenty_id=tid,
            )
            notes_created += 1

        self.stdout.write(self.style.SUCCESS(
            f"Klart: {len(account_by_twenty)} konton, {len(person_by_twenty)} personer, "
            f"{len(deal_by_twenty)} affärer, {notes_created} nya anteckningar.",
        ))

    def _fetch_all(
        self, session: requests.Session, url: str, key: str, limit: int,
    ) -> list[dict]:
        out: list[dict] = []
        cursor = None
        page_size = min(60, limit) if limit else 60
        while True:
            params: dict[str, Any] = {"limit": page_size}
            if cursor:
                params["starting_after"] = cursor
            try:
                res = session.get(url, params=params, timeout=60)
            except requests.RequestException as exc:
                raise CommandError(f"Twenty-anrop misslyckades ({url}): {exc}") from exc
            if res.status_code == 404:
                # Äldre path-varianter
                alt = url.replace("/rest/", "/rest/v1/")
                if alt != url:
                    return self._fetch_all(session, alt, key, limit)
                self.stderr.write(f"404 på {url} — hoppar över {key}")
                return out
            if res.status_code >= 400:
                raise CommandError(
                    f"Twenty {res.status_code} på {url}: {res.text[:400]}",
                )
            payload = res.json()
            rows = _rows(payload, key)
            out.extend(rows)
            if limit and len(out) >= limit:
                return out[:limit]
            page_info = {}
            if isinstance(payload, dict):
                page_info = payload.get("pageInfo") or payload.get("data", {}).get("pageInfo") or {}
            if not page_info.get("hasNextPage"):
                # Om ingen pageInfo: en sida räcker
                if not rows or len(rows) < page_size:
                    break
                # Cursor from last id
                cursor = rows[-1].get("id")
                if not cursor or cursor == params.get("starting_after"):
                    break
            else:
                cursor = page_info.get("endCursor") or (rows[-1].get("id") if rows else None)
                if not cursor:
                    break
        return out


def _rel_id(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, dict):
        rid = value.get("id")
        return str(rid) if rid else None
    s = str(value).strip()
    return s or None


def _person_name(row: dict) -> str:
    name = row.get("name")
    if isinstance(name, dict):
        parts = [name.get("firstName") or "", name.get("lastName") or ""]
        return " ".join(p for p in parts if p).strip()
    if isinstance(name, str) and name.strip():
        return name.strip()
    return str(row.get("firstName") or "")


def _note_body(row: dict) -> str:
    body = row.get("body") or row.get("bodyV2") or ""
    if isinstance(body, dict):
        # Twenty rich text: blocknote JSON or markdown
        md = body.get("markdown") or body.get("blocknote") or body.get("text")
        if isinstance(md, str):
            return md
        return str(md or "")[:12000]
    return str(body or "")[:12000]
