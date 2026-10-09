"""
Genkit läser det reglerna inte fick ut: linje och hållplats ur fritexten.

Reglerna först (core/tip_text.py, gratis, i varje pollrunda). Hit kommer bara
tips där reglerna inte hittade linjen eller platsen, eller där bedömningen är
osäker (`confidence=low`). Modellen läser samma fakta som granskningen
(core/tip_facts.TipFacts, nu med `lines` och `stops`), och

1. **en läsning per text**, inte per rad: SL publicerar samma meddelande under
   flera external_id. Nyckeln är `Opportunity.rule_key` (core/tip_text.text_key);
   läsningen sparas i `ai_facts` + `ai_rule_key` på alla rader med texten, och
   insamlingen hämtar den varje pollrunda (`facts_for`, core/ingest.assess) --
   så att den överlever att upserten skriver om raden (migrering 0033/0034).
2. **bara det som står i texten**: `tip_facts.sanitize` kastar varje linje,
   hållplats, klockslag och försening som inte står ordagrant i källan.
   Koordinater kommer aldrig från modellen, bara ur registret (tip_text.registry_coords).
3. **reglerna sätter poängen**: för osäkra tips räknas poängen ur faktan med
   `classify_from_facts` (core/genkit.apply_facts), med AI_RAISE_CAP och
   `ai_adjusted_at` som förut. För övriga tips rör läsningen aldrig poängen.
4. **ordning och tak**: medel/starka tips först, sedan nyaste; högst
   `thresholds.AI_PLACES_MAX_PER_RUN` texter per körning; ai_client:s minut-,
   dygns- och månadstak och backoff per text (`retry_allowed`) gäller.
"""

from __future__ import annotations

import logging

from django.db.models import Case, Exists, IntegerField, OuterRef, Q, Value, When
from django.utils import timezone

from core import ai_client, thresholds
from core.models import Confidence, Opportunity, SeverityTier
from core.tip_facts import TipFacts, sanitize
from core.tip_text import TextFacts, line_label

log = logging.getLogger(__name__)

PURPOSE = "places"


def source_text(o) -> str:
    return f"{o.title or ''}\n{o.summary or ''}"


def facts_for(keys) -> dict[str, dict]:
    """Sparade läsningar per textnyckel: {rule_key: ai_facts}."""
    keys = [k for k in set(keys) if k]
    if not keys:
        return {}
    rows = (
        Opportunity.objects.filter(rule_key__in=keys, ai_facts__isnull=False)
        .exclude(ai_rule_key__isnull=True)
        .values_list("rule_key", "ai_rule_key", "ai_facts")
    )
    out: dict[str, dict] = {}
    for rule_key, ai_rule_key, facts in rows:
        if rule_key == ai_rule_key and isinstance(facts, dict) and rule_key not in out:
            out[rule_key] = facts
    return out


def merge(rules: TextFacts, facts: dict | None, text: str, *, mode: str = "") -> TextFacts:
    """
    Reglernas läsning, kompletterad med modellens där reglerna stod tomma.

    Reglerna vinner alltid där de hittat något: de är deterministiska och
    citerar texten per konstruktion. Modellens fält rensas mot texten först.
    """
    if not facts:
        return rules
    clean = sanitize(facts, text)
    merged = TextFacts(
        line=rules.line, origin=rules.origin, destination=rules.destination,
        stops=list(rules.stops), clocks=list(rules.clocks),
        delay_minutes=rules.delay_minutes, delay_qualifier=rules.delay_qualifier,
    )
    if not merged.line:
        for literal in [*clean["lines"], clean["line"], clean["train_no"]]:
            if literal:
                merged.line = (line_label(literal, mode=mode) or literal)[:60]
                break
    stops = [s for s in [clean["from_station"], *clean["stops"]] if s]
    destination = clean["to_station"]
    if not merged.station and stops:
        merged.origin = stops[0]
    for stop in stops:
        if stop.lower() != (destination or "").lower() and not any(stop.lower() == s.lower() for s in merged.stops):
            merged.stops.append(stop)
    if not merged.destination and destination:
        merged.destination = destination
    if not merged.clocks and clean["departure_clock"]:
        merged.clocks = [clean["departure_clock"]]
    if merged.delay_minutes is None and clean["delay_minutes"]:
        merged.delay_minutes = clean["delay_minutes"]
    return merged


