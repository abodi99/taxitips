"""
PredictHQ Events API: evenemang i hela Sverige med förutsagt antal besökare.

Uppmätt 2026-09-13 för Sverige, 120 dagar (docs/data-sources.md):
- 3 031 evenemang (Ticketmaster: 246), 1 127 inom 30 dagar. Sport 1 583:
  ishockey 767, fotboll 357, basket 325.
- `phq_attendance` för 2 555; saknas för 473 scenföreställningar.
- `predicted_end` för 2 528. En riktig `end` (större än `start`) för 319 --
  `end == start` betyder att sluttiden är okänd.
- Heldag skrivs 00:00:00-23:59:59 lokalt (83 st). Flerdagars: duration > 86400 (101).
- 264 saknar venue-entitet och 82 saknar `geo.address.locality`; orten står då
  efter postnumret i `formatted_address`.
- "Gothenburg" och "Göteborg" förekommer båda. Två titlar har dubbelkodad UTF-8.
- `limit=500` gav 50 per sida. `x-ratelimit-limit: 200, 200;w=60`. `overflow: true`
  betyder att abonnemanget kapade svaret -- utan felkod.
- 183 av Ticketmasters 246 evenemang finns också här; se events.ingest.link_duplicates.
"""

from __future__ import annotations

import datetime as dt
import time

import requests

from events import timing

API_URL = "https://api.predicthq.com/v1/events/"
PAGE_SIZE = 50
# 200 anrop per 60 sekunder enligt svarshuvudena; 0,35 s håller sig under.
REQUEST_INTERVAL_S = 0.35
TIMEOUT_S = 30
MAX_ATTEMPTS = 4
# Skydd mot en next-länk som aldrig tar slut. 3 031 evenemang är 61 sidor.
MAX_PAGES = 400
# De kategorier där folk samlas på en plats och går hem samtidigt. Helgdagar,
# skollov, väderlarm och flygförseningar är andra sorters signaler.
CATEGORIES = (
    "concerts", "sports", "festivals", "performing-arts", "conferences", "expos", "community",
    "severe-weather", "disasters", "terror"
)
AIRPORT_CATEGORIES = ("airport-delays",)


class PredictHQError(RuntimeError):
    pass


class Client:
    def __init__(self, token: str, *, session=None, sleep=time.sleep, clock=time.monotonic) -> None:
        self.token = token
        self.session = session or requests.Session()
        self.sleep = sleep
        self.clock = clock
        self.call_count = 0
        self.rate_limit_remaining: int | None = None
        self._last_call = float("-inf")

    def get(self, url: str, params: dict | None = None) -> dict:
        status = None
        for attempt in range(MAX_ATTEMPTS):
            wait = REQUEST_INTERVAL_S - (self.clock() - self._last_call)
            if wait > 0:
                self.sleep(wait)
            self._last_call = self.clock()
            response = self.session.get(
                url,
                params=params,
                headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
                timeout=TIMEOUT_S,
            )
            self.call_count += 1
            status = response.status_code
            remaining = response.headers.get("x-ratelimit-remaining")
            if remaining is not None:
                try:
                    self.rate_limit_remaining = int(str(remaining).split(",")[0])
                except ValueError:
                    pass
            if status == 429:
                retry = response.headers.get("Retry-After") or response.headers.get("x-ratelimit-reset")
                try:
                    delay = min(float(str(retry).split(",")[0]), 60.0)
                except (TypeError, ValueError):
                    delay = 2 ** attempt
                self.sleep(delay)
                continue
            if status >= 500:
                self.sleep(2 ** attempt)
                continue
            if status != 200:
                raise PredictHQError(f"PredictHQ svarade {status}: {response.text[:200]}")
            return response.json()
        raise PredictHQError(f"PredictHQ svarade inte efter {MAX_ATTEMPTS} försök (senast {status})")


def fetch_events(client, start_date: dt.date, end_date: dt.date) -> tuple[list[dict], dict]:
    """Hämtar evenemang för Sverige, samt flygförseningar för Sverige och Danmark (CPH)."""
    
    # 1. Hämta vanliga evenemang för Sverige
    events: dict[str, dict] = {}
    stats = {"pages": 0, "count": 0, "overflow": False, "truncated": 0}
    
    def _fetch_query(country: str, cats: tuple, keep=lambda event: True):
        params = {
            "country": country,
            "category": ",".join(cats),
            "active.gte": start_date.isoformat(),
            "active.lte": end_date.isoformat(),
            "active.tz": "Europe/Stockholm",
            "state": "active,predicted",
            "sort": "start",
            "limit": PAGE_SIZE,
        }
        url, query = API_URL, params
        pages = 0
        while url:
            payload = client.get(url, query)
            query = None
            stats["pages"] += 1
            if pages == 0:
                stats["count"] += (payload.get("count") or 0)
            pages += 1
            if payload.get("overflow"):
                stats["overflow"] = True
            for event in payload.get("results") or []:
                if event.get("id") and keep(event):
                    events[event["id"]] = event
            url = payload.get("next")
            if url and pages >= MAX_PAGES:
                stats["truncated"] = 1
                break

    _fetch_query("SE", CATEGORIES + AIRPORT_CATEGORIES)
    # Från Danmark bara Kastrup: det är dit folk flyger för att sedan åka till Skåne.
    _fetch_query("DK", AIRPORT_CATEGORIES, keep=is_copenhagen_airport)

    stats["calls"] = client.call_count
    stats["rateLimitRemaining"] = client.rate_limit_remaining
    return list(events.values()), stats


