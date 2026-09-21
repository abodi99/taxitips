"""
Mode-medveten allvarlighetsgradering av textbaserade transitlarm
(Trafiklab idag; SL/Västtrafik ansluter i senare faser utan att röra den
här filen).

Port av worker/src/scoring.js:s classifySeverity. Till skillnad från
core/scoring.py (järnvägens strukturella klassificerare, som har riktiga
signaler som "nästa avgång om X min") är den här klassificeraren textbaserad
-- den återanvänder score_alert()'s serious/mediumish-signaler i stället för
att räkna om dem.

De hårdkodade taken/golven nedan är EXAKT scoring.js:s tal (85/70/55/60/45/
25) -- det är fallbacken när ScoringRule-tabellen är tom, precis som i
core/scoring.py. seed_rules.py har redan seedat motsvarande rader (verifierat
rad för rad mot scoring.js), så DB-regeln vinner i praktiken, men koden får
inte lita blint på en tabell som kan vara tom.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from core import thresholds
from core.mode import classify_mode
from core.models import Confidence, SeverityTier
from core.rules import rule_for
from core.taxi_relevance import _INSTALLD_STOPP_RE

RAIL_LIKE_MODES = {"train", "metro", "tram"}

# "E6", "E 22", "Väg 40", "40". Trafikverkets RoadNumber har båda formerna.
_ROAD_NUMBER_RE = re.compile(r"^(?:E\s*(\d+)|(?:väg\s*)?(\d+))$", re.IGNORECASE)
# Kö som eget ord: "kö" finns också i början av "Körfältsavstängningar", och
# det var just den förväxlingen som gjorde 546 körfältsavstängningar till köer.
_QUEUE_RE = re.compile(r"(?<!\w)kö(?!\w)|kövarning|köbildning", re.IGNORECASE)


def is_main_road(routes) -> bool:
    """E-väg, riksväg eller primär länsväg (se thresholds.ROAD_MAIN_ROAD_MAX_NUMBER)."""
    for route in routes or []:
        match = _ROAD_NUMBER_RE.match(str(route).strip())
        if not match:
            continue
        if match.group(1) or int(match.group(2)) <= thresholds.ROAD_MAIN_ROAD_MAX_NUMBER:
            return True
    return False


def road_tier(alert: dict) -> tuple[str, str]:
    """
    (nivå, villkor) för en väghändelse -- och därmed om föraren ser den.

    Villkoret hamnar i rule_id (road.<nivå>.<villkor>) och avgör om föraren
    ser händelsen (thresholds.ROAD_SHOWN_CONDITIONS -- bara `accident`).
    Resten klassas ändå, så att det går att svara på varför den inte visas.

    Trafikverkets MessageCode (`cause`) avgör typen och SeverityText
    (`effect`) hur mycket den påverkar. Körfältsavstängningar är ingen
    avstängd väg: tidigare räckte "avstäng" i texten, och 546 planerade
    körfältsavstängningar -- en av dem 154 dagar gammal -- visades som röda
    "Stopp" överst i listan.
    """
    cause = str(alert.get("cause") or "").strip().lower()
    text = " ".join(
        str(alert.get(k) or "") for k in ("header", "description", "cause")
    ).lower()
    effect = str(alert.get("effect") or "").lower()

    # Brand i fordon är en trafikolycka; "Omfattande brand" (skog, byggnad)
    # nära vägen är det inte.
    if "olycka" in text or cause == "brand i fordon":
        return SeverityTier.ROAD_ACCIDENT_OR_CLOSURE, "accident"
    lane_only = "körfält" in cause
    if (
        "vägen avstängd" in text
        or "helt avstängd" in text
        or (not lane_only and ("avstäng" in cause or "avstangning" in cause))
    ):
        return SeverityTier.ROAD_ACCIDENT_OR_CLOSURE, "closed"
    # Bara typ och rubrik: "Risk för kö" står i beskrivningen på vanliga
    # vägarbeten och hade släppt igenom dem.
    if _QUEUE_RE.search(f"{alert.get('header') or ''} {cause}"):
        return SeverityTier.ROAD_WORK_OR_QUEUE, "queue"
    main = is_main_road(alert.get("routes"))
    if main and cause in thresholds.ROAD_HAZARD_CAUSES:
        return SeverityTier.ROAD_WORK_OR_QUEUE, "hazard_main_road"
    if main and "mycket stor" in effect:
        return SeverityTier.ROAD_WORK_OR_QUEUE, "major_main_road"
    return SeverityTier.ROAD_WORK, "minor"

_STATED_ALTERNATIVE_RE = re.compile(
    r"(övriga avgångar|ersättningsbuss|ersättningstrafik|buss ersätter|tågbyte)",
    re.IGNORECASE,
)
_WHOLE_LINE_STOP_RE = re.compile(
    r"(stopp i tågtrafiken|ingen trafik|inga avgångar|trafikstopp)", re.IGNORECASE
)


@dataclass
class Assessment:
    tier: str
    score: int
    confidence: str
    reasons: list[str]
    rule_id: str
    mode: str


def _has_stated_alternative(text: str) -> bool:
    return bool(_STATED_ALTERNATIVE_RE.search(text))


def _is_whole_line_stop(text: str) -> bool:
    return bool(_WHOLE_LINE_STOP_RE.search(text))


def _reasons_from(taxi: dict) -> list[str]:
    why = taxi.get("why") or ""
    return [r.strip() for r in why.split(",") if r.strip()]


def _editorial_confidence(alert: dict, low: str, high: str) -> str:
    """
    En källas EGEN redaktionella allvarlighet -- SL:s importance_level,
    Västtrafiks severity -- höjer konfidens när den är hög. Den avgör
    ALDRIG tier eller poäng: SL/VT:s prioritet mäter hur angeläget
    OPERATÖREN tycker meddelandet är, inte om hela linjen stod still. Det
    är därför den bara får flytta konfidens, aldrig mer.

    Trafiklab-larm saknar båda fälten helt (ingen sl/vt-nyckel alls), så
    de faller alltid tillbaka på `low` -- oförändrat beteende för dem.
    """
    sl = alert.get("sl") or {}
    vt = alert.get("vt") or {}
    if float(sl.get("importance_level") or 0) >= 7:
        return high
    if str(vt.get("severity") or "").lower() in ("high", "veryhigh"):
        return high
    return low



def _rated(tier: str, score: int, confidence: str, mode: str, condition: str, reasons: list[str]) -> Assessment:
    # rule_for's own mode__in=[mode, ""] lookup already falls back to a
    # blanket (mode="") rule when no mode-specific one exists -- so passing
    # the REAL detected mode here (not "") still finds e.g. seed_rules'
    # LINE_PAUSED/mode=""/"whole_line_stop" row correctly, while also
    # keeping the actual mode available for rule_id and the Assessment
    # itself (needed for opportunities.mode -- unlike rail, which is
    # always "train" by construction, this classifier spans several modes).
    rule = rule_for(tier, mode, condition)
    score = rule.apply(score) if rule else max(0, min(100, score))
    rule_id = f"{mode}.{tier}.{condition}" if condition else f"{mode}.{tier}"
    return Assessment(tier, score, confidence, reasons, rule_id, mode)


def classify_transit_alert(alert: dict, taxi: dict | None) -> Assessment:
    """
    RailAlert-motsvarighet för textbaserade transitlarm: alert + taxi
    (score_alert()'s resultat, EFTER alert_in_market()-grinden) -> tier,
    poäng, konfidens, motivering, färdsätt.
    """
    mode = classify_mode(alert)

    if not taxi or taxi.get("level") == "ignore":
        reasons = _reasons_from(taxi) if taxi else []
        return Assessment(SeverityTier.IGNORE, 0, Confidence.MEDIUM, reasons, f"{mode}.ignore", mode)

    if mode == "road":
        # Bara etikett, ingen ompoängsättning: score_road_alert har redan
        # kapat vägpoängen lågt (max 15) av skäl som står i dess docstring,
        # och tiern får inte smyga tillbaka in poäng som medvetet togs bort.
        tier, condition = road_tier(alert)
        return Assessment(
            tier, taxi.get("score", 0), Confidence.MEDIUM,
            _reasons_from(taxi), f"road.{tier}.{condition}", mode,
        )

    score = taxi.get("score", 0)
    serious = taxi.get("serious") is True
    mediumish = taxi.get("mediumish") is True
    text = f"{alert.get('header') or ''} {alert.get('description') or ''}"
    reasons = _reasons_from(taxi)

    if mode in RAIL_LIKE_MODES:
        if serious:
            if _is_whole_line_stop(text) and not _has_stated_alternative(text):
                return _rated(
                    SeverityTier.LINE_PAUSED, max(score, 85), Confidence.HIGH,
                    mode=mode, condition="whole_line_stop", reasons=reasons,
                )
            if _has_stated_alternative(text):
                return _rated(
                    SeverityTier.VEHICLE_CANCELLED, min(score, 55), Confidence.MEDIUM,
                    mode=mode, condition="stated_alternative", reasons=reasons,
                )
            # Allvarligt ordval, men inget av signalerna är entydigt i
            # texten -- kan inte säkert avgöra helt stopp vs enstaka
            # inställd. Källans egen redaktionella allvarlighet (SL:s
            # importance_level, Västtrafiks severity) höjer konfidens men
            # lämnar poängen orörd -- se _editorial_confidence().
            return _rated(
                SeverityTier.LINE_PAUSED, max(score, 70),
                _editorial_confidence(alert, Confidence.LOW, Confidence.MEDIUM),
                mode=mode, condition="ambiguous", reasons=reasons,
            )
        if mediumish:
            return _rated(
                SeverityTier.LINE_DELAYED, min(score, 45), Confidence.HIGH,
                mode=mode, condition="mediumish", reasons=reasons,
            )

    if mode == "bus":
        if serious:
            # Högst insats av alla textbaserade grenar (tak 60) men, innan
            # den här ändringen, alltid Confidence.HIGH oavsett VILKET ord
            # som gjorde den "serious" -- exakt den blinda tilliten till
            # nyckelord den här ändringen finns för att rätta till. Ett
            # uttryckligt "inställd/ställs in/inga avgångar/ingen trafik"
            # är en entydig utsago -- håll HIGH. "Serious" bara via den
            # bredare SERIOUS_RE-vokabulären (strejk, nedrivning,
            # signalproblem, stora störningar, m.fl., utan att någonstans
            # säga att något är inställt) är en svagare grund -- LOW, så
            # den faktiskt granskas i stället för att tystlåtet lita på.
            confidence = Confidence.HIGH if _INSTALLD_STOPP_RE.search(text) else Confidence.LOW
            return _rated(
                SeverityTier.VEHICLE_CANCELLED, min(score, 60), confidence,
                mode=mode, condition="serious", reasons=reasons,
            )
        if mediumish:
            return _rated(
                SeverityTier.VEHICLE_DELAYED, min(score, 25), Confidence.HIGH,
                mode=mode, condition="mediumish", reasons=reasons,
            )

    # mode == "unknown", eller en form som matchade varken serious eller
    # mediumish (ska normalt inte nås eftersom score_alert redan skulle ha
    # returnerat "ignore" -- men faller ärligt tillbaka hellre än att
    # feltolka).
    return Assessment(SeverityTier.DISRUPTION_UNCLASSIFIED, score, Confidence.LOW, reasons, f"{mode}.unclassified", mode)
