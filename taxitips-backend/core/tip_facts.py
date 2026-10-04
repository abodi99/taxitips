"""
Modellen läser fakta, reglerna sätter poängen.

Förut satte språkmodellen poängen själv för osäkra tips, och höjde ibland
mer än texten bar ("Inställd p.g.a. fordonsfel" 38 -> 85, 2026-10-04). Nu läser
den bara ut vad som står -- vad som hänt, färdsätt, stationer, klockslag,
försening, uttalat alternativ -- och `classify_from_facts` översätter det med
samma konstanter som fritextreglerna (core/text_scoring.py, core/scoring.py).
Varje tips går därmed att förklara: vilken fakta, vilken regel, vilken poäng.

Faktan sparas i RailAssessment.facts. En cachad bedömning räknas om från sin
fakta, så att en ändrad regel slår igenom utan ett enda nytt modellanrop.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field

from core.models import SeverityTier, TransportMode

EVENT_TYPES = (
    "whole_line_stop", "single_departure", "partial_route", "delay",
    "facility_or_stop_change", "planned_future", "resolved", "unclear",
)
ALTERNATIVES = ("replacement", "other_line", "next_departure", "none", "unknown")
MODES = frozenset(m for m in TransportMode.values if m not in ("", TransportMode.UNKNOWN, TransportMode.ROAD))

# En delsträcka eller en tur som vänder tidigare: resenärerna längre bort måste
# byta eller vänta, men linjen går. Mellan en enstaka avgång (20) och en oklar
# allvarlig störning (45).
PARTIAL_ROUTE_SCORE = 35
# "Försenad upp till 10 minuter" skapar ingen taxikund.
SHORT_DELAY_MIN = 10
SHORT_DELAY_SCORE = 10
# Ett glapp längre än så mellan två klockslag är ett lästfel, inte en väntan.
MAX_GAP_MIN = 12 * 60

_CLOCK_RE = re.compile(r"^\s*(\d{1,2})[:.](\d{2})\s*$")


class TipFacts(BaseModel):
    """Det modellen läser ut. Fält som texten inte nämner lämnas tomma."""

    event_type: str = Field(default="unclear", description=" | ".join(EVENT_TYPES))
    mode: str = Field(default="", description="train | metro | tram | bus | boat, eller tomt")
    line: str = ""
    train_no: str = ""
    from_station: str = ""
    to_station: str = ""
    departure_clock: str = Field(default="", description="HH:MM för den drabbade avgången, eller tomt")
    next_departure_clock: str = Field(default="", description="HH:MM för nästa avgång enligt texten, eller tomt")
    # Heltal, inte nullbart: med `int | None` svarade modellen null i 14 av 14
    # förseningar i facit (eval_ai 2026-10-04). 0 betyder att texten inte anger längden.
    delay_minutes: int = Field(default=0, description="förseningens längd i minuter, 0 om den inte anges")
    alternative: str = Field(default="unknown", description=" | ".join(ALTERNATIVES))
    cause: str = ""
    why: str = Field(default="", max_length=300, description="En mening på svenska: vad händer?")


FACTS_PROMPT = """Du läser ett störningsmeddelande från svensk kollektivtrafik åt TaxiTips,
en app för taxiförare. Läs ut FAKTA som står i texten. Gissa aldrig: nämner
texten inte något, lämna fältet tomt. Du sätter ingen poäng -- det gör reglerna.

## event_type -- välj exakt en
- whole_line_stop: hela linjen eller sträckan står still nu, ingen trafik
- single_departure: en eller några namngivna avgångar är inställda
- partial_route: avgången eller linjen går bara en del av sträckan (vänder tidigare, delsträcka inställd)
- delay: trafiken går men är försenad
- facility_or_stop_change: hiss, rulltrappa, toalett, eller en hållplats som är flyttad, indragen eller stängd medan trafiken går
- planned_future: planerat arbete eller avstängning som börjar en senare dag
- resolved: störningen är över, trafiken går som vanligt igen
- unclear: texten säger inte vad som händer

## alternative -- välj exakt en
- replacement: ersättningsbuss, ersättningstrafik eller ersättningstaxi är insatt
- other_line: resenärerna hänvisas till en annan namngiven linje
- next_departure: texten anger när nästa avgång går
- none: texten säger uttryckligen att inget alternativ finns ännu
- unknown: texten säger inget om alternativ

## Övriga fält
- mode: train, metro, tram, bus eller boat -- bara om det framgår, annars tomt
- line, train_no: linjenummer eller tågnummer om de står
- from_station, to_station: bara själva namnet ("Lund C"), aldrig ord som "Inställd"
- departure_clock: den drabbade avgångens klockslag (HH:MM), annars tomt
- next_departure_clock: nästa avgångs klockslag (HH:MM) om texten anger det, annars tomt
- delay_minutes: förseningens längd i minuter som heltal ("cirka 20 minuter" -> 20), annars 0
- cause: orsaken, kort
- why: en mening på svenska om vad som händer

