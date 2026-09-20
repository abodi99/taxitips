"""
Ett passagerarfartyg som lägger till blir ett tips.

v1, okalibrerad. Poängen bygger på två saker AIS faktiskt vet -- fartygets
längd och klockslaget -- och säger aldrig hur många som går i land. AIS har
ingen passagerarsiffra, och en 190 meter lång färja kan vara halvtom en
tisdag i november. Därför står storleken som storlek i motiveringen, aldrig
som resenärer: samma princip som GTFS-beläggningen, kategoriskt och utan
påhittade tal.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from core.models import Confidence, SeverityTier
from core.repository import upsert_opportunities, upsert_source_events
from maritime import ais
from maritime.ports import Port

SOURCE = "aisstream"
STOCKHOLM = ZoneInfo("Europe/Stockholm")

# Samma svans som flygets: terminalen töms inte när förtöjningen sitter.
TAIL_MINUTES = 45

# Under det här är det skärgårdstrafik, inte en färja. Alla nio
# passagerarfartyg i provkörningen 2026-09-12 var 24-38 m; de minsta
# Östersjöfärjorna är runt 120 m. 100 lämnar marginal åt båda hållen.
MIN_TIP_LENGTH_M = 100

# (minsta längd, baspoäng, etikett). Längst först.
SIZE_BANDS = (
    (170, 55, "stor färja"),
    (130, 45, "medelstor färja"),
    (MIN_TIP_LENGTH_M, 35, "mindre färja"),
)
# Kvällsankomst lyfter, dagtid gör det inte -- samma riktning som flygets
# dagtidsspärr, men utan påståenden om kollektivtrafiken som vi inte mätt.
LATE_BONUS = 15
LATE_FROM_HOUR = 21
LATE_UNTIL_HOUR = 6
SCORE_CAP = 85

RULE_ID = f"boat.{SeverityTier.ARRIVAL_WAVE.value}"


@dataclass
class Assessment:
    score: int
    confidence: str
    reasons: list[str]
    rule_id: str
    tier: str
    band: str
    start: dt.datetime
    end: dt.datetime


def assess(vessel, port: Port, reason: str, now: dt.datetime) -> Assessment | None:
    """Poängen för en ankomst, eller None om fartyget är för litet för ett tips."""
    length = vessel.length_m
    if not length or length < MIN_TIP_LENGTH_M:
        return None
    base, band = next((score, label) for floor, score, label in SIZE_BANDS if length >= floor)

    if reason == ais.REASON_ETA and vessel.eta:
        start = vessel.eta
    else:
        start = vessel.timestamp or now
    local = start.astimezone(STOCKHOLM)

    name = vessel.ship_name or f"MMSI {vessel.mmsi}"
    reasons = [
        f"{name}: {length} m lång, AIS-typ {vessel.ship_type} ({band}). "
        f"Hur många som reser framgår inte av AIS.",
    ]
    if reason == ais.REASON_SLOWING:
        reasons.append(
            f"Saktade in till {vessel.speed_knots:.1f} knop i {port.name} kl {local:%H:%M}, "
            f"efter att ha setts i fart."
        )
        confidence = Confidence.MEDIUM
    else:
        reasons.append(
            f"Beräknad ankomst kl {local:%H:%M} enligt fartygets egen AIS-ETA, som är handinmatad."
        )
        confidence = Confidence.LOW

    score = base
    if local.hour >= LATE_FROM_HOUR or local.hour < LATE_UNTIL_HOUR:
        score += LATE_BONUS
        reasons.append(f"Kvällsankomst (efter {LATE_FROM_HOUR}:00).")

    return Assessment(
        score=min(score, SCORE_CAP),
        confidence=confidence.value,
        reasons=reasons,
        rule_id=RULE_ID,
        tier=SeverityTier.ARRIVAL_WAVE.value,
        band=band,
        start=start,
        end=start + dt.timedelta(minutes=TAIL_MINUTES),
    )


def external_id(vessel, port: Port) -> str:
    """Ett id per anlöp: samma fartyg i samma hamn senare samma dag är en ny ankomst."""
    stamp = (vessel.triggered_at or vessel.timestamp).astimezone(dt.timezone.utc)
    return f"{SOURCE}:{port.key}:{vessel.mmsi}:{stamp:%Y%m%dT%H%M}"


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value else None


def write_tip(vessel, port: Port, assessment: Assessment, reason: str) -> str:
    """Skriv källhändelsen och tipset. Returnerar tipsets external_id."""
    ext = external_id(vessel, port)
    local = assessment.start.astimezone(STOCKHOLM)

    source_ids = upsert_source_events([{
        "source": SOURCE,
        "external_id": ext,
        "mode": "boat",
        "active_from": assessment.start,
        "active_to": assessment.end,
        # Fartygets läge i beslutsögonblicket -- det förklaringspanelen visar
        # som "vad källan faktiskt sa".
        "raw": json.dumps({
            "mmsi": vessel.mmsi,
            "ship_name": vessel.ship_name,
            "ship_type": vessel.ship_type,
            "length_m": vessel.length_m,
            "destination": vessel.destination,
            "port": port.name,
            "latitude": vessel.latitude,
            "longitude": vessel.longitude,
            "speed_knots": vessel.speed_knots,
            "nav_status": vessel.nav_status,
            "eta": _iso(vessel.eta),
            "ais_timestamp": _iso(vessel.timestamp),
            "trigger": reason,
        }, ensure_ascii=False),
        "lat": vessel.latitude,
        "lon": vessel.longitude,
    }])

    # places[0] blir push-prefixet; orten läggs till när den inte redan står i
    # namnet, så att "Nynäshamn" matchar en förare som valt "Stockholm".
    places = [port.name] if port.city in port.name else [port.name, port.city]
    title_name = vessel.ship_name.title() if vessel.ship_name else "Färja"
    verb = "lägger till" if reason == ais.REASON_SLOWING else "väntas lägga till"

    upsert_opportunities([{
        "external_id": ext,
        # Inte "road": core/api.py lägger bara vägtips i `context`.
        "kind": "ferry",
        "mode": "boat",
        "severity_tier": assessment.tier,
        "level": "high" if assessment.score >= 60 else "medium",
        "title": f"{title_name} {verb} i {port.name}",
        "summary": f"{assessment.band.capitalize()} ({vessel.length_m} m) {verb} kl {local:%H:%M}.",
        # Terminalen, inte fartygets position: det är dit föraren kör.
        "lat": port.lat,
        "lon": port.lon,
        "h3_index": "",
        "places": json.dumps(places, ensure_ascii=False),
        "region": port.region,
        "start_time": assessment.start,
        "end_time": assessment.end,
        "demand_score": assessment.score,
        "confidence": assessment.confidence,
        "reasons": json.dumps(assessment.reasons, ensure_ascii=False),
        "rule_id": assessment.rule_id,
        "source_event_ids": json.dumps([source_ids[ext]] if ext in source_ids else []),
        "compensation_eligible": False,
        "compensation_amount_kr": None,
        # Ingen tidtabell för bussarna från terminalen. NULL = vet inte.
        "next_departure_minutes": None,
        "next_departure_at": None,
        "is_last_departure": False,
        "has_alternative": False,
        "alternative_note": "",
    }])
    return ext
