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
from dataclasses import dataclass, field

from core import taxi_context as tc
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
_NO_ALTERNATIVE_YET_RE = re.compile(
    r"(invänta info|inga ersättningsbuss|ingen ersättningsbuss|ingen ersättningstrafik|saknas ersättningsbuss)",
    re.IGNORECASE,
)
_WHOLE_LINE_STOP_RE = re.compile(
    r"(stopp i (trafiken|tågtrafiken|busstrafiken|spårvagnstrafiken)|ingen trafik|inga avgångar|trafikstopp|tågstopp|totalt stopp)",
    re.IGNORECASE,
)
# En ENSTAKA avgång, inte linjen: "Inställd avgång kl 20:40", "Hagsätra -
# Vällingby kl 16:59 är inställd", "Inställd delsträcka", "Resenärer hänvisas
# till nästa avgång". Mätt 2026-10-02: SL:s tunnelbane- och spårvagnslarm av
# den här sorten blev "Hela linjen stoppad" 85 och väckte förare, fast nästa
# tåg gick om några minuter.
#
# Ett namngivet tåg ("Vy Tåg 382 ... är inställt") är också en enstaka avgång,
# även när klockslaget saknar minuter ("klockan 19:är") eller följs av ett
# komma ("06:14, är inställt"). Mätt 2026-10-02: Vy Tågs strejkinställda tåg
# Göteborg–Halden blev "Hela linjen stoppad" 53 och 97.
_SINGLE_DEPARTURE_RE = re.compile(
    r"(inställd avgång|avgången (kl\.? ?)?\d{1,2}[:.]\d{2}|"
    r"(?<!från )kl\.? ?\d{1,2}[:.]\d{2}[^.]{0,60}inställ|\b\d{1,2}[:.]\d{2},? (är )?inställ|"
    r"\btåg(?: nr\.?)? ?\d{3,5}\b[^.]{0,90}inställ|"
    r"delsträcka|del av avgång|enstaka avgång|hänvisas till nästa avgång|nästa ordinarie avgång)",
    re.IGNORECASE,
)
# Hållplatser och anläggningar, inte trafik: "Stängd hållplats", "Hiss ur
# funktion", "hållplatsen flyttas 100 meter". Ingen står strandsatt av en
# stängd hiss eller en hållplats som flyttats för ett vägarbete -- bussen går.
# Mätt 2026-10-04: dussintals sådana, flera pågående i månader, låg i
# förarnas lista som "Övrigt" eller till och med som svaga tips.
FACILITY_NOTICE_RE = re.compile(
    r"(\bhiss|rulltrapp|\btrappa|\btrappan\b|toalett|biljettautomat|väntsal|informationsskärm|"
    r"hållplats\w*[^.]{0,80}(stängd|stängs|indrag|flytta|avstängd|trafikeras inte|tillfällig|inställd)|"
    r"(stannar|trafikerar) inte (vid|hållplats)|"
    r"(stängd|stängda|indragen|indragna|indraget|flyttad|flyttade|flyttat|flyttas|tillfällig|tillfälligt|"
    r"avstängd|avstängda|avstängt) hållplats|hållplatsläge)",
    re.IGNORECASE,
)


def is_facility_notice(text: str) -> bool:
    """Ett meddelande om en hållplats eller anläggning, inte om trafiken."""
    return bool(FACILITY_NOTICE_RE.search(text or ""))


# "7 oktober klockan 06:14": avgångens datum när det inte är i dag.
_MONTHS = (
    "januari", "februari", "mars", "april", "maj", "juni", "juli", "augusti",
    "september", "oktober", "november", "december",
)
_DATE_RE = re.compile(r"\b(\d{1,2})\s+(" + "|".join(_MONTHS) + r")\b", re.IGNORECASE)
# Tåget går, bara långsammare -- en försening, inget stopp.
_REDUCED_SPEED_RE = re.compile(
    r"(reducerad hastighet|nedsatt hastighet|hastighetsnedsättning|kör långsamt)", re.IGNORECASE
)
_CLOCK_RE = re.compile(r"(?:kl\.? ?)?\b(\d{1,2})[:.](\d{2})\b", re.IGNORECASE)

