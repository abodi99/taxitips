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

from core.models import Confidence, Opportunity, RailAssessment, SeverityTier, SourceEvent

log = logging.getLogger(__name__)

ALLOWED_TIERS = frozenset(SeverityTier.values)

PROMPT = """Du är bedömare åt TaxiTips, en app för svenska taxiförare.
Frågan är: står resenärer kvar utan alternativ och behöver taxi -- och
hur stark är signalen (0–100)?

Regelverket gissade på fritext och satte confidence=low. Du får ALL
tillgänglig data och ska omklassa tipset. Du FÅR höja eller sänka poängen
och byta severity_tier när texten och signalerna motiverar det.

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

## severity_tier — välj EXAKT en
- line_paused: hela linjen/sträckan stoppad, ingen trafik
- vehicle_cancelled: en eller flera avgångar inställda
- line_delayed: försening på linjen
- vehicle_delayed: enstaka avgång försenad / "riskerar att bli försenad"
- disruption_unclassified: oklart, svag text
- road_accident_or_closure / road_work_or_queue / road_work: väghändelser
  (skapar sällan taxikunder — håll score lågt, typ under 20)

## Poängvägledning
- Ersättningsbuss / ersättningstrafik redan på plats → score under 30,
  has_alternative true.
- "Riskerar att bli försenad", ny tid, omväg, flyttad hållplats →
  vehicle_delayed eller disruption_unclassified, score under 40.
- Verkligt inställd avgång utan alternativ, rusning / knutpunkt →
  vehicle_cancelled, score 55–75.
- Hela linjen stoppad utan alternativ, sista avgången → line_paused,
  score 75–95.
- Vägarbete som stänger en hållplats men bussen går vidare → score under 25.

Svara ENDAST med JSON:
{{"score": <0-100>, "severity_tier": "<en av listan>", "stranded": <true|false>, "has_alternative": <true|false|null>, "why": "<kort motivering på svenska>"}}
"""


def normalize_key(opportunity: Opportunity) -> str:
    """
    Cachenyckel på normaliserad form.

    Titlar duger inte: tågtitlar bär tågnummer och klockslag och är
    därmed nästan unika (28 av 28 i en mätning). Nyckeln beskriver i
    stället störningens FORM -- två störningar med samma form har samma
    svar. Versionssuffix så gamla dampen-svar inte återanvänds efter
    omklassningsprompten.
    """
    title = (opportunity.title or "").lower()
    title = re.sub(r"\d+", "N", title)
    title = re.sub(r"\s+", " ", title).strip()[:60]
    hour = opportunity.start_time.hour if opportunity.start_time else 0
    bucket = "natt" if hour >= 22 or hour <= 5 else "dag"
    alt = "alt" if opportunity.has_alternative else "noalt"
    return f"v2|{opportunity.severity_tier}|{opportunity.mode}|{title}|{bucket}|{alt}"


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


def review(
    opportunity: Opportunity,
    call_model,
    *,
    reclassify: bool = True,
    bypass_cache: bool = False,
) -> RailAssessment | None:
    """
    Granskar ett tips. `call_model` tar en prompt och returnerar text.

    `reclassify=True` (default för confidence=low): modellens score och
    severity_tier får ersätta regelverkets. `reclassify=False`: bara sänka.
    """
    if not bypass_cache:
        cached = (
            RailAssessment.objects.filter(cache_key=normalize_key(opportunity))
            .order_by("-created_at")
            .first()
        )
        if cached:
            log.info("genkit: cacheträff för %s", opportunity.external_id)
            return _apply(
                opportunity,
                cached.model_score,
                cached.verdict,
                cached.model_name or "gemini-flash",
                reclassify=reclassify,
                severity_tier=None,
                has_alternative=None,
            )

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

    score, why, tier, has_alt = parsed
    return _apply(
        opportunity,
        score,
        why,
        "gemini-flash",
        reclassify=reclassify,
        severity_tier=tier,
        has_alternative=has_alt,
    )


def _parse(
    raw: str,
) -> tuple[int, str, str | None, bool | None] | None:
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
    return score_i, why, tier_out, has_alt


def _apply(
    opportunity: Opportunity,
    model_score: int,
    why: str,
    model_name: str,
    *,
    reclassify: bool,
    severity_tier: str | None,
    has_alternative: bool | None,
) -> RailAssessment:
    """
    Sparar bedömningen och uppdaterar tipset.

    Omklassning: final = model_score, ev. ny tier/has_alternative.
    Dämpning: final = min(rule, model), bara sänka.
    """
    rule = opportunity.demand_score
    if reclassify:
        final = int(max(0, min(100, model_score)))
    else:
        final = min(rule, model_score)

    assessment = RailAssessment(
        opportunity=opportunity,
        cache_key=normalize_key(opportunity),
        rule_score=rule,
        model_score=model_score,
        final_score=final,
        verdict=why,
        model_name=model_name,
    )
    assessment._allow_reclassify = reclassify  # type: ignore[attr-defined]
    assessment.save()

    updates: dict = {}
    if final != opportunity.demand_score:
        updates["demand_score"] = final
    if reclassify and severity_tier and severity_tier != opportunity.severity_tier:
        updates["severity_tier"] = severity_tier
    if reclassify and has_alternative is not None and (
        has_alternative != opportunity.has_alternative
    ):
        updates["has_alternative"] = has_alternative

    if updates or (reclassify and opportunity.confidence == Confidence.LOW):
        reasons = list(opportunity.reasons or [])
        if final < rule:
            reasons.append(f"AI sänkte: {why[:80]}" if why else "AI sänkte poängen")
        elif final > rule:
            reasons.append(f"AI höjde: {why[:80]}" if why else "AI höjde poängen")
        elif severity_tier and severity_tier != opportunity.severity_tier:
            reasons.append(
                f"AI omklassade till {severity_tier}: {why[:60]}"
                if why
                else f"AI omklassade till {severity_tier}"
            )
        updates["reasons"] = reasons
        updates["confidence"] = Confidence.MEDIUM
        # Höjde modellen tipset -- poäng, typ eller bort med alternativet -- får
        # höjningen synas i listan men aldrig ensam väcka en telefon.
        raised = (
            final > rule
            or "severity_tier" in updates
            or (updates.get("has_alternative") is False and opportunity.has_alternative)
        )
        if raised:
            from django.utils import timezone

            updates["ai_adjusted_at"] = timezone.now()
        Opportunity.objects.filter(pk=opportunity.pk).update(**updates)
        log.info(
            "genkit: %s rule=%s model=%s final=%s tier=%s (%s)",
            opportunity.external_id,
            rule,
            model_score,
            final,
            updates.get("severity_tier", opportunity.severity_tier),
            why[:60],
        )
    return assessment
