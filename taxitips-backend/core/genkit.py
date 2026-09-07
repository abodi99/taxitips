"""
Språkmodellsgranskning av osäkra bedömningar.

Var den gör nytta -- och var den inte gör det
---------------------------------------------
Efter Fas 2 har alla 24 tågtips `confidence: high`. Det är inte en
förbättring att jaga: de strukturella signalerna (nästa avgång, sista
tåget, ersättningstrafik) svarar på frågan direkt, och en språkmodell kan
inte tillföra något till "Trafikverket säger att bussen ersätter".

Osäkerheten sitter i buss- och spårvagnsflödena, där bedömningen görs på
fritext. Mätt live: 10 av 35 icke-tågtips har `confidence: low`, och bland
dem finns fall som

    85  "Hållplats Elektravägen inställd pga vägarbete"   -- ett vägarbete
    97  "Linje 4 klockan 22:59 är inställd från Angered"  -- rimlig
    35  "Ny avgångstid"                                    -- säger inget

Det är där en modell kan läsa meningen i stället för nyckelorden.

Fyra regler som gör det säkert
------------------------------
1. Får bara SÄNKA. `slutlig = min(regelpoäng, modellpoäng)`. Ett falskt
   högt tips kostar en förare en bomresa; ett falskt lågt kostar ingenting.
2. Cache på normaliserad form, inte titel. Tågtitlar är unika (28 av 28) --
   cache på titel ger noll träffar.
3. Fallerar anropet behålls regelsvaret. Blockerar aldrig en skrivning.
4. Körs bara på `confidence: low`. Resten är redan välgrundat.
"""

from __future__ import annotations

import json
import logging
import re

from core.models import Confidence, Opportunity, RailAssessment, SourceEvent

log = logging.getLogger(__name__)

PROMPT = """Du bedömer om en kollektivtrafikstörning i Sverige innebär att \
resenärer står kvar och behöver taxi.

Störning: {title}
Detaljer: {summary}
Regelverket gav: {score} av 100
{context_block}
Svara ENDAST med JSON:
{{"score": <0-100>, "stranded": <true|false>, "why": "<kort motivering på svenska>"}}

Vägledning:
- Ersättningsbuss, ersättningstrafik eller nästa avgång inom ~20 min → ingen \
är strandsatt, sätt score lågt (under 30).
- "Vi kör igen", "återinsatt", "trafiken återupptagen" → problemet är över, \
sätt score 0.
- Vägarbete, flyttad hållplats, ändrad körväg → påverkar resan men \
strandsätter ingen, sätt score lågt.
- Inställd sista avgång, stoppad linje utan alternativ → verkligt \
strandsatta, behåll högt.
Var konservativ: höj aldrig över regelverkets poäng."""


def normalize_key(opportunity: Opportunity) -> str:
    """
    Cachenyckel på normaliserad form.

    Titlar duger inte: tågtitlar bär tågnummer och klockslag och är
    därmed nästan unika (28 av 28 i en mätning). Nyckeln beskriver i
    stället störningens FORM -- två störningar med samma form har samma
    svar.
    """
    title = (opportunity.title or "").lower()
    title = re.sub(r"\d+", "N", title)  # tågnummer, klockslag, linjer
    title = re.sub(r"\s+", " ", title).strip()[:60]
    hour = opportunity.start_time.hour if opportunity.start_time else 0
    bucket = "natt" if hour >= 22 or hour <= 5 else "dag"
    return f"{opportunity.severity_tier}|{opportunity.mode}|{title}|{bucket}"


