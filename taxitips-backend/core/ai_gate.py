"""
En andra bedömning innan en osäker regel väcker en telefon.

Pushcykeln går var 30:e sekund, AI-granskningen var 5:e minut: en notis från en
regel som själv säger att den är osäker (rule_id *.ambiguous) hann gå innan
någon läst texten. 91 sådana notiser på en vecka (2026-10-04), bland dem
"Västtågen 7239 inställt från Bankeryd" med 85 poäng fast texten sa att nästa
tåg gick 35 minuter senare.

Grinden läser texten med den bättre modellen (thresholds.AI_MODEL_GATE) som
FAKTA, och reglerna räknar om (core/tip_facts.py) -- samma väg som granskningen.
Utfallet får bara SÄNKA (reclassify=False):

* fortfarande notisvärd -> notisen går som vanligt;
* inte längre notisvärd -> ingen notis. `notified_at` sätts, för tipset har
  haft sin notisstund, och skälet står i tipsets förklaring;
* AI:n avstängd, över budget, långsam eller fel -> notisen går som i dag.
  En grind som fallerar får aldrig tysta en riktig störning.

En redan cachad fakta (samma text tidigare) används utan nytt anrop.
"""

from __future__ import annotations

import logging

from django.utils import timezone

from core import ai_client, genkit, thresholds
from core.models import Opportunity, RailAssessment
from core.tip_facts import TipFacts

log = logging.getLogger(__name__)


def needs_gate(opportunity) -> bool:
    return (opportunity.rule_id or "").endswith(".ambiguous")


def _still_worthy(opportunity) -> bool:
    return thresholds.is_notify_worthy(
        opportunity.severity_tier, opportunity.demand_score, opportunity.has_alternative,
        level=thresholds.effective_level(opportunity),
    )


def _block(opportunity, why: str, now) -> None:
    reasons = list(opportunity.reasons or [])
    tag = f"AI stoppade notisen: {why[:100]}" if why else "AI stoppade notisen"
    if tag not in reasons:
        reasons.append(tag)
    # notified_at skrivs här, i pushsteget: tipset har haft sin notisstund.
    Opportunity.objects.filter(pk=opportunity.pk).update(notified_at=now, reasons=reasons)
    log.info("ai_gate: stoppade notis för %s (%s)", opportunity.external_id, why[:60])


def screen(rows: list, now=None) -> tuple[list, dict]:
    """
    Kandidaterna som får gå vidare till köandet, och vad grinden gjorde.
    Kandidater utan osäker regel passerar orörda.
    """
    now = now or timezone.now()
    passed, stats = [], {"gated": 0, "blocked": 0, "deferred": 0, "failOpen": 0, "cached": 0}
    asked = 0
    for opportunity in rows:
        if not needs_gate(opportunity):
            passed.append(opportunity)
            continue
        stats["gated"] += 1
        cached = (
            RailAssessment.objects.filter(cache_key=genkit.normalize_key(opportunity), facts__isnull=False)
            .order_by("-created_at")
            .first()
        )
        if cached is not None:
            stats["cached"] += 1
            assessment = genkit.apply_facts(
                opportunity, cached.facts, reclassify=False,
                reuse_assessment=cached if cached.opportunity_id == opportunity.id else None,
            )
        elif ai_client.unavailable_reason():
            stats["failOpen"] += 1
            passed.append(opportunity)
            continue
        elif asked >= thresholds.AI_GATE_MAX_PER_CYCLE:
            # Nästa cykel, om 30 sekunder: tipset är fortfarande kandidat.
            stats["deferred"] += 1
            continue
        else:
            asked += 1
            assessment = genkit.review(
                opportunity,
                ai_client.json_caller(
                    "gate", TipFacts, model=thresholds.AI_MODEL_GATE,
                    subject=opportunity.external_id, timeout=thresholds.AI_GATE_TIMEOUT_S,
                ),
                reclassify=False, bypass_cache=True, facts=True,
            )
            if assessment is None:
                stats["failOpen"] += 1
                passed.append(opportunity)
                continue
        opportunity.refresh_from_db()
        if _still_worthy(opportunity):
            passed.append(opportunity)
        else:
            stats["blocked"] += 1
            _block(opportunity, assessment.verdict or "", now)
    return passed, stats