_CPH = ("cph", "copenhagen", "kastrup", "københavn", "kobenhavn", "köpenhamn")


def is_copenhagen_airport(event: dict) -> bool:
    """Flygförsening på Köpenhamns flygplats (Kastrup), inte Billund eller Aalborg."""
    names = [event.get("title") or ""] + [
        f"{e.get('name') or ''} {e.get('formatted_address') or ''}" for e in event.get("entities") or []
    ]
    text = " ".join(names).lower()
    return any(word in text for word in _CPH)


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


def _venue(event: dict) -> dict:
    return next((e for e in event.get("entities") or [] if e.get("type") == "venue"), None) or {}


def normalize(event: dict) -> dict | None:
    """Ett PredictHQ-evenemang som fält för events.Event, eller None om det inte går att använda."""
    if not event.get("id") or event.get("private"):
        return None
    state = event.get("state") or "active"
    if state not in ("active", "predicted"):
        return None
    start = _parse_dt(event.get("start"))
    start_local = event.get("start_local") or ""
    if start is None or len(start_local) < 10:
        return None
    try:
        start_date = dt.date.fromisoformat(start_local[:10])
    except ValueError:
        return None

    end = _parse_dt(event.get("end"))
    end_local = event.get("end_local") or ""
    all_day = start_local.endswith("T00:00:00") and end_local.endswith("T23:59:59")
    geo = event.get("geo") or {}
    address = geo.get("address") or {}
    coords = (geo.get("geometry") or {}).get("coordinates") or event.get("location") or [None, None]
    formatted = timing.fix_mojibake(address.get("formatted_address") or "").removesuffix(", Sweden").strip()
    venue = _venue(event)
    labels = [label["label"] for label in event.get("phq_labels") or [] if label.get("label")]
    attendance = event.get("phq_attendance")
    return {
        "external_id": str(event["id"])[:120],
        "name": timing.fix_mojibake(event.get("title") or "").strip()[:300],
        # PredictHQ har ingen publik evenemangssida. Länken kommer från en
        # länkad Ticketmaster-post när en sådan finns.
        "url": "",
        "source_status": state,
        "segment": (event.get("category") or "")[:60],
        "genre": (labels[0] if labels else "")[:60],
        "sub_genre": (labels[1] if len(labels) > 1 else "")[:60],
        "labels": labels,
        "start_date": start_date,
        "start_at": None if all_day else start,
        "time_known": not all_day,
        # end == start betyder okänd sluttid hos PredictHQ.
        "source_end": end if end and end > start and not all_day else None,
        "predicted_end": _parse_dt(event.get("predicted_end")),
        "multi_day": (event.get("duration") or 0) > 86400,
        "venue_id": str(venue.get("entity_id") or "")[:60],
        "venue_name": timing.fix_mojibake(venue.get("name") or formatted.split(",")[0]).strip()[:200],
        "address": formatted[:200],
        "city": timing.swedish_city(address.get("locality") or timing.city_from_address(formatted))[:100],
        "postal_code": (address.get("postcode") or "")[:20],
        "lat": _float(coords[1]) if len(coords) > 1 else None,
        "lon": _float(coords[0]) if coords else None,
        "attendance": int(attendance) if attendance else None,
        "rank": event.get("rank"),
        "local_rank": event.get("local_rank"),
    }


def trimmed(event: dict) -> dict:
    """Det av svaret som förklarar raden. Konsumtionsprognoser och påverkansmönster sparas inte."""
    keep = ("id", "title", "category", "phq_labels", "rank", "local_rank", "phq_attendance", "start", "end",
            "start_local", "end_local", "predicted_end", "duration", "timezone", "state")
    geo = event.get("geo") or {}
    return {
        **{key: event.get(key) for key in keep},
        "venue": _venue(event),
        "geo": {"geometry": geo.get("geometry"), "address": geo.get("address")},
    }
