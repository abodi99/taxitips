"""
Språkmodellsgranskning av osäkra bedömningar.

Var den gör nytta -- och var den inte gör det
---------------------------------------------
Efter Fas 2 har alla 24 tågtips `confidence: high`. Det är inte en
förbättring att jaga: de strukturella signalerna (nästa avgång, sista
tåget, ersättningstrafik) svarar på frågan direkt, och en språkmodell kan
inte tillföra något till "Trafikverket säger att bussen ersätter".

Osäkerheten sitter i buss- och spårvagnsflödena, där bedömningen görs på
fritext. Mätt live: många `confidence: low` tips, och bland dem finns fall
som

    97  "Hållplats Elektravägen inställd pga vägarbete"   -- vägarbete, ej taxi
    60  "Buss linje 210 riskerar att bli försenad"         -- försening märkt cancelled
    35  "Ny avgångstid"                                    -- säger inget

Det är där en modell kan läsa meningen i stället för nyckelorden.

Regler
------
1. **confidence=low → omklassning.** Regelverket har redan sagt att det
   inte vet. Genkit får sätta score (0–100) och severity_tier inom
   tillåtna värden -- även höja -- och får alla fält som finns på tipset
   plus rå källkontext. Det är en medveten utvidgning av den gamla
   "bara sänk"-regeln: den gällde när AI:n skulle dämpa redan höga
   gissningar, inte när fritexten hade fel klass.
2. **confidence≠low → bara sänka** (min(regel, modell)), om den vägen
   någonsin används. Skyddsräcket lever kvar i RailAssessment.save().
3. Cache på normaliserad form, inte titel.
4. Fallerar anropet behålls regelsvaret. Blockerar aldrig en skrivning.
"""

from __future__ import annotations

import json
import logging
import re

from core import thresholds
from core.models import (
    Confidence,
    Opportunity,
    RailAssessment,
    SeverityTier,
    SourceEvent,
    TransportMode,
)
from core.taxi_context import final_level

log = logging.getLogger(__name__)

ALLOWED_TIERS = frozenset(SeverityTier.values)
ALLOWED_MODES = frozenset(
    m for m in TransportMode.values if m not in ("", TransportMode.UNKNOWN, TransportMode.ROAD)
)

_BAD_STATION_RE = re.compile(
    r"^(inställ\w*|övriga avgångar|buss\w* ersätter|ersättnings\w*|försening\w*|"
    r"trafikstörning\w*|ny avgångstid|tågbyte|invänta info|okänd|ingen|null|none|-)$",
    re.IGNORECASE,
)

