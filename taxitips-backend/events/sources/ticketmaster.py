"""
Ticketmaster Discovery API v2: evenemang i hela Sverige.

Uppmätt 2026-09-12 (docs/data-sources.md):
- 315 kommande svenska evenemang, 55 inom 30 dagar. Tunt: Avicii Arena har 0,
  Malmö Arena och Strawberry Arena 2 var. Källan räcker inte ensam.
- Alla har koordinat. 28 har sluttid, 11 saknar starttid (TBA).
- `dates.end.localTime` är en kopia av startens localTime, medan
  `dates.end.dateTime` är rätt. Bara dateTime används.

Regler från dokumentationen: 5000 anrop per dygn, 5 per sekund, och
"we only support retrieving the 1000th item. i.e. (size * page < 1000)".

Villkoren förbjuder att "derive revenues from the use or provision of the
Ticketmaster API" -- avtal behövs innan datan når betalande kunder.
"""

from __future__ import annotations

import datetime as dt
import time

import requests

API_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
PAGE_SIZE = 200
DEEP_PAGING_LIMIT = 1000
# 5 anrop per sekund enligt dokumentationen; en kvarts sekund ger marginal.
REQUEST_INTERVAL_S = 0.25
WINDOW = dt.timedelta(days=30)
# Ett fönster med 1000+ träffar delas i två tills det här. Därunder hämtas det
# som går, och avkapningen bokförs i stället för att tyst tappa evenemang.
MIN_WINDOW = dt.timedelta(hours=12)
TIMEOUT_S = 20
MAX_ATTEMPTS = 4


class TicketmasterError(RuntimeError):
    pass


class Client:
    def __init__(self, api_key: str, *, session=None, sleep=time.sleep, clock=time.monotonic) -> None:
        self.api_key = api_key
        self.session = session or requests.Session()
        self.sleep = sleep
        self.clock = clock
        self.call_count = 0
        self.rate_limit_available: int | None = None
        self._last_call = float("-inf")

    def get(self, **params) -> dict:
        status = None
        for attempt in range(MAX_ATTEMPTS):
            wait = REQUEST_INTERVAL_S - (self.clock() - self._last_call)
            if wait > 0:
                self.sleep(wait)
            self._last_call = self.clock()
            response = self.session.get(
                API_URL,
                params={**params, "apikey": self.api_key},
                headers={"Accept": "application/json"},
                timeout=TIMEOUT_S,
            )
            self.call_count += 1
            status = response.status_code
            available = response.headers.get("Rate-Limit-Available")
            if available is not None:
                try:
                    self.rate_limit_available = int(available)
                except ValueError:
                    pass
            if status == 429:
                if self.rate_limit_available == 0:
                    raise TicketmasterError("Ticketmaster-kvoten för dygnet är slut (Rate-Limit-Available: 0)")
                self.sleep(2 ** attempt)
                continue
            if status >= 500:
                self.sleep(2 ** attempt)
                continue
            if status != 200:
                # Svarstexten, aldrig URL:en: nyckeln står i query-strängen.
                raise TicketmasterError(f"Ticketmaster svarade {status}: {response.text[:200]}")
            return response.json()
        raise TicketmasterError(f"Ticketmaster svarade inte efter {MAX_ATTEMPTS} försök (senast {status})")


