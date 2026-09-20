"""
Samma verkliga evenemang i två källor.

Uppmätt 2026-09-13: 183 av Ticketmasters 246 evenemang fanns också hos PredictHQ,
oftast inom 30 meter och med samma namn. Parningen görs i minnet vid visning --
PredictHQ-data får inte sparas (villkoren 3.7 d i, se events/live.py) -- och är
därför en ren funktion över vilka objekt som helst med rätt attribut.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict

from core.geo import haversine_km
from events import timing

# 400 m och 90 minuter täcker "Stevie Wonder at 3Arena" mot Ticketmasters post på
# Globentorget 2. Namnlikheten skiljer två evenemang på samma arena samma kväll åt.
MAX_KM = 0.4
MAX_START_GAP = dt.timedelta(minutes=90)
MIN_NAME_SIMILARITY = 0.5

_EARLIEST = dt.datetime.min.replace(tzinfo=dt.timezone.utc)


def pair(primaries: list, others: list) -> dict[int, tuple[int, str]]:
    """
    {index i others: (index i primaries, förklaring)} för varje par som avser samma evenemang.

    Objekten behöver `start_date`, `start_at`, `lat`, `lon` och `name`. Varje primär
    tas av högst en annan, och den närmaste i starttid vinner -- annars kunde Mamma
    Mias två föreställningar samma dag hamna på samma rad.
    """
    by_date: dict[dt.date, list[int]] = defaultdict(list)
    for index, primary in enumerate(primaries):
        if primary.lat is not None and primary.lon is not None:
            by_date[primary.start_date].append(index)

    order = sorted(
        range(len(others)),
        key=lambda j: (others[j].start_date, others[j].start_at is None, others[j].start_at or _EARLIEST),
    )
    used: set[int] = set()
    result: dict[int, tuple[int, str]] = {}
    for j in order:
        other = others[j]
        if other.lat is None or other.lon is None:
            continue
        best = None
        for i in by_date.get(other.start_date, []):
            if i in used:
                continue
            primary = primaries[i]
            distance = haversine_km(other.lat, other.lon, primary.lat, primary.lon)
            if distance > MAX_KM:
                continue
            gap = abs(other.start_at - primary.start_at) if other.start_at and primary.start_at else dt.timedelta(0)
            if gap > MAX_START_GAP:
                continue
            similarity = timing.name_similarity(other.name, primary.name)
            if similarity < MIN_NAME_SIMILARITY:
                continue
            key = (gap, -similarity, distance)
            if best is None or key < best[0]:
                best = (key, i, distance, similarity, gap)
        if best:
            _, i, distance, similarity, gap = best
            used.add(i)
            result[j] = (
                i,
                f"{distance * 1000:.0f} m bort, {int(gap.total_seconds() // 60)} min isär, namnlikhet {similarity:.0%}.",
            )
    return result