# Instruktionerna först och lika för varje tips, tipsets egna data sist: då kan
# början av prompten återanvändas (cachas) mellan anropen och kostar mindre.
PROMPT = """Du är bedömare åt TaxiTips, en app för svenska taxiförare.
Frågan är: står resenärer kvar utan alternativ och behöver taxi -- och
hur stark är signalen (0–100)?

Regelverket gissade på fritext och satte confidence=low. Du får ALL
tillgänglig data och ska omklassa tipset. Du FÅR höja eller sänka poängen
och byta severity_tier när texten och signalerna motiverar det.

## severity_tier — välj EXAKT en
- line_paused: hela linjen/sträckan stoppad nu, ingen trafik
- vehicle_cancelled: en eller flera avgångar inställda
- line_delayed: försening på linjen
- vehicle_delayed: enstaka avgång försenad / "riskerar att bli försenad"
- disruption_unclassified: oklart, svag text
- ignore: ej taxirelevant nu (hållplats flyttad/indragen när linjen går förbi, hiss/rulltrappa, kort tåg som ändå går, kommande arbete längre fram i tiden, eller störning som redan är över — sätt då score 0)
- road_accident_or_closure / road_work_or_queue / road_work: väghändelser
  (skapar sällan taxikunder — håll score lågt, typ under 20)

## Poängvägledning
- Ej taxirelevant (hiss, flyttad hållplats, kort tåg, redan avklarad störning, kommande arbete en annan dag) → severity_tier "ignore", score 0.
- Ersättningsbuss / ersättningstrafik redan på plats → score under 30,
  has_alternative true.
- "Riskerar att bli försenad", ny tid, omväg, mindre försening (5–15 min) →
  vehicle_delayed eller disruption_unclassified, score 10–25.
- Verkligt inställd avgång utan alternativ, rusning / knutpunkt →
  vehicle_cancelled, score 55–75.
- Hela linjen stoppad utan alternativ, sista avgången → line_paused,
  score 75–95.
- Vägarbete som stänger en hållplats men bussen går vidare → ignore (0) eller score under 20.

## Stationer och färdsätt
- Om texten nämner tydlig startstation/hållplats och slutstation/destination, ange dem i `from_station` och `to_station` (bara själva stations-/hållplatsnamnet, t.ex. "Lund C", "Malmö C", aldrig ord som "Inställd" eller "Övriga avgångar"). Lämna annars som "".
- Om färdsättet är tydligt (train, metro, tram, bus, boat), ange det i `mode`, annars "".

Svara ENDAST med JSON:
{{"score": <0-100>, "severity_tier": "<en av listan>", "stranded": <true|false>, "has_alternative": <true|false|null>, "mode": "<train|metro|tram|bus|boat|>", "from_station": "<startstation eller tom>", "to_station": "<slutstation eller tom>", "why": "<kort motivering på svenska>"}}

## Tipset
Titel: {title}
Sammanfattning: {summary}
Nuvarande severity_tier: {severity_tier}
Färdsätt (mode): {mode}
Region: {region}
Platser: {places}
Regelpoäng: {score}/100
Har ersättningsalternativ (has_alternative): {has_alternative}
Alternativanteckning: {alternative_note}
Nästa avgång (minuter): {next_departure_minutes}
Sista avgången idag: {is_last_departure}
Regelverkets skäl: {reasons}

## Rå källkontext
{context_block}
"""


def _clean_station(value: object) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = re.sub(r"\s+", " ", value).strip().strip(".,;:!()[]{}\"'")
    if len(cleaned) < 2 or len(cleaned) > 60:
        return ""
    if _BAD_STATION_RE.match(cleaned):
        return ""
    return cleaned


def _encode_model_meta(
    base_model: str,
    severity_tier: str | None,
    has_alternative: bool | None,
    mode: str | None = None,
) -> str:
    base = (base_model or "gemini-flash").split("|")[0]
    if not severity_tier and has_alternative is None and not mode:
        return base[:60]
    alt_str = "" if has_alternative is None else ("1" if has_alternative else "0")
    return f"{base}|{severity_tier or ''}|{alt_str}|{mode or ''}"[:60]


def _decode_model_meta(
    model_name: str | None,
) -> tuple[str, str | None, bool | None, str | None]:
    raw = model_name or "gemini-flash"
    if "|" not in raw:
        return raw, None, None, None
    parts = raw.split("|")
    base = parts[0] or "gemini-flash"
    tier = parts[1] if len(parts) > 1 and parts[1] in ALLOWED_TIERS else None
    alt = (
        True
        if len(parts) > 2 and parts[2] == "1"
        else (False if len(parts) > 2 and parts[2] == "0" else None)
    )
    mode = parts[3] if len(parts) > 3 and parts[3] in ALLOWED_MODES else None
    return base, tier, alt, mode


