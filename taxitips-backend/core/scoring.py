"""
Klassificering och poängsättning av järnvägsstörningar.

Problemet detta löser
---------------------
Mätt mot live-data: 27 av 27 aktiva tågtips hade poäng 97, tier
line_paused, confidence low. Bevisat i Node-koden att två helt olika
situationer fick samma svar:

    Ingen ersättning (verkligt strandsatt)   -> line_paused  85  low
    Nästa tåg om 10 min (ingen strandsatt)   -> line_paused  85  low

Orsaken: scoring.js har redan en vehicle_cancelled-nivå med tak 55 byggd
för "inställd men alternativ finns" -- men tågen når den aldrig, eftersom
hasStatedAlternative() letar efter fraser ("övriga avgångar",
"ersättningsbuss") som Trafikverkets normalisering aldrig skriver. Alla
faller i grenen "allvarligt ordval, men otydligt".

Lösningen är inte fler regexar utan de strukturella signaler Trafikverket
redan ger och Node kastar bort: finns nästa avgång, är detta sista tåget,
hur stor är stationen.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.models import Confidence, SeverityTier, TransportMode
from core.rules import rule_for
from core.sources.trafikverket_rail import RailAlert

# En ersättare inom det här fönstret betyder att ingen är strandsatt.
ALTERNATIVE_SOON_MIN = 30

# Stora stationer ger fler resenärer per inställd avgång. Bonusen är
# medvetet liten -- den rangordnar mellan lika starka tips, den skapar
# inte ett tips.
BUSY_STATION_DEPARTURES = 20
BUSY_STATION_BONUS = 6

# Fallback-tak, speglar scoring.js. ScoringRule i databasen är sanningen,
# men de här gäller när tabellen är tom.
DEFAULT_CAPS = {
    SeverityTier.LINE_DELAYED: 45,
    SeverityTier.VEHICLE_DELAYED: 25,
    SeverityTier.IGNORE: 0,
}


@dataclass
class Assessment:
    tier: str
    score: int
    confidence: str
    reasons: list[str]
    rule_id: str


def _next_text(alert: RailAlert) -> str:
    """"nästa resa mot X" när ResRobot svarat, annars "nästa avgång" från stationen."""
    if alert.alternative_basis == "resrobot":
        return f"nästa resa mot {alert.destination}" if alert.destination else "nästa resa"
    return "nästa avgång"


def classify(alert: RailAlert) -> Assessment:
    """
    RailAlert -> tier, poäng, konfidens och motivering.

    Rangordningen bygger på vad som faktiskt strandsätter folk:

      1. Sista tåget, ingen ersättare      -> line_paused, golv 85, hög
      2. Inställt, ingen ersättare i sikte -> line_paused, golv 70, medel
      3. Inställt, ersättare inom 30 min   -> vehicle_cancelled, tak 55
      4. Kraftig försening                 -> line_delayed, tak 45
    """
    reasons: list[str] = []

    if not alert.cancelled:
        reasons.append(f"försenat {alert.delay_minutes} min")
        return _finish(
            SeverityTier.LINE_DELAYED, alert.delay_minutes + 20,
            Confidence.HIGH, reasons, alert, "train.line_delayed",
        )

    reasons.append("inställd avgång")

    # Starkaste signalen, och den kommer från operatören själv: är
    # ersättningstrafik insatt tas resenärerna om hand. De står inte och
    # väntar på taxi. Mätt: 35 av 59 inställda avgångar har detta -- utan
    # kontrollen blir de den vanligaste falska högnoteringen i flödet.
    if alert.has_replacement:
        reasons.append(alert.replacement_note.lower() or "ersättningstrafik insatt")
        return _finish(
            SeverityTier.VEHICLE_CANCELLED, 40, Confidence.HIGH,
            reasons, alert, "train.vehicle_cancelled.replacement",
        )

    soon = (
        alert.next_departure_minutes is not None
        and alert.next_departure_minutes <= ALTERNATIVE_SOON_MIN
    )

    if soon:
        # Det HÄR är fallet som saknades. Resenärerna väntar en kvart --
        # de tar inte taxi. Ett tips här är inte fel, men det ska inte
        # konkurrera med en verkligt strandsatt perrong.
        reasons.append(f"{_next_text(alert)} om {alert.next_departure_minutes} min")
        return _finish(
            SeverityTier.VEHICLE_CANCELLED, 55, Confidence.HIGH,
            reasons, alert, "train.vehicle_cancelled.alternative_soon",
        )

    if alert.is_last_departure:
        reasons.append("sista avgången härifrån")
        return _finish(
            SeverityTier.LINE_PAUSED, 85, Confidence.HIGH,
            reasons, alert, "train.line_paused.last_departure",
        )

    if alert.next_departure_minutes is not None:
        reasons.append(f"{_next_text(alert)} först om {alert.next_departure_minutes} min")
        return _finish(
            SeverityTier.LINE_PAUSED, 78, Confidence.HIGH,
            reasons, alert, "train.line_paused.long_gap",
        )

    # Ingen information om nästa avgång. Behåll Node-beteendet -- golv 70,
    # låg konfidens -- men nu är det ett litet undantag i stället för
    # regeln som alla tips föll i.
    reasons.append("okänt om ersättning finns")
    return _finish(
        SeverityTier.LINE_PAUSED, 70, Confidence.LOW,
        reasons, alert, "train.line_paused.unknown",
    )


def _finish(
    tier: str, score: int, confidence: str,
    reasons: list[str], alert: RailAlert, rule_id: str,
) -> Assessment:
    """Applicerar stationsbonus och eventuell ScoringRule från databasen."""
    if alert.station_departures_in_window >= BUSY_STATION_DEPARTURES:
        score += BUSY_STATION_BONUS
        reasons.append(f"stor station ({alert.station_departures_in_window} avgångar)")

    # Inbyggda tak som fallback. Reglerna ska vara data i ScoringRule --
    # men en tom tabell (nytt system, test, glömd seed_rules) får inte
    # betyda att en försening kan poängsättas som en stoppad linje.
    # Databasen får skärpa gränserna, aldrig vara det enda skyddet.
    cap = DEFAULT_CAPS.get(tier)
    if cap is not None:
        score = min(score, cap)

    # Regeln måste matcha grenen, inte bara nivån. Slår man upp enbart på
    # tier höjer line_paused/golv-85 även long_gap-fallet (78) till 85 --
    # och raderar den rangordning som är hela poängen med fasen.
    condition = rule_id.rsplit(".", 1)[-1] if "." in rule_id else ""
    rule = rule_for(tier, TransportMode.TRAIN, condition)
    score = rule.apply(score) if rule else max(0, min(100, score))

    if alert.station:
        reasons.append(f"station: {alert.station}")
    brand = alert.information_owner or alert.operator
    if brand:
        reasons.append(f"operatör: {brand}")
    return Assessment(tier, score, confidence, reasons, rule_id)
