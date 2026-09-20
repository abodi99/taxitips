"""
Kombinationslagret (P2): signaler från olika källor som gäller samma plats och tid.

Pipelinen bedömer varje källa för sig. Här hittas det som bara syns när två signaler
läggs bredvid varandra. Varje påslag bär ett regel-id och en skälrad, så att det går
att förklara för föraren och att stänga av:

* `combo.duplicate` -- samma störning från två källor. Mätt lokalt 2026-09-14:
  Skånetrafiken och Trafikverket om samma inställda tåg, 65 m isär. Visas som EN rad;
  den andra källan står med som stöd. Primär är den med högst poäng, därefter högst
  säkerhet.
* `combo.hub` -- störningar i olika färdsätt vid samma knutpunkt, till exempel tåg och
  buss vid samma station: fler väntar på samma plats. +HUB_BOOST.
* `combo.arrival` -- en ankomstvåg (flyg eller färja) medan kollektivtrafiken från
  samma hub är inställd eller stoppad: de som anländer har färre alternativ.
  +ARRIVAL_BOOST.

Ett tips med utskrivet alternativ (ersättningstrafik) förstärks aldrig.

Påslagen ändrar ordningen i förarens lista men INTE notiserna. De är okalibrerade, och
en notis ska vila på källans egen bedömning tills påslagen mätts mot feedback.

Körs som eget jobb (`combine_signals`, var 60:e sekund), aldrig i anropet. Resultatet
ersätter förra körningens rader i `opportunity_combinations`: raderna är härledda och
räknas om från tipsen varje gång.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass

from core.geo import haversine_km

DUPLICATE_KM = 0.4
HUB_KM = 0.4
ARRIVAL_HUB_KM = 2.0
HUB_BOOST = 5
ARRIVAL_BOOST = 10
DISRUPTION_TIERS = frozenset({"line_paused", "vehicle_cancelled"})
ARRIVAL_KINDS = frozenset({"flight", "ferry"})
CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}
DEFAULT_LIFETIME = dt.timedelta(hours=1)


@dataclass(frozen=True)
class Found:
    rule_id: str
    effect: str  # "merge" (dubblett, en rad) eller "boost" (höjer ordningen)
    primary: str
    members: tuple[str, ...]
    boost: int
    reason: str
    expires_at: dt.datetime


def source_of(tip) -> str:
    return str(tip.external_id).split(":", 1)[0]


def _overlaps(a, b, now: dt.datetime) -> bool:
    a_start, b_start = a.start_time or now, b.start_time or now
    a_end, b_end = a.end_time or now + DEFAULT_LIFETIME, b.end_time or now + DEFAULT_LIFETIME
    return a_start <= b_end and b_start <= a_end


def _near(a, b, km: float) -> bool:
    return (
        None not in (a.lat, a.lon, b.lat, b.lon)
        and haversine_km(a.lat, a.lon, b.lat, b.lon) <= km
    )


def _rank(tip) -> tuple:
    return (-(tip.demand_score or 0), -CONFIDENCE_RANK.get(tip.confidence, 0), str(tip.external_id))


def _expires(tips, now: dt.datetime) -> dt.datetime:
    ends = [t.end_time for t in tips if t.end_time]
    return min(ends) if ends else now + DEFAULT_LIFETIME


def find(tips: list, now: dt.datetime) -> list[Found]:
    """Kombinationerna bland aktiva tips. Rent: inga databasanrop."""
    placed = [t for t in tips if t.lat is not None and t.lon is not None and t.kind != "road"]
    found: list[Found] = []

    # 1. Dubbletter: samma färdsätt, olika källor, samma plats och tid.
    merged: set[str] = set()
    ordered = sorted(placed, key=_rank)
    for i, primary in enumerate(ordered):
        if primary.external_id in merged:
            continue
        dupes = [
            other for other in ordered[i + 1:]
            if other.external_id not in merged
            and source_of(other) != source_of(primary)
            and other.kind == primary.kind
            and other.mode == primary.mode
            and _near(primary, other, DUPLICATE_KM)
            and _overlaps(primary, other, now)
        ]
        if not dupes:
            continue
        merged.update(d.external_id for d in dupes)
        sources = ", ".join(sorted({source_of(d) for d in dupes}))
        found.append(Found(
            "combo.duplicate", "merge", primary.external_id, tuple(d.external_id for d in dupes), 0,
            f"Samma störning rapporteras även av {sources}.", _expires([primary, *dupes], now),
        ))

    remaining = [t for t in ordered if t.external_id not in merged]
    disruptions = [
        t for t in remaining
        if t.kind == "transit" and t.severity_tier in DISRUPTION_TIERS and not t.has_alternative
    ]

    # 2. Knutpunkt: störningar i olika färdsätt på samma plats. Påslaget går till den
    # starkaste i klustret; de andra står som medlemmar.
    clustered: set[str] = set()
    for primary in disruptions:
        if primary.external_id in clustered:
            continue
        others = [
            other for other in disruptions
            if other is not primary
            and other.external_id not in clustered
            and other.mode != primary.mode
            and _near(primary, other, HUB_KM)
            and _overlaps(primary, other, now)
        ]
        if not others:
            continue
        clustered.add(primary.external_id)
        clustered.update(o.external_id for o in others)
        modes = ", ".join(sorted({o.mode or "okänt" for o in [primary, *others]}))
        found.append(Found(
            "combo.hub", "boost", primary.external_id, tuple(o.external_id for o in others), HUB_BOOST,
            f"Flera störningar vid samma knutpunkt ({modes}): fler väntar på samma plats.",
            _expires([primary, *others], now),
        ))

    # 3. Ankomst medan kollektivtrafiken från samma hub står still.
    for arrival in (t for t in remaining if t.kind in ARRIVAL_KINDS and not t.has_alternative):
        hits = [d for d in disruptions if _near(arrival, d, ARRIVAL_HUB_KM) and _overlaps(arrival, d, now)]
        if not hits:
            continue
        found.append(Found(
            "combo.arrival", "boost", arrival.external_id, tuple(h.external_id for h in hits), ARRIVAL_BOOST,
            f"Kollektivtrafiken härifrån är inställd eller stoppad ({(hits[0].title or '')[:60]}): "
            f"de som anländer har färre alternativ.",
            _expires([arrival, *hits], now),
        ))
    return found


def run(now: dt.datetime | None = None) -> Counter:
    """Räkna om kombinationerna och ersätt förra körningens rader."""
    from django.db import transaction
    from django.utils import timezone

    from core.models import Combination, Opportunity

    now = now or timezone.now()
    tips = list(
        Opportunity.objects.filter(end_time__gt=now)
        .exclude(severity_tier="ignore")
        .exclude(kind="road")
        .only(
            "external_id", "kind", "mode", "severity_tier", "demand_score", "confidence",
            "has_alternative", "lat", "lon", "start_time", "end_time", "title",
        )
    )
    combinations = find(tips, now)
    with transaction.atomic():
        Combination.objects.all().delete()
        Combination.objects.bulk_create([
            Combination(
                rule_id=c.rule_id, effect=c.effect, primary_external_id=c.primary,
                member_external_ids=list(c.members), boost=c.boost, reason=c.reason,
                computed_at=now, expires_at=c.expires_at,
            )
            for c in combinations
        ])
    return Counter(c.rule_id for c in combinations)