def _fmt(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_events(client, start: dt.datetime, end: dt.datetime, *, country: str = "SE") -> tuple[list[dict], dict]:
    """Alla evenemang som startar i [start, end), i 30-dagarsfönster. (evenemang, statistik)."""
    events: dict[str, dict] = {}
    stats = {"windows": 0, "splits": 0, "truncated": 0}
    cursor = start
    while cursor < end:
        window_end = min(cursor + WINDOW, end)
        _fetch_window(client, cursor, window_end, country, events, stats)
        cursor = window_end
    stats["calls"] = client.call_count
    stats["rateLimitAvailable"] = client.rate_limit_available
    return list(events.values()), stats


def _fetch_window(client, start, end, country, events, stats) -> None:
    params = {
        "countryCode": country,
        "size": PAGE_SIZE,
        "sort": "date,asc",
        "startDateTime": _fmt(start),
        "endDateTime": _fmt(end),
        # TBA: datumet är känt men inte tiden -- det hör hemma i en kalender.
        # TBD: inte ens datumet är känt -- det gör det inte.
        "includeTBA": "yes",
        "includeTBD": "no",
        "includeTest": "no",
    }
    first = client.get(**params, page=0)
    page_info = first.get("page") or {}
    total = page_info.get("totalElements", 0)
    if total >= DEEP_PAGING_LIMIT and end - start > MIN_WINDOW:
        middle = start + (end - start) / 2
        stats["splits"] += 1
        _fetch_window(client, start, middle, country, events, stats)
        _fetch_window(client, middle, end, country, events, stats)
        return

    stats["windows"] += 1
    if total >= DEEP_PAGING_LIMIT:
        stats["truncated"] += 1
    _collect(first, events)
    pages = page_info.get("totalPages", 1)
    page = 1
    while page < pages and page * PAGE_SIZE < DEEP_PAGING_LIMIT:
        _collect(client.get(**params, page=page), events)
        page += 1


def _collect(payload: dict, events: dict) -> None:
    for event in (payload.get("_embedded") or {}).get("events", []):
        if event.get("id"):
            events[event["id"]] = event


def _parse_dt(value) -> dt.datetime | None:
    if not value:
        return None
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _name(obj) -> str:
    name = ((obj or {}).get("name") or "").strip()
    return "" if name == "Undefined" else name


def _venue(event: dict) -> dict:
    return ((event.get("_embedded") or {}).get("venues") or [{}])[0] or {}


def _primary_classification(event: dict) -> dict:
    classes = event.get("classifications") or []
    return next((c for c in classes if c.get("primary")), classes[0] if classes else {}) or {}


def normalize(event: dict) -> dict | None:
    """Ett Ticketmaster-evenemang som fält för events.Event, eller None om det inte går att använda."""
    if not event.get("id") or event.get("test"):
        return None
    dates = event.get("dates") or {}
    start = dates.get("start") or {}
    end = dates.get("end") or {}
    if start.get("dateTBD") or not start.get("localDate"):
        return None
    try:
        start_date = dt.date.fromisoformat(start["localDate"])
    except ValueError:
        return None

    time_known = not (start.get("timeTBA") or start.get("dateTBA") or start.get("noSpecificTime"))
    start_at = _parse_dt(start.get("dateTime")) if time_known else None
    if start_at is None:
        time_known = False
    # end.localTime är en kopia av startens localTime ("18:00" -> "18:00" när
    # dateTime säger 16:00Z -> 17:00Z). Bara dateTime går att lita på.
    source_end = None if end.get("noSpecificTime") else _parse_dt(end.get("dateTime"))

    venue = _venue(event)
    location = venue.get("location") or {}
    classification = _primary_classification(event)
    return {
        "external_id": str(event["id"])[:120],
        "name": (event.get("name") or "").strip()[:300],
        "url": (event.get("url") or "")[:500],
        "source_status": ((dates.get("status") or {}).get("code") or "")[:30],
        "segment": _name(classification.get("segment"))[:60],
        "genre": _name(classification.get("genre"))[:60],
        "sub_genre": _name(classification.get("subGenre"))[:60],
        "sub_type": _name(classification.get("subType")),
        "start_date": start_date,
        "start_at": start_at,
        "time_known": time_known,
        "source_end": source_end,
        "multi_day": bool(dates.get("spanMultipleDays")),
        "venue_id": str(venue.get("id") or "")[:60],
        "venue_name": (venue.get("name") or "").strip()[:200],
        "address": ((venue.get("address") or {}).get("line1") or "").strip()[:200],
        "city": ((venue.get("city") or {}).get("name") or "").strip()[:100],
        "postal_code": (venue.get("postalCode") or "")[:20],
        "lat": _float(location.get("latitude")),
        "lon": _float(location.get("longitude")),
    }


def trimmed(event: dict) -> dict:
    """Det av svaret som förklarar raden. Bilder, säljinfo och fritext sparas inte."""
    venue = _venue(event)
    classification = _primary_classification(event)
    return {
        "id": event.get("id"),
        "name": event.get("name"),
        "url": event.get("url"),
        "dates": event.get("dates"),
        "classification": {
            key: _name(classification.get(key)) for key in ("segment", "genre", "subGenre", "type", "subType")
        },
        "venue": {key: venue.get(key) for key in ("id", "name", "address", "city", "postalCode", "location")},
    }