def normalize_key(opportunity: Opportunity) -> str:
    """
    Cachenyckel på normaliserad form.

    Titlar duger inte: tågtitlar bär tågnummer och klockslag och är
    därmed nästan unika (28 av 28 i en mätning), medan SL/Skånetrafiken/VT
    ofta har helt generiska titlar ("Försenad avgång", "Inställd avgång")
    där hela innehållet ligger i summary. Nyckeln beskriver därför både
    titelns och sammanfattningens normaliserade form.
    """
    title = (opportunity.title or "").lower()
    title = re.sub(r"\d+", "N", title)
    title = re.sub(r"\s+", " ", title).strip()[:60]
    summary = (opportunity.summary or "").lower()
    summary = re.sub(r"\d+", "N", summary)
    summary = re.sub(r"\s+", " ", summary).strip()[:80]
    hour = opportunity.start_time.hour if opportunity.start_time else 0
    bucket = "natt" if hour >= 22 or hour <= 5 else "dag"
    alt = "alt" if opportunity.has_alternative else "noalt"
    return f"v4|{opportunity.severity_tier}|{opportunity.mode}|{title}|{summary}|{bucket}|{alt}"


def _structural_context(opportunity: Opportunity) -> str:
    """
    All tillgänglig råsignal utöver Opportunity-fälten: källans egen
    allvarlighet, ersättning, linje, orsak/effekt/områden från fritext-
    payloaden. Tom sträng om inget finns -- vi hittar aldrig på data.
    """
    lines: list[str] = []
    if not opportunity.source_event_ids:
        return "(ingen source_event kopplad)"
    events = list(
        SourceEvent.objects.filter(id__in=opportunity.source_event_ids[:5])
    )
    if not events:
        return "(source_event saknas i databasen)"

    for i, se in enumerate(events):
        raw = se.raw if isinstance(se.raw, dict) else {}
        prefix = f"Källa {i + 1} ({se.source or '?'}):"
        bits: list[str] = []
        # SourceEvent har ingen header/description-kolumn -- allt bor i raw.
        for key in ("header", "title", "message", "description", "summary"):
            if raw.get(key):
                bits.append(f"{key}={str(raw[key])[:300]}")
        sl = raw.get("sl") or {}
        if sl.get("importance_level") is not None:
            bits.append(f"SL importance_level={sl['importance_level']}/7")
        vt = raw.get("vt") or {}
        if vt.get("severity"):
            bits.append(f"VT severity={vt['severity']}")
        if raw.get("has_replacement"):
            mode = raw.get("replacement_mode") or "okänt fordon"
            bits.append(f"Trafikverket ersättningstrafik ({mode})")
        for key in (
            "route_label",
            "cause",
            "effect",
            "areas",
            "routes",
            "stops",
            "severity",
            "priority",
        ):
            val = raw.get(key)
            if val:
                bits.append(f"{key}={str(val)[:160]}")
        for nest in ("sl", "vt", "trafiklab"):
            blob = raw.get(nest)
            if isinstance(blob, dict):
                for k in ("message", "title", "description", "summary", "deviations"):
                    if blob.get(k):
                        bits.append(f"{nest}.{k}={str(blob[k])[:200]}")
        if bits:
            lines.append(prefix)
            lines.extend(f"  - {b}" for b in bits)
    return "\n".join(lines) if lines else "(ingen rå kontext)"


def _prompt_for(opportunity: Opportunity) -> str:
    context = _structural_context(opportunity)
    places = ", ".join(opportunity.places or []) or "(inga)"
    reasons = ", ".join(opportunity.reasons or []) or "(inga)"
    return PROMPT.format(
        title=opportunity.title or "",
        summary=(opportunity.summary or "")[:1200],
        severity_tier=opportunity.severity_tier or "",
        mode=opportunity.mode or "",
        region=opportunity.region or "(okänd)",
        places=places,
        score=opportunity.demand_score,
        has_alternative=opportunity.has_alternative,
        alternative_note=(opportunity.alternative_note or "")[:300] or "(ingen)",
        next_departure_minutes=opportunity.next_departure_minutes
        if opportunity.next_departure_minutes is not None
        else "(okänt)",
        is_last_departure=opportunity.is_last_departure,
        reasons=reasons,
        context_block=context,
    )