def _structural_context(opportunity: Opportunity) -> str:
    """
    Riktiga signaler utöver fritexten, när källan gav några: dess egen
    redaktionella allvarlighet (SL:s importance_level, Västtrafiks
    severity) och om Trafikverket redan bekräftat ersättningstrafik. En
    modell som ser detta bedömer på grundval av verklig data, inte bara
    en fri tolkning av samma text regelverket redan läste.

    Stärker bara PROMPT ovan -- lägger inte till ett nytt ställe Genkit
    anropas från, och rör inte review()/_apply()s skyddsräcke.
    """
    if not opportunity.source_event_ids:
        return ""
    se = SourceEvent.objects.filter(id=opportunity.source_event_ids[0]).first()
    if not se or not isinstance(se.raw, dict):
        return ""
    raw = se.raw
    lines = []
    sl = raw.get("sl") or {}
    if sl.get("importance_level") is not None:
        lines.append(f"- SL:s egen prioritet för meddelandet: {sl['importance_level']}/7.")
    vt = raw.get("vt") or {}
    if vt.get("severity"):
        lines.append(f"- Västtrafiks egen allvarlighetsbedömning: {vt['severity']}.")
    if raw.get("has_replacement"):
        mode = raw.get("replacement_mode") or "okänt fordon"
        lines.append(f"- Trafikverket har redan registrerat ersättningstrafik ({mode}).")
    if raw.get("route_label"):
        lines.append(f"- Linje: {raw['route_label']}.")
    return "\n".join(lines)


def review(opportunity: Opportunity, call_model) -> RailAssessment | None:
    """
    Granskar ett tips. `call_model` tar en prompt och returnerar text --
    injiceras så att testerna slipper nätverk, och så att Firebase/Genkit
    kan bytas mot vad som helst utan att den här logiken ändras.

    Returnerar None när inget behöver ändras.
    """
    cached = (
        RailAssessment.objects.filter(cache_key=normalize_key(opportunity))
        .order_by("-created_at")
        .first()
    )
    if cached:
        log.info("genkit: cacheträff för %s", opportunity.external_id)
        return _apply(opportunity, cached.model_score, cached.verdict, cached.model_name)

    context = _structural_context(opportunity)
    prompt = PROMPT.format(
        title=opportunity.title or "",
        summary=(opportunity.summary or "")[:400],
        score=opportunity.demand_score,
        context_block=f"Ytterligare kända signaler:\n{context}\n" if context else "",
    )
    try:
        raw = call_model(prompt)
        parsed = _parse(raw)
    except Exception as exc:
        # Regelsvaret står kvar. En trasig modell får aldrig stoppa
        # pipelinen eller ändra ett tips.
        log.warning("genkit: anrop misslyckades, behåller regelpoäng: %s", exc)
        return None

    if parsed is None:
        log.warning("genkit: kunde inte tolka svaret, behåller regelpoäng")
        return None

    score, why = parsed
    return _apply(opportunity, score, why, "gemini-flash")


def _parse(raw: str) -> tuple[int, str] | None:
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
    return int(max(0, min(100, score))), str(data.get("why") or "")[:300]


def _apply(
    opportunity: Opportunity, model_score: int, why: str, model_name: str
) -> RailAssessment:
    """
    Sparar bedömningen och sänker poängen om modellen vill det.

    RailAssessment.save() klämmer själv final_score till min(rule, model) --
    skyddsräcket ligger i modellen, inte bara här, så en framtida
    anropsväg inte kan kringgå det.
    """
    assessment = RailAssessment.objects.create(
        opportunity=opportunity,
        cache_key=normalize_key(opportunity),
        rule_score=opportunity.demand_score,
        model_score=model_score,
        final_score=min(opportunity.demand_score, model_score),
        verdict=why,
        model_name=model_name,
    )

    if assessment.final_score < opportunity.demand_score:
        reasons = list(opportunity.reasons or [])
        reasons.append(f"AI sänkte: {why[:80]}" if why else "AI sänkte poängen")
        # update() i stället för save(): rör bara de kolumner som ändras,
        # och lämnar notified_at ifred (se repository.py).
        Opportunity.objects.filter(pk=opportunity.pk).update(
            demand_score=assessment.final_score,
            reasons=reasons,
            confidence=Confidence.MEDIUM,
        )
        log.info(
            "genkit: %s %s -> %s (%s)",
            opportunity.external_id,
            assessment.rule_score,
            assessment.final_score,
            why[:60],
        )
    return assessment
