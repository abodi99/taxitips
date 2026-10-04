"""
Mäter faktaläsningen mot facit: core/fixtures/golden_tips.jsonl.

Riktiga texter ur produktionen (2026-10-04), märkta för hand med vad som hänt
(event_type), uttalat alternativ, försening och klockslag. Tvetydiga texter
(en fullsatt buss, ett maraton) är utelämnade hellre än gissade. Varje rad kan
ha flera godtagbara svar.

Körs vid ändring av prompt eller modell -- inte i testsviten: den kostar
pengar (ca 56 anrop, under en krona) och beror på nätet.

    python manage.py eval_ai                       # Flash-Lite, som granskningen
    python manage.py eval_ai --model gemini-3.8-flash
    python manage.py eval_ai --rules-only          # bara dagens regler, inga anrop

Reglernas svar räknas alltid med som jämförelse: severity_tier översatt till
närmaste händelse (line_paused -> whole_line_stop, vehicle_cancelled ->
single_departure eller partial_route, *_delayed -> delay, ignore -> en
icke-händelse, disruption_unclassified -> unclear).
"""

from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

from django.core.management.base import BaseCommand

from core import ai_client, thresholds
from core.models import Opportunity
from core.tip_facts import TipFacts

GOLDEN = Path(__file__).resolve().parents[2] / "fixtures" / "golden_tips.jsonl"

RULE_EVENTS = {
    "line_paused": {"whole_line_stop"},
    "vehicle_cancelled": {"single_departure", "partial_route"},
    "line_delayed": {"delay"},
    "vehicle_delayed": {"delay"},
    "ignore": {"facility_or_stop_change", "planned_future", "resolved"},
    "disruption_unclassified": {"unclear"},
}


def load(path: Path = GOLDEN) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def rules_event(case: dict) -> str:
    """Dagens regelväg (som ingest.assess) på samma text."""
    from core.taxi_relevance import enrich_alert
    from core.text_scoring import classify_transit_alert

    alert = {
        "id": case["id"], "header": case["title"], "description": case["summary"], "region": case["region"],
        "cause": None, "effect": None, "areas": [], "routes": [], "stops": [], "url": None,
        "active_from": None, "active_to": None,
    }
    return classify_transit_alert(alert, enrich_alert(alert)).tier


def score(case: dict, facts: TipFacts) -> dict[str, bool]:
    """Fält för fält: True = rätt, False = fel. Fält utan facit räknas inte."""
    expected = case["expected"]
    out = {"event_type": facts.event_type in expected["event_type"]}
    if "alternative" in expected:
        out["alternative"] = facts.alternative in expected["alternative"]
    if "delay_minutes" in expected:
        out["delay_minutes"] = facts.delay_minutes == expected["delay_minutes"]
    for clock in ("departure_clock", "next_departure_clock"):
        if clock in expected:
            out[clock] = (facts.__dict__.get(clock) or "").zfill(5) == expected[clock]
    return out


class Command(BaseCommand):
    help = "Mäter modellens faktaläsning mot facit (core/fixtures/golden_tips.jsonl)"

    def add_arguments(self, parser):
        parser.add_argument("--model", default=thresholds.AI_MODEL_EXTRACT)
        parser.add_argument("--rules-only", action="store_true")
        parser.add_argument("--limit", type=int, default=None)

    def _generate(self, tip, model: str, subject: str) -> TipFacts:
        """Ett anrop, i takt med minuttaket: väntar i stället för att hoppa över."""
        from core.genkit import _facts_prompt_for

        for _attempt in range(30):
            try:
                return ai_client.generate("eval", _facts_prompt_for(tip), TipFacts, model=model, subject=subject)
            except ai_client.AiUnavailable as exc:
                if "minuttaket" not in str(exc):
                    raise
                time.sleep(5)
        raise ai_client.AiUnavailable("minuttaket släppte inte")

    def handle(self, *args, model, rules_only=False, limit=None, **options):
        from core.genkit import _facts_prompt_for

        cases = load()[:limit] if limit else load()
        rule_hits = 0
        right, total = Counter(), Counter()
        misses = []
        for case in cases:
            tier = rules_event(case)
            rule_ok = bool(RULE_EVENTS.get(tier, set()) & set(case["expected"]["event_type"]))
            rule_hits += rule_ok
            if rules_only:
                if not rule_ok:
                    misses.append(f"  regel {tier:24} väntat {'/'.join(case['expected']['event_type'])}: {case['title'][:60]}")
                continue
            tip = Opportunity(
                title=case["title"], summary=case["summary"], mode=case.get("mode") or "",
                region=case["region"], places=[], alternative_note="", source_event_ids=[],
            )
            try:
                facts = self._generate(tip, model, case["id"])
            except Exception as exc:
                misses.append(f"  {case['id']} FEL {type(exc).__name__}: {exc}"[:160])
                continue
            for field, ok in score(case, facts).items():
                total[field] += 1
                right[field] += ok
                if not ok:
                    misses.append(
                        f"  {case['id']} {field}: fick {getattr(facts, field)!r}, väntat "
                        f"{case['expected'][field]!r} — {case['title'][:50]}"
                    )

        n = len(cases)
        self.stdout.write(f"Facit: {n} texter · regler: {rule_hits}/{n} rätt händelse ({rule_hits * 100 // max(n, 1)} %)")
        if not rules_only:
            self.stdout.write(f"Modell {model}:")
            for field in ("event_type", "alternative", "delay_minutes", "departure_clock", "next_departure_clock"):
                if total[field]:
                    self.stdout.write(f"  {field:22} {right[field]}/{total[field]} ({right[field] * 100 // total[field]} %)")
        if misses:
            self.stdout.write("Fel:")
            for line in misses:
                self.stdout.write(line)
