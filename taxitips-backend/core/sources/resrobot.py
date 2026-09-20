"""
Trafiklab ResRobot v2.1: nästa resa mot samma slutstation när ett tåg är inställt.

Trafikverkets avgångar vid stationen säger när nästa TÅG går därifrån, men inte åt
vilket håll, och inte om en buss från hållplatsen utanför tar resenären dit.
Reseplaneraren svarar på den frågan: "hur kommer jag från Lindome till Göteborg C nu?".

Uppmätt 2026-09-15, Lindome 06:02, tåg 3022 mot Göteborg C inställt:

* Avgångstavlan saknade 3022 men hade 3023 åt andra hållet. `planRtTs` var
  1970-01-01, alltså ingen realtidsplan: inställningen låg redan i tidtabellen. Vi
  litar inte på att det alltid är så, och hoppar över varje resa som använder ett tåg
  Trafikverket anger som inställt.
* Reseplaneraren gav tåg 3174 06:13 mot Göteborg C -- rätt riktning. Trafikverkets
  "nästa avgång från stationen" räknar tåg åt båda hållen.

Licens CC0. Bronze-nyckeln tillåter 45 anrop per minut och 30 000 per månad. Därför:

* bara inställda avgångar utan insatt ersättningstrafik som går inom `ACTIONABLE`;
* högst `CALLS_PER_RUN` anrop per pollrunda (rälspollen går var 90:e sekund);
* månadsräknaren och hållplats-id:n per station ligger i rälskällans
  `source_status.detail["resrobot"]`, samma mönster som Swedavia-budgeten;
* ett svar återanvänds i `ANSWER_TTL` via källhändelsens rådata.

Svar saknas, budgeten är slut eller API:t fallerar: då gäller Trafikverkets nästa
avgång från stationen, som förut. Nyckeln går som query-parameter (API:ts krav) och
loggas aldrig -- fel loggas med typnamn eller felkod, aldrig med URL.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from core.time_limits import reraise_time_limit

log = logging.getLogger(__name__)

BASE_URL = "https://api.resrobot.se/v2.1/"
TZ = ZoneInfo("Europe/Stockholm")
# Under Bronze-taket 30 000, med marginal för manuella anrop och andra miljöer.
MONTHLY_BUDGET = 25_000
CALLS_PER_RUN = 20
ACTIONABLE = timedelta(hours=2)
ANSWER_TTL = timedelta(minutes=30)
STOP_RADIUS_M = 600
NUM_TRIPS = 3
SAME_DEPARTURE_MIN = 2
# Spärr: efter så många fel i en runda görs inga anrop förrän pausen gått ut, även i
# nästa runda. Första liverundan via beat 2026-09-15 fick INT_HAFAS_CONNECTION_ERROR på
# varje hållplatsuppslag; utan spärr hade ett ihållande fel kostat 20 anrop var 90:e
# sekund och tömt månadsbudgeten på ett dygn.
MAX_ERRORS_PER_RUN = 3
ERROR_PAUSE = timedelta(minutes=10)
TIMEOUT_S = 15


def load_state(previous: dict | None, now: datetime) -> dict:
    """Månadsräknaren och hållplats-id:n från förra rundan; räknaren nollas per kalendermånad."""
    state = dict(previous or {})
    month = now.astimezone(TZ).strftime("%Y-%m")
    if state.get("month") != month:
        state = {"month": month, "calls": 0, "stops": dict(state.get("stops") or {})}
    state.setdefault("calls", 0)
    state.setdefault("stops", {})
    return state


def _product(leg: dict) -> dict:
    product = leg.get("Product") or leg.get("ProductAtStop") or {}
    if isinstance(product, list):
        product = product[0] if product else {}
    return product if isinstance(product, dict) else {}


def mode_of(leg: dict) -> str:
    category = str(_product(leg).get("catOutL") or "").lower()
    for word, mode in (("buss", "buss"), ("tunnelbana", "tunnelbana"), ("spårvagn", "spårvagn"),
                       ("tåg", "tåg"), ("färja", "båt"), ("båt", "båt")):
        if word in category:
            return mode
    return "annat"


def _point_time(point: dict) -> datetime | None:
    day = point.get("rtDate") or point.get("date")
    clock = point.get("rtTime") or point.get("time")
    if not day or not clock:
        return None
    try:
        return datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=TZ)
    except ValueError:
        return None


def first_alternative(body: dict, when: datetime, cancelled_trains) -> dict | None:
    """
    Första resan som går vid eller efter `when` utan ett inställt tåg och utan
    inställd eller onåbar delsträcka. Rent: inga anrop.
    """
    cancelled = {str(t) for t in cancelled_trains}
    for trip in body.get("Trip") or []:
        legs = (trip.get("LegList") or {}).get("Leg") or []
        if isinstance(legs, dict):
            legs = [legs]
        journeys = [leg for leg in legs if leg.get("type") == "JNY"]
        if not journeys:
            continue
        trains = [str(_product(leg).get("num") or "") for leg in journeys if mode_of(leg) == "tåg"]
        if any(num and num in cancelled for num in trains):
            continue
        if any(leg.get("cancelled") is True or leg.get("reachable") is False for leg in journeys):
            continue
        start = _point_time(legs[0].get("Origin") or {})
        if start is None or start < when:
            continue
        first = journeys[0]
        first_start = _point_time(first.get("Origin") or {})
        # ResRobot känner inte alltid till inställningen. För SL:s pendeltåg är `num`
        # linjenumret (43), inte tågnumret, och reseplaneraren föreslog det inställda
        # tåget självt "om 0 min" (live 2026-09-15). Ett tåg inom SAME_DEPARTURE_MIN
        # från den inställda avgången räknas därför som samma tåg.
        if (
            mode_of(first) == "tåg" and first_start is not None
            and abs((first_start - when).total_seconds()) <= SAME_DEPARTURE_MIN * 60
        ):
            continue
        product = _product(first)
        label = " ".join(p for p in (str(product.get("catOutL") or "").strip(), str(product.get("num") or "").strip()) if p)
        return {
            "basis": "resrobot",
            "departs_at": start.isoformat(),
            "mode": mode_of(first),
            "label": label or mode_of(first),
            "trains": [t for t in trains if t],
            "changes": len(journeys) - 1,
        }
    return None


def nearest_station_stop(body: dict) -> str | None:
    """Hållplatsen som är järnvägsstationen, annars den närmaste."""
    stops = [
        item.get("StopLocation") for item in (body.get("stopLocationOrCoordLocation") or [])
        if isinstance(item, dict) and item.get("StopLocation")
    ]
    if not stops:
        return None
    stops.sort(key=lambda s: float(s.get("dist") or 0))
    for stop in stops:
        if "station" in str(stop.get("name") or "").lower():
            return str(stop.get("extId"))
    return str(stops[0].get("extId"))


def previous_answers(now: datetime) -> dict[str, dict]:
    """Förra rundornas ResRobot-svar per tips, ur rälskällans rådata."""
    from core.models import SourceEvent

    out: dict[str, dict] = {}
    rows = SourceEvent.objects.filter(source="trafikverket_rail", active_to__gt=now).values_list("external_id", "raw")
    for external_id, raw in rows:
        try:
            data = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except ValueError:
            continue
        answer = data.get("alternative") if isinstance(data, dict) else None
        if isinstance(answer, dict) and answer.get("basis") == "resrobot":
            out[external_id] = answer
    return out


class AlternativeFinder:
    """Anropsbar för trafikverket_rail.build_alerts: (tips-id, station, slutstation, tid, inställda tåg) -> svar."""

    def __init__(self, api_key: str, *, stations: dict, now: datetime, state: dict | None = None,
                 previous: dict | None = None, session: requests.Session | None = None) -> None:
        self.api_key = api_key
        self.stations = stations
        self.now = now
        self.state = load_state(state, now)
        self.previous = previous or {}
        self.session = session or requests.Session()
        self.run: Counter = Counter()

    def __call__(self, external_id: str, sig: str, to_sig: str, when: datetime, cancelled_trains) -> dict | None:
        if not (self.now - timedelta(minutes=5) <= when <= self.now + ACTIONABLE):
            self.run["outside_window"] += 1
            return None
        cached = self.previous.get(external_id)
        if cached and self._fresh(cached) and not set(cached.get("trains") or []) & {str(t) for t in cancelled_trains}:
            self.run["reused"] += 1
            return cached
        origin = self._stop(sig)
        destination = self._stop(to_sig) if origin else None
        if not origin or not destination or origin == destination:
            self.run["no_stop"] += 1
            return None
        local = when.astimezone(TZ)
        body = self._get("trip", originId=origin, destId=destination,
                         date=local.strftime("%Y-%m-%d"), time=local.strftime("%H:%M"), numF=NUM_TRIPS)
        if body is None:
            return None
        answer = first_alternative(body, when, cancelled_trains)
        if answer is None:
            self.run["no_trip"] += 1
            return None
        answer["checked_at"] = self.now.isoformat()
        self.run["answered"] += 1
        return answer

    def detail(self) -> dict:
        return {**self.state, "budget": MONTHLY_BUDGET, "run": dict(self.run)}

    def _fresh(self, answer: dict) -> bool:
        try:
            checked = datetime.fromisoformat(answer.get("checked_at") or "")
        except ValueError:
            return False
        return self.now - checked < ANSWER_TTL

    def _stop(self, sig: str | None) -> str | None:
        if not sig:
            return None
        stops = self.state["stops"]
        if sig in stops:
            return stops[sig] or None
        station = self.stations.get(sig)
        if station is None or station.lat is None or station.lon is None:
            return None
        body = self._get("location.nearbystops", originCoordLat=station.lat, originCoordLong=station.lon,
                         r=STOP_RADIUS_M, maxNo=5)
        if body is None:
            return None
        # Även "ingen hållplats" sparas, så att samma station inte frågas varje runda.
        stops[sig] = nearest_station_stop(body) or ""
        return stops[sig] or None

    def _paused(self) -> bool:
        try:
            until = datetime.fromisoformat(self.state.get("paused_until") or "")
        except ValueError:
            return False
        return self.now < until

    def _failed(self) -> None:
        self.run["errors"] += 1
        if self.run["errors"] >= MAX_ERRORS_PER_RUN and not self._paused():
            until = self.now + ERROR_PAUSE
            self.state["paused_until"] = until.isoformat()
            log.warning("resrobot: %d fel i rad, pausar till %s", self.run["errors"], until.astimezone(TZ).strftime("%H:%M"))

    def _get(self, path: str, **params) -> dict | None:
        if self._paused():
            self.run["paused"] += 1
            return None
        if self.state["calls"] >= MONTHLY_BUDGET:
            self.run["budget_exhausted"] += 1
            return None
        if self.run["calls"] >= CALLS_PER_RUN:
            self.run["run_limit"] += 1
            return None
        self.state["calls"] += 1
        self.run["calls"] += 1
        try:
            res = self.session.get(
                BASE_URL + path, params={**params, "format": "json", "accessId": self.api_key}, timeout=TIMEOUT_S,
            )
            body = res.json()
        except Exception as exc:  # nätverk, timeout, ogiltig JSON: reservläget tar över
            reraise_time_limit(exc)
            log.warning("resrobot: %s misslyckades: %s", path, type(exc).__name__)
            self._failed()
            return None
        code = body.get("errorCode") if isinstance(body, dict) else None
        if code == "SVC_NO_RESULT":
            return {}
        if res.status_code >= 400 or code or not isinstance(body, dict):
            log.warning("resrobot: %s svarade %s", path, code or res.status_code)
            self._failed()
            return None
        return body