# Lägespoängen för fritext. Se core/taxi_context.py för hur omständigheterna
# läggs på, och docs/betygsmetod.md för varför.
WHOLE_LINE_STOP_SCORE = 70
SINGLE_DEPARTURE_SCORE = 20
STATED_ALTERNATIVE_SCORE = 25
AMBIGUOUS_SCORE = 45
BUS_LINE_CANCELLED_SCORE = 45
RAIL_DELAY_SCORE = 30
BUS_DELAY_SCORE = 15
UNCLASSIFIED_CAP = 30


@dataclass
class Assessment:
    tier: str
    score: int
    confidence: str
    reasons: list[str]
    rule_id: str
    mode: str
    stranded: bool = False
    quick_alternative: bool = False
    wait_minutes: int | None = None
    factors: list = field(default_factory=list)

    def situation(self) -> tc.Situation:
        return tc.Situation(
            base=self.score, stranded=self.stranded, confidence=self.confidence,
            quick_alternative=self.quick_alternative, wait_minutes=self.wait_minutes,
            factors=list(self.factors),
        )


def _has_stated_alternative(text: str) -> bool:
    if _NO_ALTERNATIVE_YET_RE.search(text):
        return False
    return bool(_STATED_ALTERNATIVE_RE.search(text))


def _is_whole_line_stop(text: str) -> bool:
    return bool(_WHOLE_LINE_STOP_RE.search(text))


def is_single_departure(text: str) -> bool:
    return bool(_SINGLE_DEPARTURE_RE.search(text))


