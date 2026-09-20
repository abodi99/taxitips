"""
Regelmotorn för flygankomster: från enskilda flyg till ankomstvågor.

Enheten är fönstret, inte flyget. Ett enskilt plan är ingen störning -- det
taxirelevanta är anhopningen: N ankomster inom samma halvtimme, sent på
kvällen, när tåg och buss tunnats ut. Därför skrivs ETT tips per
(flygplats, 30-minutersfönster), inte ett per flyg.

Motsvarar core/scoring.py:s roll för järnväg: strukturell klassificering av
en källa som redan ger oss tal, i stället för textgissning. Alla tal kommer
från core/thresholds.py (invariant 7).

Vad motiveringen får säga
-------------------------
Nattpåslaget finns därför att kollektivtrafiken faktiskt tunnas ut -- men vi
har ingen tidtabell för Arlanda Express eller flygbussarna, och tipset får
därför ALDRIG skriva "sista tåget har gått" (invariant 2). Motiveringen säger
tidpunkten och att den gav ett påslag, inte vad tidpunkten innebär för
resenärens alternativ. Samma skäl till att antal resenärer aldrig nämns:
svaret innehåller varken flygplanstyp eller passagerarantal.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from django.utils import timezone

from core import thresholds
from core.models import Confidence, SeverityTier, TransportMode
from core.rules import rule_for
from core.sources.swedavia import NON_ARRIVING_STATUSES

RULE_ID = "flight.arrival_wave"
RULE_ID_LAST = "flight.last_arrival"


@dataclass
class FlightWindow:
    """En flygplats och en halvtimme, med flygen som landar i den."""

    airport: str
    start: dt.datetime  # aware, UTC
    end: dt.datetime
    flights: list[dict] = field(default_factory=list)
    # Satt av windows(): fönstret är kvällens sista, inget mer landar inom
    # FLIGHT_ISOLATION_HOURS. Bara meningsfullt för RULE_LAST_ARRIVAL.
    is_last: bool = False

    @property
    def config(self) -> dict:
        return thresholds.AIRPORTS[self.airport]

    @property
    def arrivals(self) -> int:
        return len(self.flights)

    @property
    def delayed(self) -> list[dict]:
        return [
            f for f in self.flights
            if (f.get("delay_minutes") or 0) >= thresholds.FLIGHT_DELAY_MINUTES
        ]

    @property
    def live(self) -> int:
        return sum(1 for f in self.flights if f.get("is_live"))

    @property
    def local_start(self) -> dt.datetime:
        return timezone.localtime(self.start)

    @property
    def local_end(self) -> dt.datetime:
        return timezone.localtime(self.end)

    @property
    def external_id(self) -> str:
        """
        Stabil över pollar av samma fönster, så upsert uppdaterar i stället
        för att skapa dubbletter. UTC med avsikt: lokal tid hade gett två
        olika id för samma timme natten då klockan ställs om.
        """
        stamp = self.start.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
        return f"swedavia:{self.airport}:{stamp}"

    def label(self) -> str:
        return f"{self.local_start:%H:%M}–{self.local_end:%H:%M}"


@dataclass
class FlightAssessment:
    tier: str
    score: int
    confidence: str
    reasons: list[str]
    rule_id: str
    mode: str = TransportMode.FLIGHT


def _floor_to_window(moment: dt.datetime) -> dt.datetime:
    """
    Avrundar nedåt till fönsterstart, räknat på LOKAL tid.

    Lokalt och inte UTC därför att gränserna ska ligga på halvtimmar en
    förare känner igen ("23:30"), inte på 21:30 UTC som råkar bli 23:30 på
    sommaren och 22:30 på vintern.
    """
    local = timezone.localtime(moment)
    minute = (local.minute // thresholds.FLIGHT_WINDOW_MINUTES) * thresholds.FLIGHT_WINDOW_MINUTES
    return local.replace(minute=minute, second=0, microsecond=0)


def windows(flights: list[dict], airport: str, now: dt.datetime | None = None) -> list[FlightWindow]:
    """
    Flyg -> de fönster som faktiskt är taxirelevanta.

    Grindarna, i ordning:
      1. Borttagna och inställda flyg räknas aldrig -- de bär inga resenärer.
      2. Bara sena timmar: mitt på dagen finns full kollektivtrafik.
      3. Flygplatsens egen regel -- volym (RULE_WAVE) eller ensamhet
         (RULE_LAST_ARRIVAL). Se thresholds.AIRPORTS för varför de skiljer sig.

    `flights` får gärna innehålla både dagens och morgondagens ankomster:
    ensamhetsregeln måste kunna se förbi midnatt för att avgöra om ett plan
    23:50 verkligen är kvällens sista.
    """
    now = now or timezone.now()
    config = thresholds.AIRPORTS[airport]
    span = dt.timedelta(minutes=thresholds.FLIGHT_WINDOW_MINUTES)

    counted = [
        f for f in flights
        if f.get("status") not in NON_ARRIVING_STATUSES and f.get("effective")
    ]

    buckets: dict[dt.datetime, FlightWindow] = {}
    for flight in counted:
        start = _floor_to_window(flight["effective"])
        if not thresholds.is_flight_late_hour(start.hour):
            continue
        window = buckets.get(start)
        if window is None:
            window = buckets[start] = FlightWindow(airport=airport, start=start, end=start + span)
        window.flights.append(flight)

    if config["rule"] == thresholds.RULE_WAVE:
        ready = [w for w in buckets.values() if w.arrivals >= config["wave_min"]]
    else:
        # Ensamhetsregeln mäts mot ALLA ankomster, inte bara de sena: ett plan
        # 05:30 är inte kvällens sista om nästa landar 06:15, även om 06:15
        # ligger utanför det sena fönstret.
        after = sorted(f["effective"] for f in counted)
        gap = dt.timedelta(hours=thresholds.FLIGHT_ISOLATION_HOURS)
        ready = []
        for w in buckets.values():
            latest = max(f["effective"] for f in w.flights)
            if not any(latest < t <= latest + gap for t in after):
                w.is_last = True
                ready.append(w)

    ready.sort(key=lambda w: w.start)
    return ready


def _confidence(window: FlightWindow, now: dt.datetime) -> str:
    """
    Hur säkra är vi på att fönstret ser ut så här?

    Ett fönster långt fram bygger på ren tidtabell -- inga estimat har
    publicerats än, och halva vågen kan ha flyttat sig när det väl blir kväll.
    Nära i tiden avgör i stället hur många av flygen källan faktiskt sagt
    något om (estimatedUtc/actualUtc) i stället för att bara ha tidtabellen.
    """
    horizon = now + dt.timedelta(hours=thresholds.FLIGHT_HORIZON_HOURS)
    if window.start > horizon:
        return Confidence.LOW
    if window.live * 2 >= window.arrivals:
        return Confidence.HIGH
    return Confidence.MEDIUM


def classify(window: FlightWindow, now: dt.datetime | None = None) -> FlightAssessment:
    """Ett fönster -> tier, poäng, confidence och en motivering som går att följa."""
    now = now or timezone.now()
    config = window.config
    delayed = window.delayed
    is_wave = config["rule"] == thresholds.RULE_WAVE

    if is_wave:
        tier, rule_id = SeverityTier.ARRIVAL_WAVE, RULE_ID
        extra = window.arrivals - config["wave_min"]
        score = thresholds.FLIGHT_BASE_SCORE + thresholds.FLIGHT_SCORE_PER_EXTRA_ARRIVAL * extra
        reasons = [f"{window.arrivals} ankomster landar {window.label()} på {config['name']}"]
    else:
        tier, rule_id = SeverityTier.LAST_ARRIVAL, RULE_ID_LAST
        score = (
            thresholds.FLIGHT_LAST_ARRIVAL_BASE
            + thresholds.FLIGHT_LAST_ARRIVAL_PER_EXTRA * (window.arrivals - 1)
        )
        plan = "1 plan" if window.arrivals == 1 else f"{window.arrivals} plan"
        reasons = [
            f"{plan} landar {window.label()} på {config['name']}",
            # Ett påstående ur tidtabellen, inte om resenärens alternativ:
            # vi vet att inget mer landar, inte att bussen slutat gå.
            f"inget mer plan landar här inom {thresholds.FLIGHT_ISOLATION_HOURS} timmar",
        ]

    if delayed:
        bonus = min(
            thresholds.FLIGHT_DELAY_BONUS_CAP,
            thresholds.FLIGHT_SCORE_PER_DELAYED * len(delayed),
        )
        score += bonus
        reasons.append(
            f"{len(delayed)} av dem är minst {thresholds.FLIGHT_DELAY_MINUTES} minuter försenade"
        )

    if thresholds.is_flight_night_hour(window.local_start.hour):
        score += thresholds.FLIGHT_NIGHT_BONUS
        # Säger tidpunkten och påslaget, inte vad tidpunkten betyder för
        # resenärens alternativ -- se modulens docstring.
        reasons.append(f"sen kväll/natt — påslag {thresholds.FLIGHT_NIGHT_BONUS} p")

    # Databasen får skärpa gränsen, aldrig vara det enda skyddet: en tom
    # ScoringRule-tabell (nytt system, test, glömd seed_rules) ska inte kunna
    # släppa igenom en poäng över 100. Samma resonemang som core/scoring.py.
    rule = rule_for(tier, TransportMode.FLIGHT)
    score = rule.apply(score) if rule else max(0, min(100, score))

    reasons.append(f"flygplats: {config['name']} ({window.airport})")
    shown = [f["flight_id"] for f in window.flights[:4] if f.get("flight_id")]
    if shown:
        more = window.arrivals - len(shown)
        listed = ", ".join(shown) + (f" m.fl. (+{more})" if more > 0 else "")
        reasons.append(f"flyg: {listed}")

    return FlightAssessment(
        tier=tier,
        score=score,
        confidence=_confidence(window, now),
        reasons=reasons,
        rule_id=rule_id,
    )


def title(window: FlightWindow) -> str:
    kind = "Ankomstvåg" if window.config["rule"] == thresholds.RULE_WAVE else "Sista ankomsten"
    return f"{kind} {window.config['name']} {window.local_start:%H:%M}"


def summary(window: FlightWindow) -> str:
    """
    Antal plan, aldrig antal resenärer.

    Svaret bär varken flygplanstyp eller passagerarantal, så "500-600
    personer" hade varit påhittat -- samma regel som för GTFS-beläggning.
    """
    when = f"mellan {window.local_start:%H:%M} och {window.local_end:%H:%M}"
    if window.config["rule"] == thresholds.RULE_WAVE:
        text = f"{window.arrivals} plan landar {when}."
    else:
        plan = "Ett plan" if window.arrivals == 1 else f"{window.arrivals} plan"
        text = (
            f"{plan} landar {when}, och sedan är det tomt i minst "
            f"{thresholds.FLIGHT_ISOLATION_HOURS} timmar."
        )
    delayed = window.delayed
    if delayed:
        text += (
            f" {len(delayed)} av dem är minst "
            f"{thresholds.FLIGHT_DELAY_MINUTES} minuter försenade."
        )
    return text


def flight_external_id(flight: dict) -> str:
    """Ett id per flygben, stabilt mellan pollar."""
    scheduled = flight.get("scheduled") or flight.get("effective")
    stamp = scheduled.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    return f"swedavia:{flight['airport']}:{flight['flight_id']}:{stamp}"
