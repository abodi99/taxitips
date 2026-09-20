"""
AIS-pilot (P1): när lägger nästa färja till vid terminalen, och när går folk iland?

Två tider hålls isär med avsikt:

* `berth_eta` -- när fartyget förväntas ligga vid kaj.
* `pickup_window` -- när resenärerna kommer ut: kajtid + 10 till + 45 minuter.
  Okalibrerat startvärde; FerryCall sparar förutsagd mot faktisk kajtid för att
  kunna kalibrera det.

Kajtiden räknas på ETT sätt åt gången, och grunden står med. Ingen vägd blandning av
fartygets AIS-ETA och sträcka/fart: en blandad siffra går varken att förklara för
föraren eller att kalibrera. Regeln:

1. Nära terminalen (inom NEAR_KM): återstående sträcka och snittfart ur bufferten.
2. Längre bort: fartygets egen AIS-ETA, om den är rimlig och destinationen pekar på
   terminalen.
3. Annars sträcka och fart, om fartyget är i fart.

Ett fartyg som inte närmar sig terminalen -- avgår, eller går till en annan hamn --
ger ingenting. Avgångar från Sverige är inte en körning.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import deque
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

from core.geo import haversine_km
from maritime import ais
from maritime.register import TERMINALS, PilotTerminal

SOURCE = "aisstream_pilot"
RULE_ID = "boat.berth_eta_pilot"
STOCKHOLM = ZoneInfo("Europe/Stockholm")

# Positionsbufferten per fartyg.
BUFFER_POSITIONS = 10
BUFFER_WINDOW = dt.timedelta(minutes=30)
# Trenden kräver minst så lång tid och så mycket minskat avstånd, annars är det brus.
MIN_TREND_SPAN = dt.timedelta(minutes=2)
MIN_CLOSING_KM = 0.3

NEAR_KM = 25.0
ETA_MAX_AHEAD = dt.timedelta(hours=12)
ETA_MAX_BEHIND = dt.timedelta(minutes=10)
PICKUP_FROM = dt.timedelta(minutes=10)
PICKUP_UNTIL = dt.timedelta(minutes=45)
# Tipset skrivs när kajtiden ligger så här nära.
TIP_AHEAD = dt.timedelta(minutes=90)
BERTHED_KNOTS = 1.0
KNOT_KMH = 1.852
# En ändring i kajtid under så här mycket sparas inte i historiken.
ESTIMATE_CHANGE = dt.timedelta(minutes=2)
ESTIMATE_HISTORY = 30

BASIS_DISTANCE = "distance"
BASIS_AIS_ETA = "ais_eta"


@dataclass
class Fix:
    at: dt.datetime
    lat: float
    lon: float
    sog: float | None


@dataclass
class Track:
    mmsi: int
    terminal: PilotTerminal
    fixes: deque = field(default_factory=lambda: deque(maxlen=BUFFER_POSITIONS))
    destination: str = ""
    ais_eta: dt.datetime | None = None

    def add(self, update: ais.AisUpdate) -> None:
        if update.lat is None or update.lon is None:
            return
        if self.fixes and update.timestamp <= self.fixes[-1].at:
            return
        self.fixes.append(Fix(update.timestamp, update.lat, update.lon, update.sog))
        cutoff = update.timestamp - BUFFER_WINDOW
        while self.fixes and self.fixes[0].at < cutoff:
            self.fixes.popleft()

    def distance_km(self, fix: Fix | None = None) -> float | None:
        fix = fix or (self.fixes[-1] if self.fixes else None)
        if fix is None:
            return None
        port = self.terminal.port
        return haversine_km(fix.lat, fix.lon, port.lat, port.lon)


@dataclass(frozen=True)
class BerthEstimate:
    berth_eta: dt.datetime
    basis: str
    distance_km: float
    speed_knots: float | None
    ais_eta: dt.datetime | None
    distance_eta: dt.datetime | None

    @property
    def pickup_window(self) -> tuple[dt.datetime, dt.datetime]:
        return self.berth_eta + PICKUP_FROM, self.berth_eta + PICKUP_UNTIL


def approaching(track: Track) -> bool:
    """Närmar sig fartyget terminalen: kortare avstånd över bufferten, och i fart nu."""
    if len(track.fixes) < 2:
        return False
    first, last = track.fixes[0], track.fixes[-1]
    if last.at - first.at < MIN_TREND_SPAN:
        return False
    if last.sog is None or last.sog < ais.UNDERWAY_KNOTS:
        return False
    return track.distance_km(first) - track.distance_km(last) >= MIN_CLOSING_KM


def berthed(track: Track) -> bool:
    """Ligger fartyget vid terminalen: inne i hamnrutan och nästan stilla."""
    if not track.fixes:
        return False
    last = track.fixes[-1]
    return (
        track.terminal.port.contains(last.lat, last.lon)
        and last.sog is not None
        and last.sog < BERTHED_KNOTS
    )


def mean_speed(track: Track) -> float | None:
    speeds = [f.sog for f in track.fixes if f.sog is not None and f.sog >= ais.UNDERWAY_KNOTS]
    return sum(speeds) / len(speeds) if speeds else None


def destination_matches(track: Track) -> bool:
    text = (track.destination or "").upper()
    return any(code in text for code in track.terminal.destination_codes)


def estimate(track: Track, now: dt.datetime) -> BerthEstimate | None:
    """Kajtiden för ett fartyg som närmar sig, med grund -- eller None."""
    if not approaching(track):
        return None
    last = track.fixes[-1]
    distance = track.distance_km()
    speed = mean_speed(track)
    distance_eta = None
    if speed:
        hours = distance * track.terminal.route_factor / (speed * KNOT_KMH)
        distance_eta = last.at + dt.timedelta(hours=hours)
    ais_eta = None
    if (
        track.ais_eta
        and destination_matches(track)
        and -ETA_MAX_BEHIND <= track.ais_eta - now <= ETA_MAX_AHEAD
    ):
        ais_eta = track.ais_eta

    if distance <= NEAR_KM and distance_eta:
        return BerthEstimate(distance_eta, BASIS_DISTANCE, distance, speed, ais_eta, distance_eta)
    if ais_eta:
        return BerthEstimate(ais_eta, BASIS_AIS_ETA, distance, speed, ais_eta, distance_eta)
    if distance_eta:
        return BerthEstimate(distance_eta, BASIS_DISTANCE, distance, speed, ais_eta, distance_eta)
    return None


def call_id(track: Track) -> str:
    started = track.fixes[0].at.astimezone(dt.timezone.utc)
    return f"{track.mmsi}:{track.terminal.port_key}:{started:%Y%m%dT%H%M}"


def record_estimate(call, est: BerthEstimate, now: dt.datetime) -> bool:
    """Skriv uppskattningen på anlöpet. True när den ändrats nog att sparas."""
    changed = (
        call.berth_eta is None
        or abs(est.berth_eta - call.berth_eta) >= ESTIMATE_CHANGE
        or call.eta_basis != est.basis
    )
    if call.first_estimate_at is None:
        call.first_estimate_at = now
        call.first_berth_eta = est.berth_eta
    call.berth_eta = est.berth_eta
    call.eta_basis = est.basis
    call.distance_km = round(est.distance_km, 1)
    if changed:
        history = list(call.estimates or [])
        history.append({
            "at": now.isoformat(),
            "berthEta": est.berth_eta.isoformat(),
            "basis": est.basis,
            "distanceKm": round(est.distance_km, 1),
        })
        call.estimates = history[-ESTIMATE_HISTORY:]
    return changed


# -- tipset --------------------------------------------------------------------


def assess(est: BerthEstimate, *, name: str, length_m: int | None) -> tuple[int, str, list[str]]:
    """(poäng, säkerhet, skäl). Storleken som storlek, aldrig som antal resenärer."""
    from core.models import Confidence
    from maritime import tips as port_tips

    if length_m:
        base, band = next(
            ((score, label) for floor, score, label in port_tips.SIZE_BANDS if length_m >= floor),
            (35, "färja"),
        )
        size = f"{length_m} m ({band})"
    else:
        base, band, size = 35, "färja", "okänd längd"

    berth_local = est.berth_eta.astimezone(STOCKHOLM)
    reasons = [f"{name}: {size}. Hur många som reser framgår inte av AIS."]
    if est.basis == BASIS_DISTANCE:
        reasons.append(
            f"Kajtid ≈ {berth_local:%H:%M}, räknad på återstående {est.distance_km:.0f} km "
            f"och snittfarten {est.speed_knots:.0f} knop de senaste positionerna."
        )
    else:
        reasons.append(
            f"Kajtid ≈ {berth_local:%H:%M} enligt fartygets egen AIS-ETA, som besättningen "
            f"matar in för hand. Fartyget är {est.distance_km:.0f} km bort."
        )
    reasons.append("Iland-fönstret, kajtid +10 till +45 min, är ett okalibrerat startvärde.")

    confidence = Confidence.MEDIUM if est.basis == BASIS_DISTANCE and est.distance_km <= NEAR_KM else Confidence.LOW
    pickup_local = est.pickup_window[0].astimezone(STOCKHOLM)
    score = base
    if pickup_local.hour >= port_tips.LATE_FROM_HOUR or pickup_local.hour < port_tips.LATE_UNTIL_HOUR:
        score += port_tips.LATE_BONUS
        reasons.append(f"Kvällsankomst (efter {port_tips.LATE_FROM_HOUR}:00).")
    return min(score, port_tips.SCORE_CAP), confidence.value, reasons


def write_tip(call, est: BerthEstimate, *, name: str, length_m: int | None) -> str:
    """Skriv källhändelsen och tipset för anlöpet. Samma anlöp skriver över sitt eget tips."""
    from core.models import SeverityTier
    from core.repository import upsert_opportunities, upsert_source_events

    terminal = TERMINALS[call.terminal]
    port = terminal.port
    ext = f"{SOURCE}:{call.call_id}"
    pickup_start, pickup_end = est.pickup_window
    score, confidence, reasons = assess(est, name=name, length_m=length_m)
    berth_local = est.berth_eta.astimezone(STOCKHOLM)

    source_ids = upsert_source_events([{
        "source": SOURCE,
        "external_id": ext,
        "mode": "boat",
        "active_from": pickup_start,
        "active_to": pickup_end,
        "raw": json.dumps({
            "mmsi": call.mmsi,
            "ship_name": name,
            "terminal": port.name,
            "berth_eta": est.berth_eta.isoformat(),
            "basis": est.basis,
            "ais_eta": est.ais_eta.isoformat() if est.ais_eta else None,
            "distance_eta": est.distance_eta.isoformat() if est.distance_eta else None,
            "distance_km": round(est.distance_km, 1),
            "speed_knots": round(est.speed_knots, 1) if est.speed_knots else None,
        }, ensure_ascii=False),
        "lat": port.lat,
        "lon": port.lon,
    }])

    places = [port.name] if port.city in port.name else [port.name, port.city]
    upsert_opportunities([{
        "external_id": ext,
        "kind": "ferry",
        "mode": "boat",
        "severity_tier": SeverityTier.ARRIVAL_WAVE.value,
        "level": "high" if score >= 60 else "medium",
        "title": f"{name.title()} lägger till i {port.name} ≈ {berth_local:%H:%M}",
        "summary": (
            f"Folk går iland ≈ {pickup_start.astimezone(STOCKHOLM):%H:%M}–"
            f"{pickup_end.astimezone(STOCKHOLM):%H:%M} (beräknat, okalibrerat)."
        ),
        "lat": port.lat,
        "lon": port.lon,
        "h3_index": "",
        "places": json.dumps(places, ensure_ascii=False),
        "region": port.region,
        # Tipset gäller iland-fönstret, inte kajtiden: det är då resenärerna finns.
        "start_time": pickup_start,
        "end_time": pickup_end,
        "demand_score": score,
        "confidence": confidence,
        "reasons": json.dumps(reasons, ensure_ascii=False),
        "rule_id": RULE_ID,
        "source_event_ids": json.dumps([source_ids[ext]] if ext in source_ids else []),
        "compensation_eligible": False,
        "compensation_amount_kr": None,
        "next_departure_minutes": None,
        "next_departure_at": None,
        "is_last_departure": False,
        "has_alternative": False,
        "alternative_note": "",
    }])
    return ext


def subscription(api_key: str) -> dict:
    """EN filtrerad anslutning: registrets fartyg, var som helst i inseglingsrutorna."""
    from maritime.register import REGISTER

    return {
        "APIKey": api_key,
        "BoundingBoxes": [[list(t.approach_box[0]), list(t.approach_box[1])] for t in TERMINALS.values()],
        # AISStream vill ha MMSI som strängar.
        "FiltersShipMMSI": [str(vessel.mmsi) for vessel in REGISTER],
        "FilterMessageTypes": list(ais.MESSAGE_TYPES),
    }
