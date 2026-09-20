"""
GET /api/events -- evenemangskalendern för föraren.

Samma entitlement-grind som /api/alerts: en obetald eller okänd token får en
tom lista med `reason`, inte 403.

    GET /api/events?days=14&radius_km=150        X-TT-Position: 59.33,18.07

Bara källor som får visas i den betalda appen (events/rights.py). Utan en
rättighetsreferens för visning är listan tom, med reason `no_licensed_sources`.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter

from django.db.models import F, Q
from django.utils import timezone
from django.views.decorators.http import require_GET

import functools

from django.conf import settings

from core import areas
from core.api import _float, _json, position_from, request_area
from core.entitlement import entitlement_for_request
from core.geo import haversine_km
from events import matching, timing
from events import ingest
from events.rights import app_sources, rights_for
from events.models import Event

DEFAULT_DAYS = 14
# Så långt fram som hämtningen når (poll_events): längre fram finns inget att visa.
MAX_DAYS = ingest.DEFAULT_HORIZON_DAYS
# Samma marknadsradie som tipsflödet: ett evenemang i Göteborg är inte en
# möjlighet för en förare i Stockholm.
DEFAULT_RADIUS_KM = 150.0


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _hhmm(value: dt.datetime | None) -> str | None:
    return value.astimezone(timing.STOCKHOLM).strftime("%H:%M") if value else None


def visible_upcoming(now: dt.datetime, days: int):
    """Det föraren ska se: inte dolt, inte borta ur källan, inte slut, inom `days` dagar."""
    today = now.astimezone(timing.STOCKHOLM).date()
    return visible_between(now, today, today + dt.timedelta(days=days))


def visible_between(now: dt.datetime, first: dt.date, last: dt.date):
    """
    Samma sak mellan två lokala datum: det som börjar i perioden, och det som redan
    pågår när perioden börjar. För `first` = i dag är det exakt visible_upcoming.
    """
    since = max(now, dt.datetime.combine(first, dt.time.min, tzinfo=timing.STOCKHOLM))
    return (
        Event.objects.filter(hidden_reason="", missing_since__isnull=True, start_date__lte=last)
        .filter(Q(start_date__gte=first) | Q(end_at__gt=since) | Q(multi_day=True, end_at__isnull=True))
        .exclude(end_at__lte=now)
        .order_by("start_date", F("start_at").asc(nulls_last=True), "name")
    )


def event_row(event, now: dt.datetime, lat: float | None = None, lon: float | None = None, also=()) -> dict:
    """
    Ett evenemang som API-rad. `event` kan vara en sparad Event eller ett objekt
    med samma attribut (PredictHQ-rader i minnet); `also` är samma evenemang från
    andra källor, som bidrar med sina länkar.
    """
    members = [event, *also]
    links = [
        {"source": m.source, "label": timing.SOURCE_LABELS.get(m.source, m.source), "url": m.url}
        for m in members if getattr(m, "url", "")
    ]
    attendance = getattr(event, "attendance", None)
    leave_until = event.end_at + dt.timedelta(minutes=timing.LEAVE_WINDOW_MIN) if event.end_at else None
    distance = None
    if None not in (lat, lon, event.lat, event.lon):
        distance = round(haversine_km(lat, lon, event.lat, event.lon), 1)
    size = timing.size_level(attendance)
    sport = timing.sport_for(event.source, event.category, getattr(event, "genre", ""),
                             getattr(event, "sub_genre", ""), event.name)
    from core.areas import COUNTY_NAMES, place_for

    county_code, municipality_code, _codes = place_for(
        event.lat, event.lon, event.region or None,
    )
    return {
        "id": f"{event.source}:{event.external_id}",
        "source": event.source,
        "sources": [m.source for m in members],
        "sourceLabel": " + ".join(timing.SOURCE_LABELS.get(m.source, m.source) for m in members),
        # Utan "Platinum Tickets": för många arenakonserter är det den enda posten
        # Ticketmaster listar. Källans namn följer med för spårbarhet.
        "name": timing.display_name(event.name),
        "sourceName": event.name,
        "url": links[0]["url"] if links else "",
        "links": links,
        "category": event.category,
        "categoryLabel": timing.CATEGORY_LABELS.get(event.category, event.category),
        # Fotboll, ishockey, handboll eller annan sport; tomt när det inte är sport.
        "sport": sport,
        "sportLabel": timing.SPORT_LABELS.get(sport, ""),
        "status": event.source_status,
        "statusLabel": timing.status_label(event.source_status),
        "happening": timing.is_happening(event.source_status),
        # En förutsägelse, inte en räkning: visas avrundad. Bara PredictHQ har den.
        "attendance": attendance,
        "attendanceText": timing.attendance_text(attendance),
        "sizeLevel": size,
        "sizeLabel": timing.SIZE_LABELS[size],
        # Arenans kapacitet (TheSportsDB): hur stor platsen är, inte hur många som kommer.
        "venueCapacity": ((getattr(event, "raw", None) or {}).get("capacity")
                          if event.source == "thesportsdb" else None),
        "rank": getattr(event, "rank", None),
        "localRank": getattr(event, "local_rank", None),
        "startDate": event.start_date.isoformat(),
        "startAt": _iso(event.start_at),
        "startLocal": _hhmm(event.start_at),
        "timeKnown": event.time_known,
        "endAt": _iso(event.end_at),
        "endLocal": _hhmm(event.end_at),
        # Flerdagars konferenser och nattklubbskvällar slutar en annan dag än de
        # börjar -- utan datumet ser 09:00-18:00 ut att ha passerat.
        "endDate": event.end_at.astimezone(timing.STOCKHOLM).date().isoformat() if event.end_at else None,
        "endBasis": event.end_basis,
        "endNote": event.end_note,
        # Utsläppsfönstret -- när publiken lämnar lokalen. Det är det här, inte
        # starttiden, som gör ett evenemang till en körning.
        "leaveFrom": _iso(event.end_at),
        "leaveUntil": _iso(leave_until),
        "leaveUntilLocal": _hhmm(leave_until),
        "ongoing": bool(event.start_at and event.start_at <= now and (event.end_at is None or now < event.end_at)),
        "multiDay": event.multi_day,
        # Arenanamnet saknas ibland i källan (Avicii Arena hos Ticketmaster), men
        # adressen finns.
        "venueName": event.venue_name or event.address or event.city,
        "address": event.address,
        "city": event.city,
        "lat": event.lat,
        "lon": event.lon,
        "region": event.region,
        "county": county_code,
        "countyName": COUNTY_NAMES.get(county_code or ""),
        "municipality": municipality_code,
        "distanceKm": distance,
    }


def _merged(events: list) -> list[tuple]:
    """
    En rad per verkligt evenemang, i visible_upcoming:s ordning. Finns samma evenemang
    hos PredictHQ och en annan källa paras de (events/matching.py): PredictHQ-raden bär
    besökarprognosen, den andra bidrar med sin länk.
    """
    primaries = [e for e in events if e.source == "predicthq"]
    others = [e for e in events if e.source != "predicthq"]
    if not primaries or not others:
        return [(event, ()) for event in events]
    pairs = matching.pair(primaries, others)
    also: dict[int, list] = {}
    for j, (i, _note) in pairs.items():
        also.setdefault(id(primaries[i]), []).append(others[j])
    paired = {id(others[j]) for j in pairs}
    return [(event, tuple(also.get(id(event), ()))) for event in events if id(event) not in paired]


PREVIEW_NOTE = (
    "Förhandsvisning i utveckling: ingen källa har ännu rätt att visas i appen, "
    "och förare ser inte det här förrän ett avtal finns."
)


@functools.lru_cache(maxsize=4096)
def _codes_at(lat: float, lon: float) -> frozenset[str]:
    return frozenset(areas.area_for(lat, lon)[1])


def _date(value) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def period(request, today: dt.date) -> tuple[dt.date, dt.date]:
    """
    Perioden föraren valt: `from` och `to` (YYYY-MM-DD, lokala datum, båda med), annars
    `days` från `from` eller i dag. Aldrig före i dag och aldrig längre fram än MAX_DAYS.
    """
    first = _date(request.GET.get("from")) or today
    last = _date(request.GET.get("to"))
    if last is None:
        try:
            days = int(request.GET.get("days") or DEFAULT_DAYS)
        except ValueError:
            days = DEFAULT_DAYS
        last = first + dt.timedelta(days=max(0, days))
    horizon = today + dt.timedelta(days=MAX_DAYS)
    first = min(max(first, today), horizon)
    last = min(max(last, first), horizon)
    return first, last


def _in_period(event, first: dt.date, last: dt.date) -> bool:
    if event.start_date > last:
        return False
    if event.start_date >= first:
        return True
    # Började före perioden: med bara om det fortfarande pågår när perioden börjar.
    if event.end_at is None:
        return bool(event.multi_day)
    return event.end_at.astimezone(timing.STOCKHOLM).date() >= first


@require_GET
def upcoming(request):
    """
    GET /api/events?from=2026-10-03&to=2026-10-05   (eller ?days=14)

    Evenemangen i perioden, i förarens län och kommuner eller inom radien från positionen.
    `dayCounts` räknar evenemangen per startdag över hela horisonten i samma område, så att
    appen kan visa vilka dagar som har något utan att hämta allt.
    """
    ent = entitlement_for_request(request)
    if not ent.ok:
        return _json(request, {"events": [], "entitled": False, "reason": ent.reason})

    now = timezone.now()
    today = now.astimezone(timing.STOCKHOLM).date()
    first, last = period(request, today)
    horizon = today + dt.timedelta(days=MAX_DAYS)
    lat, lon = position_from(request)
    radius = _float(request.GET.get("radius_km"), DEFAULT_RADIUS_KM)
    counties, municipalities = request_area(request, lat, lon)
    chosen = set(areas.device_area_codes({"counties": counties, "municipalities": municipalities}))

    # Bara källor med rätt att visas i den betalda appen -- se events/rights.py. Under
    # utveckling kan lagrade källor förhandsvisas (EVENTS_APP_PREVIEW, bara med DEBUG)
    # även när en annan källa redan är "app-godkänd" men saknar rader -- annars blir
    # listan tom medan pipelinen visar Ticketmaster-data.
    allowed = list(app_sources())
    preview = False
    if settings.DEBUG and settings.EVENTS_APP_PREVIEW:
        stored = [source for source in ingest.SOURCES if rights_for(source).may_store()]
        extra = [source for source in stored if source not in allowed]
        if extra:
            allowed = list(dict.fromkeys([*allowed, *extra]))
            preview = True
        elif not allowed and stored:
            allowed = stored
            preview = True
    if not allowed:
        return _json(request, {
            "events": [], "entitled": True, "reason": "no_licensed_sources",
            "from": first.isoformat(), "to": last.isoformat(), "days": (last - first).days,
            "maxDays": MAX_DAYS, "dayCounts": {}, "attribution": "",
        })

    rows = []
    day_counts: Counter = Counter()
    # ?sort=fotboll,ishockey,konsert: sporten för sportevenemang, annars kategorin. Tomt = allt.
    kinds = {k.strip() for k in (request.GET.get("sort") or "").split(",") if k.strip()}
    for event, also in _merged(list(visible_between(now, today, horizon).filter(source__in=allowed))):
        if kinds and (timing.sport_for(event.source, event.category, event.genre, event.sub_genre, event.name)
                      or event.category) not in kinds:
            continue
        if chosen:
            if event.lat is None or event.lon is None or not _codes_at(event.lat, event.lon) & chosen:
                continue
        elif lat is not None and lon is not None and event.lat is not None and event.lon is not None:
            if haversine_km(lat, lon, event.lat, event.lon) > radius:
                continue
        day_counts[max(event.start_date, today).isoformat()] += 1
        if _in_period(event, first, last):
            rows.append(event_row(event, now, lat, lon, also=also))
    return _json(request, {
        "events": rows,
        "entitled": True,
        "from": first.isoformat(),
        "to": last.isoformat(),
        "days": (last - first).days,
        "maxDays": MAX_DAYS,
        "horizonEnd": horizon.isoformat(),
        "dayCounts": dict(sorted(day_counts.items())),
        "radiusKm": radius if not chosen and lat is not None and lon is not None else None,
        "counties": counties,
        "municipalities": municipalities,
        "preview": preview,
        "previewNote": PREVIEW_NOTE if preview else "",
        "attribution": timing.attribution({s for r in rows for s in r["sources"]}),
    })