## Meddelandet
Titel: {title}
Sammanfattning: {summary}
Färdsätt enligt reglerna: {mode}
Region: {region}
Platser: {places}
Alternativanteckning: {alternative_note}

## Rå källkontext
{context_block}
"""


@dataclass(frozen=True)
class FactsVerdict:
    tier: str
    score: int
    has_alternative: bool | None
    mode: str | None
    condition: str
    from_station: str
    to_station: str
    why: str


def _clock_minutes(value: str) -> int | None:
    match = _CLOCK_RE.match(value or "")
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def stated_gap(facts: TipFacts) -> int | None:
    """Minuter mellan den drabbade avgången och nästa, när texten anger båda."""
    departure = _clock_minutes(facts.departure_clock)
    following = _clock_minutes(facts.next_departure_clock)
    if departure is None or following is None:
        return None
    gap = following - departure
    if gap < 0:
        gap += 24 * 60  # 23:50 inställd, nästa 05:10
    return gap if 0 < gap <= MAX_GAP_MIN else None


def classify_from_facts(facts: TipFacts | dict, current_mode: str = "", current_score: int = 0) -> FactsVerdict:
    """Fakta -> nivå och poäng, med fritextreglernas egna konstanter."""
    from core.scoring import ALTERNATIVE_SOON_MIN, SERIOUS_DELAY_MIN, SERIOUS_DELAY_SCORE, gap_score
    from core.text_scoring import (
        BUS_DELAY_SCORE,
        RAIL_DELAY_SCORE,
        RAIL_LIKE_MODES,
        SINGLE_DEPARTURE_SCORE,
        STATED_ALTERNATIVE_SCORE,
        UNCLASSIFIED_CAP,
        WHOLE_LINE_STOP_SCORE,
    )

    f = facts if isinstance(facts, TipFacts) else TipFacts.model_validate(facts)
    event = f.event_type if f.event_type in EVENT_TYPES else "unclear"
    alternative = f.alternative if f.alternative in ALTERNATIVES else "unknown"
    stated_mode = f.mode if f.mode in MODES else None
    mode = stated_mode or current_mode or "unknown"
    has_alt = True if alternative in ("replacement", "other_line") else (False if alternative == "none" else None)

    def verdict(tier, score, condition, has_alternative=has_alt):
        return FactsVerdict(
            tier=tier, score=max(0, min(100, int(score))), has_alternative=has_alternative,
            mode=stated_mode, condition=condition,
            from_station=f.from_station, to_station=f.to_station, why=f.why,
        )

    if event in ("facility_or_stop_change", "planned_future", "resolved"):
        return verdict(SeverityTier.IGNORE, 0, event)

    if event == "delay":
        minutes = f.delay_minutes or None  # 0 = längden anges inte
        if minutes is not None and minutes >= SERIOUS_DELAY_MIN:
            return verdict(SeverityTier.LINE_DELAYED, SERIOUS_DELAY_SCORE, "serious_delay")
        if minutes is not None and minutes <= SHORT_DELAY_MIN:
            tier = SeverityTier.LINE_DELAYED if mode in RAIL_LIKE_MODES else SeverityTier.VEHICLE_DELAYED
            return verdict(tier, SHORT_DELAY_SCORE, "short_delay")
        if mode in RAIL_LIKE_MODES:
            return verdict(SeverityTier.LINE_DELAYED, RAIL_DELAY_SCORE, "delay")
        return verdict(SeverityTier.VEHICLE_DELAYED, BUS_DELAY_SCORE, "delay")

    if event in ("whole_line_stop", "single_departure", "partial_route"):
        if has_alt:
            return verdict(SeverityTier.VEHICLE_CANCELLED, STATED_ALTERNATIVE_SCORE, "stated_alternative")
        gap = stated_gap(f)
        if gap is not None:
            long_gap = gap > ALTERNATIVE_SOON_MIN
            return verdict(
                SeverityTier.LINE_PAUSED if long_gap else SeverityTier.VEHICLE_CANCELLED,
                gap_score(gap), "known_gap",
            )
        if event == "whole_line_stop":
            return verdict(SeverityTier.LINE_PAUSED, WHOLE_LINE_STOP_SCORE, "whole_line_stop")
        if event == "partial_route":
            return verdict(SeverityTier.VEHICLE_CANCELLED, PARTIAL_ROUTE_SCORE, "partial_route")
        return verdict(SeverityTier.VEHICLE_CANCELLED, SINGLE_DEPARTURE_SCORE, "single_departure")

    return verdict(
        SeverityTier.DISRUPTION_UNCLASSIFIED, min(current_score, UNCLASSIFIED_CAP), "unclear",
    )
