"""
Klassificering och poängsättning av järnvägsstörningar: LÄGET.

Frågan här är bara en: hur strandsatta är resenärerna? Svaret är en
lägespoäng, en strandsättningsflagga och lägets skäl i klartext. Tid på
dygnet, ersättningsrätt, väder och stationens storlek läggs på efteråt av
core/taxi_context.py -- de gör en strandsatt resenär mer eller mindre benägen
att ta taxi, men de skapar inget läge.

Historik: Node gav varje inställt tåg 85-97 poäng oavsett om nästa tåg gick
om tio minuter. Första Django-versionen skilde på glappet men gav "nästa tåg
inom 30 min" 55 + stationsbonus 6 = 61, alltså Stark och push (mätt
2026-10-02: 1 415 Starka och 215 notiser på en vecka, hälften med nästa tåg
inom tio minuter). Skalan nedan följer glappet hela vägen.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core import taxi_context as tc
from core.models import Confidence, SeverityTier, TransportMode
from core.rules import rule_for
from core.sources.trafikverket_rail import RailAlert

# Glapp till nästa resa (minuter) -> lägespoäng. Upp till 30 minuter står
# ingen strandsatt: de väntar. Över 30 är de strandsatta, men först från en
# timme räcker läget ensamt till Stark -- däremellan avgör omständigheterna.
ALTERNATIVE_SOON_MIN = 30
QUICK_ALTERNATIVE_MIN = 10
GAP_LADDER = (
    (10, 15),
    (20, 28),
    (30, 40),
    (59, 50),
)
LONG_GAP_SCORE = 68
LAST_DEPARTURE_SCORE = 80
REPLACEMENT_SCORE = 30
UNKNOWN_SCORE = 50

# Försening. En timme sent är i praktiken en inställd avgång med en timmes glapp.
SERIOUS_DELAY_MIN = 60
SERIOUS_DELAY_SCORE = 55
DELAY_SCORE = 40

# Stora stationer: många på samma perrong. Påslaget görs i taxi_context
# (BUSY_STATION_BONUS); här bestäms bara vad "stor" är.
BUSY_STATION_DEPARTURES = 20


@dataclass
class Assessment:
    tier: str
    score: int
    confidence: str
    reasons: list[str]
    rule_id: str
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


def gap_score(minutes: int) -> int:
    """Lägespoängen för ett glapp. Delas med fritextens kända nästa avgång (SL)."""
    for limit, score in GAP_LADDER:
        if minutes <= limit:
            return score
    return LONG_GAP_SCORE


def _next_text(alert: RailAlert) -> str:
    """"nästa resa mot X" när ResRobot svarat, annars "nästa avgång" från stationen."""
    if alert.alternative_basis == "resrobot":
        return f"nästa resa mot {alert.destination}" if alert.destination else "nästa resa"
    return "nästa avgång"


def _gap_text(alert: RailAlert) -> str:
    """
    Glappet efter den inställda avgången, som ett mått som inte åldras:
    "10 min efter den inställda". Aldrig "om 10 min" -- motiveringen sparas
    och läses långt efter att den skrevs.
    """
    return f"{alert.next_departure_minutes} min efter den inställda avgången"


def is_busy_station(alert: RailAlert) -> bool:
    return alert.station_departures_in_window >= BUSY_STATION_DEPARTURES


def classify(alert: RailAlert) -> Assessment:
    """
    RailAlert -> läge: tier, lägespoäng, säkerhet, strandsättning och skäl.

      1. Ersättningstrafik insatt           -> 30, inte strandsatt
      2. Inställt, nästa resa inom 30 min   -> 15-40, inte strandsatt
      3. Sista avgången                     -> 80, strandsatt
      4. Inställt, nästa resa om 31+ min    -> 50-68, strandsatt
      5. Inställt, okänt när nästa går      -> 50, strandsatt men osäkert
      6. Försenat                           -> 40, eller 55 och strandsatt från 60 min
    """
    reasons: list[str] = []

    if not alert.cancelled:
        reasons.append(f"försenat {alert.delay_minutes} min")
        serious = alert.delay_minutes >= SERIOUS_DELAY_MIN
        return _finish(
            SeverityTier.LINE_DELAYED, SERIOUS_DELAY_SCORE if serious else DELAY_SCORE,
            Confidence.HIGH, reasons, alert, "train.line_delayed",
            stranded=serious, wait=alert.delay_minutes,
            factors=[tc.delay_factor(alert.delay_minutes)],
        )

    reasons.append("inställd avgång")

    # Operatören säger själv att ersättningstrafik är insatt: resenärerna tas
    # om hand. Mätt: 35 av 59 inställda avgångar har det.
    if alert.has_replacement:
        reasons.append(alert.replacement_note.lower() or "ersättningstrafik insatt")
        return _finish(
            SeverityTier.VEHICLE_CANCELLED, REPLACEMENT_SCORE, Confidence.HIGH,
            reasons, alert, "train.vehicle_cancelled.replacement",
            quick=True, factors=[tc.REPLACEMENT],
        )

    gap = alert.next_departure_minutes
    what = "Nästa resa" if alert.alternative_basis == "resrobot" else "Nästa tåg"
    if gap is not None and gap <= ALTERNATIVE_SOON_MIN:
        reasons.append(f"{_next_text(alert)} {_gap_text(alert)}")
        return _finish(
            SeverityTier.VEHICLE_CANCELLED, gap_score(gap), Confidence.HIGH,
            reasons, alert, "train.vehicle_cancelled.alternative_soon",
            quick=gap <= QUICK_ALTERNATIVE_MIN, wait=gap,
            factors=[tc.wait_factor(gap, what)],
        )

    if alert.is_last_departure:
        reasons.append("sista avgången härifrån")
        return _finish(
            SeverityTier.LINE_PAUSED, LAST_DEPARTURE_SCORE, Confidence.HIGH,
            reasons, alert, "train.line_paused.last_departure",
            stranded=True, factors=[tc.LAST_DEPARTURE],
        )

    if gap is not None:
        reasons.append(f"{_next_text(alert)} {_gap_text(alert)}")
        return _finish(
            SeverityTier.LINE_PAUSED, gap_score(gap), Confidence.HIGH,
            reasons, alert, "train.line_paused.long_gap",
            stranded=True, wait=gap, factors=[tc.wait_factor(gap, what)],
        )

    reasons.append("okänt om ersättning finns")
    return _finish(
        SeverityTier.LINE_PAUSED, UNKNOWN_SCORE, Confidence.LOW,
        reasons, alert, "train.line_paused.unknown",
        stranded=True, factors=[tc.UNKNOWN_NEXT],
    )


def _finish(
    tier: str, score: int, confidence: str,
    reasons: list[str], alert: RailAlert, rule_id: str,
    *, stranded: bool = False, quick: bool = False, wait: int | None = None,
    factors: list | None = None,
) -> Assessment:
    """Applicerar eventuell ScoringRule från databasen och skriver stationsraderna."""
    # Regeln måste matcha grenen, inte bara nivån -- se rules.rule_for.
    condition = rule_id.rsplit(".", 1)[-1] if "." in rule_id else ""
    rule = rule_for(tier, TransportMode.TRAIN, condition)
    score = rule.apply(score) if rule else max(0, min(100, score))

    if is_busy_station(alert):
        reasons.append(f"stor station ({alert.station_departures_in_window} avgångar)")
    if alert.station:
        reasons.append(f"station: {alert.station}")
    brand = alert.information_owner or alert.operator
    if brand:
        reasons.append(f"operatör: {brand}")
    return Assessment(
        tier, score, confidence, reasons, rule_id,
        stranded=stranded, quick_alternative=quick, wait_minutes=wait,
        factors=factors or [],
    )


def taxi_outcome(alert: RailAlert, assessment: Assessment, region_weather: list[dict] | None = None):
    """
    Läget plus omständigheterna för ett tåg -> (ersättning, taxi_context.Outcome).

    Omständigheterna räknas mot den inställda avgångens tid, inte mot när
    pollningen råkade gå: ett tips om 07:55-tåget är ett morgontips även om
    det syntes redan 06:25.
    """
    from core.compensation import rail_compensation_signal
    from core.sources.smhi import nearest_weather

    has_alternative = alert.has_replacement or alert.next_departure_is_bus
    compensation = rail_compensation_signal(
        product=alert.product, lat=alert.lat, lon=alert.lon,
        cancelled=alert.cancelled, wait_minutes=assessment.wait_minutes,
        is_last_departure=alert.is_last_departure, has_replacement=alert.has_replacement,
    )
    outcome = tc.assess(
        assessment.situation(),
        when=alert.departure_at,
        weather=nearest_weather(alert.lat, alert.lon, region_weather or []),
        compensation=compensation,
        busy_station=is_busy_station(alert),
        has_alternative=has_alternative,
    )
    return compensation, outcome