def _facts_prompt_for(opportunity: Opportunity) -> str:
    from core.tip_facts import FACTS_PROMPT

    return FACTS_PROMPT.format(
        title=opportunity.title or "",
        summary=(opportunity.summary or "")[:1200],
        mode=opportunity.mode or "",
        region=opportunity.region or "(okänd)",
        places=", ".join(opportunity.places or []) or "(inga)",
        alternative_note=(opportunity.alternative_note or "")[:300] or "(ingen)",
        context_block=_structural_context(opportunity),
    )


def apply_facts(
    opportunity: Opportunity,
    facts: dict,
    *,
    reclassify: bool,
    reuse_assessment: RailAssessment | None = None,
) -> RailAssessment:
    """Fakta -> reglernas poäng (core/tip_facts.py) -> tipset."""
    from core.tip_facts import classify_from_facts

    verdict = classify_from_facts(facts, opportunity.mode or "", opportunity.demand_score)
    return _apply(
        opportunity,
        verdict.score,
        verdict.why,
        thresholds.AI_MODEL_EXTRACT,
        reclassify=reclassify,
        severity_tier=verdict.tier,
        has_alternative=verdict.has_alternative,
        mode=verdict.mode,
        from_station=_clean_station(verdict.from_station),
        to_station=_clean_station(verdict.to_station),
        reuse_assessment=reuse_assessment,
        facts=facts,
        condition=verdict.condition,
    )


def apply_cached(opportunity: Opportunity, *, reclassify: bool = True) -> RailAssessment | None:
    """
    Applicerar en redan cachad bedömning om den finns (utan modellanrop).
    Används bl.a. direkt efter ingest.write() så att en granskad rad inte
    tappar sin bedömning mellan 90s-poll och 5m-review_uncertain.
    """
    cached = (
        RailAssessment.objects.filter(cache_key=normalize_key(opportunity))
        .order_by("-created_at")
        .first()
    )
    if not cached:
        return None
    reuse = cached if cached.opportunity_id == opportunity.id else None
    if cached.facts:
        # Räknas om från faktan: en ändrad regel slår igenom utan nytt anrop.
        return apply_facts(opportunity, cached.facts, reclassify=reclassify, reuse_assessment=reuse)
    base_model, cached_tier, cached_alt, cached_mode = _decode_model_meta(cached.model_name)
    return _apply(
        opportunity,
        cached.model_score,
        cached.verdict,
        base_model,
        reclassify=reclassify,
        severity_tier=cached_tier,
        has_alternative=cached_alt,
        mode=cached_mode,
        reuse_assessment=cached if cached.opportunity_id == opportunity.id else None,
    )


def review(
    opportunity: Opportunity,
    call_model,
    *,
    reclassify: bool = True,
    bypass_cache: bool = False,
    facts: bool = False,
) -> RailAssessment | None:
    """
    Granskar ett tips. `call_model` tar en prompt och returnerar text.

    `facts=True`: modellen läser ut fakta (core/tip_facts.TipFacts) och reglerna
    sätter poängen. Annars den äldre vägen där modellen föreslår poängen själv.

    `reclassify=True` (default för confidence=low): modellens score och
    severity_tier får ersätta regelverkets. `reclassify=False`: bara sänka.
    """
    if not bypass_cache:
        hit = apply_cached(opportunity, reclassify=reclassify)
        if hit is not None:
            log.info("genkit: cacheträff för %s", opportunity.external_id)
            return hit

    if facts:
        return _review_facts(opportunity, call_model, reclassify=reclassify)

    prompt = _prompt_for(opportunity)
    try:
        raw = call_model(prompt)
        parsed = _parse(raw)
    except Exception as exc:
        log.warning("genkit: anrop misslyckades, behåller regelpoäng: %s", exc)
        return None

    if parsed is None:
        log.warning("genkit: kunde inte tolka svaret, behåller regelpoäng")
        return None

    score, why, tier, has_alt, mode, from_station, to_station = parsed
    return _apply(
        opportunity,
        score,
        why,
        "gemini-flash",
        reclassify=reclassify,
        severity_tier=tier,
        has_alternative=has_alt,
        mode=mode,
        from_station=from_station,
        to_station=to_station,
    )


