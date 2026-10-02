"""
Kvalitetsgranskning av tipsen: stämmer det vi visar med det vi vet?

Kompletterar två befintliga kontroller:

* `check_pipeline` -- hämtar källorna, och är de färska? (driften)
* `calibration_report` -- hade tipsen rätt, mätt mot förarnas utfall? (facit)

Den här svarar på frågan däremellan: **är varje aktivt tips internt korrekt?**
Betyget ska följa regeln i core/thresholds.py, varje tips ska kunna förklaras
(regel, motivering, källhändelser -- AGENTS.md invariant), tider ska vara
klockslag och inte frysta "om X min", och en avgång som visas ska inte redan ha
gått. Rent läsande: inga skrivningar, säker att köra mot produktionen.

    python manage.py audit_tips [--json] [--strict] [--hours 24]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from core import taxi_context, thresholds
from core.models import Opportunity, SourceEvent
from core.taxi_context import MEDIUM_SCORE, STRONG_SCORE

ERROR, WARN, INFO = "fel", "varning", "info"
EXAMPLES = 5
ROAD_SCORE_CAP = thresholds.ROAD_SCORE_CAP
# En avgång som gick för mer än så här länge sedan och fortfarande är "nästa".
DEPARTED_GRACE = timedelta(minutes=2)
# "om 20 min", "om 1 tim", "om 45 minuter" -- ett avstånd räknat när texten
# skrevs. Sparad text läses minuter eller timmar senare och är då fel.
_RELATIVE_TIME = re.compile(r"\bom\s+\d+\s*(?:min|minuter|tim|timmar)\b", re.IGNORECASE)


@dataclass
class Check:
    id: str
    severity: str
    title: str
    why: str
    count: int = 0
    examples: list[dict] = field(default_factory=list)

    def hit(self, o: Opportunity, **detail) -> None:
        self.count += 1
        if len(self.examples) < EXAMPLES:
            self.examples.append({
                "id": str(o.id),
                "externalId": o.external_id,
                "title": (o.title or "")[:120],
                "mode": o.mode,
                "tier": o.severity_tier,
                "score": o.demand_score,
                **detail,
            })

    def as_dict(self) -> dict:
        return {
            "id": self.id, "severity": self.severity, "title": self.title,
            "why": self.why, "count": self.count, "examples": self.examples,
        }


def _checks() -> dict[str, Check]:
    items = [
        Check("score_range", ERROR, "Poäng utanför 0–100",
              "Skalan är 0–100 överallt; utanför den betyder färg och filter ingenting."),
        Check("road_over_cap", ERROR, f"Vägtips över {ROAD_SCORE_CAP} poäng",
              "Vägen är kapad lågt med avsikt (invariant). Väderbonus eller AI får inte lyfta den."),
        Check("missing_explanation", ERROR, "Tips utan förklaring",
              "Varje tips ska ha regel (rule_id), motivering (reasons) och källhändelser."),
        Check("orphan_source", WARN, "Källhändelse saknas",
              "Tipset pekar på en källhändelse som inte finns -- förklaringen går inte att följa."),
        Check("frozen_relative_time", ERROR, "Fryst \"om X min\" i sparad text",
              "Sparad text läses senare; avstånd i tid ska vara klockslag eller räknas i appen."),
        Check("level_mismatch", WARN, "Sparad styrka följer inte regeln",
              "Stark kräver poäng ≥ 60, ingen ersättningstrafik och strandsättning "
              "(taxi_context.final_level); Svag kräver poäng under 35 eller ett alternativ."),
        Check("notified_with_alternative", ERROR, "Notis trots ersättningstrafik",
              "Med angivet alternativ står ingen strandsatt; sådant tips får inte väcka någon."),
        Check("notified_not_worthy", WARN, "Notis på tips under notisregeln",
              "Notisen gick, men tier/poäng klarar inte is_notify_worthy i dag (regeln kan ha ändrats)."),
        Check("bad_time_window", WARN, "Starttid efter sluttid",
              "Oftast ett planerat arbete som avslutats innan det börjat; sluttiden sattes vid utgång."),
        Check("shows_departed", WARN, "Visar en avgång som redan gått",
              "Nästa avgång ligger i det förflutna men tipset säger inte att det var sista."),
        Check("low_confidence_high", WARN, "Osäkert tips med högt betyg utan AI-granskning",
              "Låg konfidens (fritext) ska granskas innan det får högsta färgen."),
        Check("long_lived", INFO, "Aktivt mer än 48 timmar framåt",
              "Oftast planerade arbeten. Rimligt, men de ska inte konkurrera med akuta störningar."),
    ]
    return {c.id: c for c in items}


def audit(*, now=None, hours: int = 0, limit: int = 20000) -> dict:
    """
    Granskar aktiva tips (eller alla som startat senaste `hours` timmarna).
    Returnerar en rapport med en rad per kontroll, antal och exempel.
    """
    now = now or timezone.now()
    checks = _checks()
    qs = Opportunity.objects.filter(suppressed_at__isnull=True)
    if hours:
        qs = qs.filter(Q(start_time__gte=now - timedelta(hours=hours)) | Q(end_time__gt=now))
    else:
        qs = qs.filter(end_time__gt=now)
    rows = list(qs.order_by("-demand_score")[:limit])

    referenced: set[str] = set()
    for o in rows:
        referenced.update(str(i) for i in (o.source_event_ids or []))
    existing = {
        str(i) for i in SourceEvent.objects.filter(id__in=list(referenced)).values_list("id", flat=True)
    } if referenced else set()

    for o in rows:
        score = o.demand_score or 0
        if not 0 <= score <= 100:
            checks["score_range"].hit(o)
        if (o.kind == "road" or o.mode == "road") and score > ROAD_SCORE_CAP:
            checks["road_over_cap"].hit(o)
        if not o.rule_id or not o.reasons or not o.source_event_ids:
            checks["missing_explanation"].hit(
                o, missing=[k for k, v in (("rule_id", o.rule_id), ("reasons", o.reasons),
                                           ("source_event_ids", o.source_event_ids)) if not v],
            )
        missing = [str(i) for i in (o.source_event_ids or []) if str(i) not in existing]
        if missing:
            checks["orphan_source"].hit(o, missing=missing[:3])

        texts = {
            "title": o.title or "", "summary": o.summary or "",
            "alternative_note": o.alternative_note or "",
            "reasons": " | ".join(str(r) for r in (o.reasons or [])),
        }
        frozen = {k: m.group(0) for k, v in texts.items() if (m := _RELATIVE_TIME.search(v))}
        if frozen:
            checks["frozen_relative_time"].hit(o, found=frozen)

        # Styrkan räknas med omständigheter som inte sparas som egna fält
        # (tid, väder), så den går inte att räkna om exakt här. Det som går att
        # pröva är gränserna: ingen Stark under 60 eller med alternativ, ingen
        # Medel under 35.
        expected = None
        if o.level == "high" and (score < STRONG_SCORE or o.has_alternative):
            expected = taxi_context.final_level(score, True, o.has_alternative)
        elif o.level == "medium" and (score < MEDIUM_SCORE or o.has_alternative):
            expected = "low"
        if expected:
            checks["level_mismatch"].hit(o, stored=o.level, expected=expected)

        if o.notified_at:
            if o.has_alternative:
                checks["notified_with_alternative"].hit(o, notifiedAt=o.notified_at.isoformat())
            elif not thresholds.is_notify_worthy(o.severity_tier, score, o.has_alternative, level=o.level):
                checks["notified_not_worthy"].hit(o, notifiedAt=o.notified_at.isoformat())

        if o.start_time and o.end_time and o.start_time > o.end_time:
            checks["bad_time_window"].hit(
                o, start=o.start_time.isoformat() if o.start_time else None,
                end=o.end_time.isoformat() if o.end_time else None,
            )
        if (
            o.next_departure_at and not o.is_last_departure
            and o.next_departure_at < now - DEPARTED_GRACE
            and o.end_time and o.end_time > now
        ):
            checks["shows_departed"].hit(o, nextDepartureAt=o.next_departure_at.isoformat())
        if o.confidence == "low" and o.level == "high" and o.ai_adjusted_at is None:
            checks["low_confidence_high"].hit(o)
        if o.end_time and o.end_time > now + timedelta(hours=48):
            checks["long_lived"].hit(o, end=o.end_time.isoformat())

    results = [c.as_dict() for c in checks.values()]
    errors = sum(c["count"] for c in results if c["severity"] == ERROR)
    warnings = sum(c["count"] for c in results if c["severity"] == WARN)
    return {
        "checkedAt": now.isoformat(),
        "scope": f"startat senaste {hours} h eller aktiva" if hours else "aktiva tips",
        "tips": len(rows),
        "errors": errors,
        "warnings": warnings,
        "ok": errors == 0,
        "checks": results,
    }
