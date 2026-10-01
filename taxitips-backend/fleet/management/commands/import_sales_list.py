"""
Importera ops/crm/sales_list.json → native CRM (account/person/deal/note + taggar).

Kör lokalt först (filen är gitignorerad PII):

  ./.venv/bin/python manage.py import_sales_list \\
    --path ../ops/crm/sales_list.json \\
    [--checkpoint ../ops/crm/sync_checkpoint.jsonl] \\
    [--dry-run] [--limit N]

Idempotent: matchar på orgnr, twenty_id (checkpoint) eller namn. Omkörning
fyller på ort (city) och bolagsform (legal_form) på befintliga konton och
sätter om taggarna (län, segment, ICP, ringordning, Taxiförbundet).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.areas import COUNTIES
from fleet import crm
from fleet.models import CrmDeal, CrmDealStage, CrmNote

_ORG_RE = re.compile(r"\D")

# sales_list segment → taggar + startsteg
SEGMENT_MAP = {
    "A": ("segment:a", "icp:stark", CrmDealStage.SCREENING),
    "B": ("segment:b", "icp:medel", CrmDealStage.NEW),
    "C": ("segment:c", "icp:svag", CrmDealStage.NEW),
    "D": ("segment:d", "icp:svag", CrmDealStage.NEW),
    "X": ("segment:x", "icp:ej", CrmDealStage.LOST),
}

COUNTY_BY_NAME = {name.lower(): code for code, name in COUNTIES}
# Förkortade namn i datan
for code, name in COUNTIES:
    short = name.replace(" län", "").lower()
    COUNTY_BY_NAME[short] = code
    COUNTY_BY_NAME[name.lower()] = code


def _norm_org(org) -> str:
    if org is None:
        return ""
    return _ORG_RE.sub("", str(org))


def _segment_letter(segment: str) -> str:
    s = (segment or "").strip().upper()
    if not s:
        return "D"
    return s[0]


def _county_slug(county_name: str) -> str:
    key = (county_name or "").strip().lower()
    code = COUNTY_BY_NAME.get(key)
    if code:
        return f"lan:{code}"
    # "Skåne" utan "län"
    for name, c in COUNTY_BY_NAME.items():
        if key and key in name:
            return f"lan:{c}"
    return "lan:okand"


def _load_checkpoint(path: Path | None) -> dict[str, str]:
    """name.lower() → twenty company uuid"""
    if path is None or not path.exists():
        return {}
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = str(row.get("name") or "").strip()
        tid = str(row.get("id") or "").strip()
        if name and tid:
            out[name.lower()] = tid
    return out


class Command(BaseCommand):
    help = "Importera sales_list.json till native CRM med taggar."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            default="",
            help="Sökväg till sales_list.json (default: ../ops/crm/sales_list.json)",
        )
        parser.add_argument(
            "--checkpoint",
            default="",
            help="Valfri sync_checkpoint.jsonl för twenty_id",
        )
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument(
            "--skip-notes",
            action="store_true",
            help="Hoppa över Inför samtalet-anteckningar (snabbare)",
        )

    def handle(self, *args, **opts):
        base = Path(__file__).resolve().parents[4]  # repo root (taxitips/)
        # …/taxitips-backend/fleet/management/commands → parents[3]=backend, [4]=repo
        path = Path(opts["path"] or (base / "ops" / "crm" / "sales_list.json"))
        if not path.is_absolute():
            path = (Path.cwd() / path).resolve()
        if not path.exists():
            raise CommandError(f"Hittar inte {path}")

        ck_path = opts["checkpoint"]
        if not ck_path:
            guess = path.parent / "sync_checkpoint.jsonl"
            ck_path = str(guess) if guess.exists() else ""
        checkpoint = _load_checkpoint(Path(ck_path) if ck_path else None)

        rows = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(rows, list):
            raise CommandError("sales_list.json ska vara en lista")
        limit = int(opts["limit"] or 0)
        if limit:
            rows = rows[:limit]
        dry = bool(opts["dry_run"])
        skip_notes = bool(opts["skip_notes"])

        self.stdout.write(
            f"Importerar {len(rows)} rader från {path}"
            + (f" (+{len(checkpoint)} twenty-id)" if checkpoint else "")
            + (" [dry-run]" if dry else ""),
        )
        if dry:
            for r in rows[:3]:
                letter = _segment_letter(r.get("segment") or "")
                self.stdout.write(
                    f"  {r.get('name')} org={r.get('orgnr')} "
                    f"seg={letter} lan={_county_slug(r.get('county') or '')} "
                    f"ort={r.get('city') or '—'} form={r.get('legal_form') or '—'}",
                )
            return

        created = updated = notes = 0
        for i, row in enumerate(rows, start=1):
            with transaction.atomic():
                c, u, n = self._upsert_row(
                    row, checkpoint=checkpoint, skip_notes=skip_notes,
                )
                created += c
                updated += u
                notes += n
            if i % 250 == 0:
                self.stdout.write(f"  … {i}/{len(rows)}")

        self.stdout.write(self.style.SUCCESS(
            f"Klart: {created} nya, {updated} uppdaterade, {notes} anteckningar. "
            f"Totalt deals: {CrmDeal.objects.count()}.",
        ))

    def _upsert_row(
        self, row: dict, *, checkpoint: dict[str, str], skip_notes: bool,
    ) -> tuple[int, int, int]:
        name = str(row.get("name") or row.get("legal_name") or "").strip()
        if not name:
            return 0, 0, 0
        org = _norm_org(row.get("orgnr"))
        twenty_id = checkpoint.get(name.lower())
        account = crm.find_account(org_number=org, name=name, twenty_id=twenty_id)
        city = str(row.get("city") or "").strip()
        legal_form = str(row.get("legal_form") or "").strip()
        created = 0
        updated = 0
        if account is None:
            account = crm.create_account(
                name=name,
                org_number=org,
                county=str(row.get("county") or "")[:32],
                city=city,
                legal_form=legal_form,
                domain=str(row.get("website") or "")[:255],
                source="marknadsanalys",
                twenty_id=twenty_id,
            )
            created = 1
        else:
            crm.update_account(account, {
                "name": name,
                "orgNumber": org or account.org_number,
                "county": str(row.get("county") or account.county or "")[:32],
                "city": city or account.city,
                "legalForm": legal_form or account.legal_form,
                "domain": str(row.get("website") or account.domain or "")[:255],
                "source": "marknadsanalys",
            })
            if twenty_id and not account.twenty_id:
                account.twenty_id = twenty_id
                account.save(update_fields=["twenty_id", "updated_at"])
            updated = 1

        # Person: första decision maker + telefon/e-post från raden
        dms = row.get("decision_makers") or []
        dm = dms[0] if isinstance(dms, list) and dms else {}
        person_name = str((dm or {}).get("name") or "")
        person_title = str((dm or {}).get("role") or "")
        email = str(row.get("email") or "").strip().lower()
        phone = str(row.get("phone") or "")
        person = None
        if person_name or email or phone:
            if account.id:
                from fleet.models import CrmPerson
                qs = CrmPerson.objects.filter(account_id=account.id)
                if email:
                    person = qs.filter(email__iexact=email).first()
                if person is None and person_name:
                    person = qs.filter(name__iexact=person_name).first()
                if person is None:
                    person = crm.create_person(
                        name=person_name or name,
                        email=email,
                        phone=phone,
                        title=person_title,
                        account=account,
                    )
                else:
                    crm.update_person(person, {
                        "name": person_name or person.name,
                        "email": email or person.email,
                        "phone": phone or person.phone,
                        "title": person_title or person.title,
                    })

        letter = _segment_letter(row.get("segment") or "")
        seg_slug, icp_slug, stage = SEGMENT_MAP.get(
            letter, ("segment:d", "icp:svag", CrmDealStage.NEW),
        )
        brief = str(row.get("brief") or "")[:4000]
        deal = (
            CrmDeal.objects.filter(account_id=account.id)
            .order_by("-updated_at")
            .first()
        )
        if deal is None:
            deal = crm.create_deal(
                name=name,
                account=account,
                person=person,
                stage=stage,
                notes_summary=brief,
                source="marknadsanalys",
            )
        else:
            # Behåll avancerat steg om säljaren redan flyttat affären — utom X→lost
            keep_stage = deal.stage
            if letter == "X":
                keep_stage = CrmDealStage.LOST
            elif deal.stage in (CrmDealStage.NEW, CrmDealStage.LOST, CrmDealStage.CHURNED):
                keep_stage = stage
            crm.update_deal(deal, {
                "name": name,
                "stage": keep_stage,
                "notesSummary": brief or deal.notes_summary,
                "source": "marknadsanalys",
                "personId": str(person.id) if person else deal.person_id,
            })

        # Taggar
        call_tier = int(row.get("call_tier") or 6)
        call_tier = max(1, min(6, call_tier))
        slugs = [
            "kalla:marknadsanalys",
            "research:klar",
            seg_slug,
            icp_slug,
            _county_slug(str(row.get("county") or "")),
            f"call:{call_tier}",
        ]
        if row.get("taxiforbundet"):
            slugs.append("medlem:taxiforbundet")
        crm.set_tags(
            entity_type="account",
            entity_id=account.id,
            slugs=slugs,
            origin="market_analysis",
            replace_categories=["county", "icp", "source", "research", "segment", "call"],
        )
        crm.set_tags(
            entity_type="deal",
            entity_id=deal.id,
            slugs=["kalla:marknadsanalys", seg_slug, f"call:{call_tier}"],
            origin="market_analysis",
            replace_categories=["source", "segment", "call"],
        )

        note_count = 0
        if not skip_notes and brief:
            exists = CrmNote.objects.filter(
                account_id=account.id, title="Inför samtalet",
            ).exists()
            if not exists:
                crm.create_note(
                    title="Inför samtalet",
                    body=brief,
                    account_id=account.id,
                    deal_id=deal.id,
                    author_label="Marknadsanalys",
                )
                note_count = 1
        return created, updated, note_count