def _review_facts(opportunity: Opportunity, call_model, *, reclassify: bool) -> RailAssessment | None:
    from core.tip_facts import TipFacts

    try:
        raw = call_model(_facts_prompt_for(opportunity))
        match = re.search(r"\{.*\}", raw or "", re.S)
        if not match:
            log.warning("genkit: inget JSON i faktasvaret, behåller regelpoäng")
            return None
        parsed = TipFacts.model_validate_json(match.group(0))
    except Exception as exc:
        log.warning("genkit: faktaanrop misslyckades, behåller regelpoäng: %s", exc)
        return None
    return apply_facts(opportunity, parsed.model_dump(), reclassify=reclassify)


def _parse(
    raw: str,
) -> tuple[int, str, str | None, bool | None, str | None, str, str] | None:
    """Plockar ut JSON ur svaret, även om modellen omger det med text."""
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    score = data.get("score")
    if not isinstance(score, (int, float)):
        return None
    score_i = int(max(0, min(100, score)))
    why = str(data.get("why") or "")[:300]
    tier = data.get("severity_tier")
    if isinstance(tier, str) and tier in ALLOWED_TIERS:
        tier_out: str | None = tier
    else:
        tier_out = None
    has_alt = data.get("has_alternative")
    if has_alt is not None and not isinstance(has_alt, bool):
        has_alt = None
    mode_val = data.get("mode")
    mode_out = mode_val if isinstance(mode_val, str) and mode_val in ALLOWED_MODES else None
    from_st = _clean_station(data.get("from_station"))
    to_st = _clean_station(data.get("to_station"))
    return score_i, why, tier_out, has_alt, mode_out, from_st, to_st