def _candidates(now):
    """Aktiva fritexttips där reglerna inte räckte och texten inte redan lästs."""
    already_read = Opportunity.objects.filter(
        rule_key=OuterRef("rule_key"), ai_rule_key=OuterRef("rule_key"), ai_facts__isnull=False,
    )
    return (
        Opportunity.objects.filter(kind="transit", end_time__gt=now, rule_key__isnull=False)
        .exclude(severity_tier=SeverityTier.IGNORE)
        # Tågen bär station och tåg i Trafikverkets egna fält.
        .exclude(region="rail")
        # "En försening har registrerats på din bevakade linje": texten säger
        # inget mer än linjen, ingen modell kan läsa ut en plats ur den.
        .exclude(rule_id__endswith=".watched_line_notice")
        .filter(Q(station="") | Q(line="") | Q(confidence=Confidence.LOW))
        .exclude(Exists(already_read))
        .annotate(
            rank=Case(
                When(level="high", then=Value(0)), When(level="medium", then=Value(1)),
                default=Value(2), output_field=IntegerField(),
            )
        )
        .order_by("rank", "-computed_at")
    )


def pick(now=None, limit: int | None = None) -> list[tuple[str, Opportunity]]:
    """(textnyckel, representant) för de texter som ska läsas, i prioritetsordning."""
    now = now or timezone.now()
    limit = thresholds.AI_PLACES_MAX_PER_RUN if limit is None else limit
    groups: dict[str, Opportunity] = {}
    for o in _candidates(now)[: max(limit, 1) * 20]:
        groups.setdefault(o.rule_key, o)
    allowed = ai_client.retry_allowed(PURPOSE, list(groups), now)
    return [(key, o) for key, o in groups.items() if key in allowed][:limit]


def _apply_extraction(o: Opportunity, facts: dict) -> None:
    """Linje, plats och mål ur läsningen -- bara där tipset står tomt. Aldrig poäng."""
    from core.tip_text import extract

    text = source_text(o)
    merged = merge(extract(o.title, o.summary, mode=o.mode or ""), facts, text, mode=o.mode or "")
    updates: dict = {"ai_facts": facts, "ai_rule_key": o.rule_key}
    if not o.line and merged.line:
        updates["line"] = merged.line[:60]
    if not o.station and merged.station:
        updates["station"] = merged.station[:120]
    if not o.places and merged.places:
        updates["places"] = merged.places
    if not o.destination and merged.destination:
        updates["destination"] = merged.destination
    Opportunity.objects.filter(pk=o.pk).update(**updates)


def apply(key: str, facts: dict, now=None) -> int:
    """Läsningen på varje aktivt tips med samma text. Returnerar antal tips."""
    from core.genkit import apply_facts

    now = now or timezone.now()
    tips = list(Opportunity.objects.filter(rule_key=key, end_time__gt=now))
    for o in tips:
        clean = sanitize(facts, source_text(o))
        _apply_extraction(o, clean)
        if o.confidence == Confidence.LOW and o.severity_tier != SeverityTier.IGNORE:
            o.refresh_from_db()
            apply_facts(o, clean, reclassify=True)
    return len(tips)


def run(now=None, limit: int | None = None, *, stdout=None) -> dict:
    """En körning: välj, läs, spara. Stannar när ai_client säger nej."""
    from core.genkit import _facts_prompt_for

    now = now or timezone.now()
    stats = {"texts": 0, "tips": 0, "failed": 0, "skipped": ""}
    reason = ai_client.unavailable_reason(purpose=PURPOSE)
    if reason:
        stats["skipped"] = reason
        return stats
    for key, representative in pick(now, limit):
        try:
            out = ai_client.generate(
                PURPOSE, _facts_prompt_for(representative), TipFacts,
                model=thresholds.AI_MODEL_EXTRACT, subject=key, timeout=thresholds.AI_PLACES_TIMEOUT_S,
            )
        except ai_client.AiUnavailable as exc:
            stats["skipped"] = str(exc)
            break  # minuttaket eller budgeten: nästa körning tar resten
        except Exception as exc:  # loggad i ai_call; backoff per text gäller
            log.warning("places_ai: läsningen misslyckades för %s: %s", key, exc)
            stats["failed"] += 1
            continue
        facts = sanitize(out, source_text(representative))
        stats["texts"] += 1
        stats["tips"] += apply(key, facts, now)
        if stdout is not None:
            stdout.write(
                f"  {key[:8]} {facts.get('lines')} {facts.get('stops')} — {(representative.title or '')[:50]}"
            )
    return stats