def departure_clock(text: str) -> tuple[int, int] | None:
    """Första klockslaget i texten ("kl 20:40" -> (20, 40)), eller None."""
    for match in _CLOCK_RE.finditer(text or ""):
        hour, minute = int(match.group(1)), int(match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    return None


def departure_date(text: str, today):
    """
    Datumet i texten ("7 oktober" -> date), eller None. Året är i år, eller
    nästa år när datumet redan passerat med mer än ett halvår -- ett larm i
    december om "3 januari" gäller januari som kommer.
    """
    import datetime as _dt

    match = _DATE_RE.search(text or "")
    if not match:
        return None
    day, month = int(match.group(1)), _MONTHS.index(match.group(2).lower()) + 1
    for year in (today.year, today.year + 1):
        try:
            candidate = _dt.date(year, month, day)
        except ValueError:
            return None
        if (candidate - today).days > -183:
            return candidate
    return None


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



def _rated(
    tier: str, score: int, confidence: str, mode: str, condition: str, reasons: list[str],
    *, stranded: bool = False, quick: bool = False, wait: int | None = None,
    factors: list | None = None,
) -> Assessment:
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
    return Assessment(
        tier, score, confidence, reasons, rule_id, mode,
        stranded=stranded, quick_alternative=quick, wait_minutes=wait,
        factors=factors or [],
    )


def classify_transit_alert(alert: dict, taxi: dict | None) -> Assessment:
    """
    Fritextlarm -> LÄGET: tier, lägespoäng, säkerhet, strandsättning och skäl.

    Ordningen är frågan "står någon strandsatt?":

      1. Alternativ angivet i texten             -> 25, inte strandsatt
      2. Känd nästa avgång (SL)                  -> tågens glappskala
      3. Hela linjen stoppad (och inte enstaka)  -> 70, strandsatt
      4. Enstaka avgång inställd                 -> 20, inte strandsatt
      5. Långsam trafik                          -> försening
      6. Allvarligt men oklart                   -> 45, inte strandsatt
      7. Försening                               -> 30 spårtrafik / 15 buss

    Omständigheterna (tid, väder, ersättning) läggs på i core/ingest.py.
    """
    from core.scoring import ALTERNATIVE_SOON_MIN, QUICK_ALTERNATIVE_MIN, gap_score

    mode = classify_mode(alert)

    if not taxi or taxi.get("level") == "ignore":
        reasons = _reasons_from(taxi) if taxi else []
        return Assessment(SeverityTier.IGNORE, 0, Confidence.MEDIUM, reasons, f"{mode}.ignore", mode)

    if mode != "road":
        notice_text = f"{alert.get('header') or ''} {alert.get('description') or ''}"
        if is_facility_notice(notice_text) and not (
            _is_whole_line_stop(notice_text) or is_single_departure(notice_text)
        ):
            return Assessment(
                SeverityTier.IGNORE, 0, Confidence.MEDIUM,
                ["hållplats eller anläggning – inte en körning"], f"{mode}.ignore.facility", mode,
            )

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
    rail_like = mode in RAIL_LIKE_MODES
    single = is_single_departure(text)
    gap = alert.get("next_departure_minutes")

    if serious and _has_stated_alternative(text):
        return _rated(
            SeverityTier.VEHICLE_CANCELLED, STATED_ALTERNATIVE_SCORE, Confidence.MEDIUM,
            mode=mode, condition="stated_alternative", reasons=reasons,
            quick=True, factors=[tc.STATED_ALTERNATIVE],
        )

    if serious and gap is not None:
        # SL har svarat på när nästa avgång på samma linje går härifrån
        # (sl.enrich_next_departures) -- samma signal som tågen har.
        reasons = [*reasons, f"nästa avgång {gap} min senare"]
        long_gap = gap > ALTERNATIVE_SOON_MIN
        return _rated(
            SeverityTier.LINE_PAUSED if long_gap else SeverityTier.VEHICLE_CANCELLED,
            gap_score(gap), Confidence.HIGH, mode=mode, condition="known_gap",
            reasons=reasons, stranded=long_gap, quick=gap <= QUICK_ALTERNATIVE_MIN,
            wait=gap, factors=[tc.wait_factor(gap, "Nästa avgång")],
        )

    if serious and _is_whole_line_stop(text) and not single:
        return _rated(
            SeverityTier.LINE_PAUSED, WHOLE_LINE_STOP_SCORE, Confidence.HIGH,
            mode=mode, condition="whole_line_stop", reasons=reasons,
            stranded=True, factors=[tc.WHOLE_LINE_STOPPED],
        )

    if serious and single:
        confidence = Confidence.HIGH if _INSTALLD_STOPP_RE.search(text) else Confidence.LOW
        return _rated(
            SeverityTier.VEHICLE_CANCELLED, SINGLE_DEPARTURE_SCORE, confidence,
            mode=mode, condition="single_departure", reasons=reasons,
            factors=[tc.SINGLE_DEPARTURE],
        )

    if _REDUCED_SPEED_RE.search(text) and not _is_whole_line_stop(text):
        serious, mediumish = False, True

    if serious:
        if rail_like:
            # Allvarligt ordval, men varken "hela linjen" eller "en avgång"
            # står i klartext. Kan vara ett stopp, kan vara en enstaka tur.
            # Högst Medel tills AI-granskningen eller en förare bekräftat det.
            return _rated(
                SeverityTier.LINE_PAUSED, AMBIGUOUS_SCORE,
                _editorial_confidence(alert, Confidence.LOW, Confidence.MEDIUM),
                mode=mode, condition="ambiguous", reasons=reasons,
                factors=[tc.UNCERTAIN],
            )
        if mode == "bus":
            # "Buss linje 39 är inställd" utan klockslag: linjen eller en tur?
            # Uttryckligt "inställd" = hög säkerhet om att något är inställt,
            # men inte att någon står strandsatt.
            confidence = Confidence.HIGH if _INSTALLD_STOPP_RE.search(text) else Confidence.LOW
            return _rated(
                SeverityTier.VEHICLE_CANCELLED, BUS_LINE_CANCELLED_SCORE, confidence,
                mode=mode, condition="serious", reasons=reasons,
                factors=[tc.UNCERTAIN],
            )

    if mediumish and rail_like:
        return _rated(
            SeverityTier.LINE_DELAYED, RAIL_DELAY_SCORE, Confidence.HIGH,
            mode=mode, condition="mediumish", reasons=reasons,
            factors=[tc.Factor("Förseningar i trafiken", "-", 10)],
        )
    if mediumish and mode == "bus":
        return _rated(
            SeverityTier.VEHICLE_DELAYED, BUS_DELAY_SCORE, Confidence.HIGH,
            mode=mode, condition="mediumish", reasons=reasons,
            factors=[tc.Factor("Bussen är försenad", "-", 10)],
        )

    # mode == "unknown", eller en form som matchade varken serious eller
    # mediumish. Ärligt: vi vet inte vad det är, så det får inte se starkt ut.
    return Assessment(
        SeverityTier.DISRUPTION_UNCLASSIFIED, min(score, UNCLASSIFIED_CAP), Confidence.LOW,
        reasons, f"{mode}.unclassified", mode, factors=[tc.UNCERTAIN],
    )