def _apply(
    opportunity: Opportunity,
    model_score: int,
    why: str,
    model_name: str,
    *,
    reclassify: bool,
    severity_tier: str | None,
    has_alternative: bool | None,
    mode: str | None = None,
    from_station: str = "",
    to_station: str = "",
    reuse_assessment: RailAssessment | None = None,
    facts: dict | None = None,
    condition: str | None = None,
) -> RailAssessment:
    """
    Sparar bedömningen och uppdaterar tipset.

    Omklassning: final = model_score, ev. ny tier/has_alternative.
    Dämpning: final = min(rule, model), bara sänka.
    """
    rule = opportunity.demand_score
    if reclassify:
        final = int(max(0, min(100, model_score)))
        if final > rule:
            # En höjning når aldrig Stark på modellens ord (AI_RAISE_CAP); ett
            # tips som redan låg över taket behåller regelns poäng.
            final = max(rule, min(final, thresholds.AI_RAISE_CAP))
    else:
        final = min(rule, model_score)

    key = normalize_key(opportunity)
    encoded_model = _encode_model_meta(model_name, severity_tier, has_alternative, mode)

    if reuse_assessment is not None:
        assessment = reuse_assessment
    else:
        assessment = RailAssessment(
            opportunity=opportunity,
            cache_key=key,
            rule_score=rule,
            model_score=model_score,
            final_score=final,
            verdict=why,
            model_name=encoded_model,
            facts=facts,
        )
        assessment._allow_reclassify = reclassify  # type: ignore[attr-defined]
        assessment.save()

    updates: dict = {}
    if final != opportunity.demand_score:
        updates["demand_score"] = final
    if severity_tier and severity_tier != opportunity.severity_tier:
        if reclassify or (severity_tier == SeverityTier.IGNORE and final == 0):
            updates["severity_tier"] = severity_tier
    if has_alternative is not None and has_alternative != opportunity.has_alternative:
        if reclassify or (has_alternative is True and not opportunity.has_alternative):
            updates["has_alternative"] = has_alternative
    if mode and opportunity.mode in ("", TransportMode.UNKNOWN) and mode != opportunity.mode:
        updates["mode"] = mode
    if facts is not None and condition and reclassify:
        # Spårbarhet: vilken regel som satte poängen ur modellens fakta.
        eff_mode = updates.get("mode", opportunity.mode) or "unknown"
        eff_tier_for_rule = updates.get("severity_tier", opportunity.severity_tier)
        rule_id = f"{eff_mode}.{eff_tier_for_rule}.ai_facts.{condition}"[:80]
        if rule_id != opportunity.rule_id:
            updates["rule_id"] = rule_id

    # Uppdatera stationer/destination när modellen extraherat rena stationsnamn
    if from_station or to_station:
        existing_places = [str(p) for p in (opportunity.places or []) if p]
        if from_station and to_station and from_station.lower() != to_station.lower():
            merged = [from_station, to_station]
            for p in existing_places:
                if p.lower() not in (from_station.lower(), to_station.lower()):
                    merged.append(p)
            if merged != existing_places:
                updates["places"] = merged
            if not opportunity.destination:
                updates["destination"] = to_station
        elif from_station and not existing_places:
            updates["places"] = [from_station]
        elif to_station and not opportunity.destination:
            updates["destination"] = to_station

    # Håll alltid Opportunity.level i synk med poäng, tier och ersättningsalternativ
    eff_tier = updates.get("severity_tier", opportunity.severity_tier)
    eff_alt = updates.get("has_alternative", opportunity.has_alternative)
    if eff_tier == SeverityTier.IGNORE or final <= 0 or eff_alt:
        new_level = "low"
    else:
        was_high = opportunity.level == "high"
        new_level = final_level(final, was_high, bool(eff_alt), Confidence.MEDIUM)
        # En språkmodell får aldrig ensam höja ett tips till Stark:
        if not was_high and new_level == "high":
            new_level = "medium"
    if new_level != opportunity.level:
        updates["level"] = new_level

    if updates or (reclassify and opportunity.confidence == Confidence.LOW):
        reasons = list(opportunity.reasons or [])
        if facts is not None:
            tag = f"AI läste: {why[:100]}" if why else "AI läste texten"
            if tag not in reasons:
                reasons.append(tag)
        elif final < rule:
            tag = f"AI sänkte: {why[:80]}" if why else "AI sänkte poängen"
            if tag not in reasons:
                reasons.append(tag)
        elif final > rule:
            tag = f"AI höjde: {why[:80]}" if why else "AI höjde poängen"
            if tag not in reasons:
                reasons.append(tag)
        elif severity_tier and severity_tier != opportunity.severity_tier:
            tag = (
                f"AI omklassade till {severity_tier}: {why[:60]}"
                if why
                else f"AI omklassade till {severity_tier}"
            )
            if tag not in reasons:
                reasons.append(tag)
        updates["reasons"] = reasons
        updates["confidence"] = Confidence.MEDIUM
        # Höjde modellen tipset -- poäng, typ eller bort med alternativet -- får
        # höjningen synas i listan men aldrig ensam väcka en telefon.
        raised = (
            final > rule
            or (
                "severity_tier" in updates
                and updates["severity_tier"] != SeverityTier.IGNORE
            )
            or (updates.get("has_alternative") is False and opportunity.has_alternative)
        )
        if raised:
            from django.utils import timezone

            updates["ai_adjusted_at"] = timezone.now()
        Opportunity.objects.filter(pk=opportunity.pk).update(**updates)
        log.info(
            "genkit: %s rule=%s model=%s final=%s tier=%s level=%s (%s)",
            opportunity.external_id,
            rule,
            model_score,
            final,
            updates.get("severity_tier", opportunity.severity_tier),
            updates.get("level", opportunity.level),
            why[:60],
        )
    return assessment
