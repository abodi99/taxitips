"""
TheSportsDB (https://www.thesportsdb.com): matcher i de svenska ligorna med stor publik --
fotboll, ishockey och handboll -- där en taxiförare kan räkna med mycket folk utanför arenan.

Bara spelschemat: datum, tid, lag, liga och arena (med arenans koordinater och kapacitet). Inga
resultat, ingen publiksiffra: kapaciteten säger hur stor arenan är, inte hur många som kommer.

Uppmätt 2026-09-19 med gratisnyckeln `123` (docs_api_guide):

- 30 anrop per minut. Därför MIN_INTERVAL_S mellan anropen, och 429 väntar en minut.
- Gratisnyckeln begränsar listorna: `eventsnextleague` ger 1 match och `eventsseason` 5. Hela
  omgångar (`eventsround`) ges fullt ut: Allsvenskan 8 matcher, SHL 7. Därför: nästa match ger
  aktuell omgång, sedan en fråga per omgång framåt tills fönstret är slut. Ligor utan omgångsnummer
  (Hockey Allsvenskan har intRound 0) ger alla matcher i omgång 0, i dag 50.
- Arenan (`lookupvenue`) har `strMap` ("59.29081, 18.08534") och `intCapacity`. Den slås upp en
  gång per arena och körning.
- Tiderna (`strTimestamp`) är UTC utan tidszon i strängen.

Villkoren (docs_terms_of_use, hämtade 2026-09-19): "You cannot publish apps to an appstore unless
you are a paid subscriber", och källan ska anges med länk. Lagring nämns inte. Visning i förarappen
kräver alltså den betalda planen; se config/settings.py EVENT_SOURCES.
"""

from __future__ import annotations

import datetime as dt
import time

import requests

BASE_URL = "https://www.thesportsdb.com/api/v1/json"
TIMEOUT_S = 20
MAX_ATTEMPTS = 3
# 30 anrop per minut på gratisnyckeln: 2,5 s ger högst 24.
MIN_INTERVAL_S = 2.5
RATE_PAUSE_S = 61
# Omgångar framåt per liga och körning; fönstret (horisonten) stoppar tidigare.
MAX_ROUNDS = 8

# Ligorna med stor publik. id enligt `search_all_leagues.php?c=Sweden` 2026-09-19. Superettan
# finns inte hos TheSportsDB; Damallsvenskan, Division 1, Svenska Cupen och SDHL har för liten
# publik för att en förare ska vänta vid arenan.
LEAGUES = (
    {"id": "4347", "sport": "football", "label": "Allsvenskan"},
    {"id": "4419", "sport": "hockey", "label": "SHL"},
    {"id": "5162", "sport": "hockey", "label": "Hockey Allsvenskan"},
    {"id": "5136", "sport": "handball", "label": "Handbollsligan"},
)
GENRE = {"football": "Soccer", "hockey": "Ice Hockey", "handball": "Handball"}
# TheSportsDB skriver orterna på engelska eller som stadsdel.
CITY = {"gothenburg": "Göteborg", "johanneshov": "Stockholm", "solna": "Solna"}
SPORT_LABEL = {"football": "Fotboll", "hockey": "Ishockey", "handball": "Handboll"}
# Lag vars namn inte bär orten, för matcher där källan saknar arena.
TEAM_TOWN = {"almtuna": "Uppsala", "modo": "Örnsköldsvik", "brynäs": "Gävle", "frölunda": "Göteborg"}


class TheSportsDbError(RuntimeError):
    pass


class Client:
    def __init__(self, api_key: str = "123", *, session=None, sleep=time.sleep, clock=time.monotonic) -> None:
        self.api_key = api_key or "123"
        self.session = session or requests.Session()
        self.sleep = sleep
        self.clock = clock
        self.call_count = 0
        self._last_call = float("-inf")

    def get(self, path: str, **params) -> dict:
        status = None
        for attempt in range(MAX_ATTEMPTS):
            wait = MIN_INTERVAL_S - (self.clock() - self._last_call)
            if wait > 0:
                self.sleep(wait)
            self._last_call = self.clock()
            response = self.session.get(f"{BASE_URL}/{self.api_key}/{path}", params=params, timeout=TIMEOUT_S)
            self.call_count += 1
            status = response.status_code
            if status == 429:
                self.sleep(RATE_PAUSE_S)
                continue
            if status >= 500:
                self.sleep(2 ** attempt)
                continue
            if status != 200:
                raise TheSportsDbError(f"TheSportsDB svarade {status} på {path}")
            try:
                return response.json() or {}
            except ValueError as exc:
                raise TheSportsDbError(f"TheSportsDB gav inget JSON på {path}") from exc
        raise TheSportsDbError(f"TheSportsDB svarade inte efter {MAX_ATTEMPTS} försök (senast {status})")


def _utc(event: dict) -> dt.datetime | None:
    raw = event.get("strTimestamp") or ""
    if not raw and event.get("dateEvent"):
        raw = f"{event['dateEvent']}T{event.get('strTime') or '00:00:00'}"
    try:
        value = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)


def _round(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _venue(client: Client, venue_id, cache: dict) -> dict:
    """Arenans stad, koordinater och kapacitet, en uppslagning per arena."""
    key = str(venue_id or "")
    if not key or key == "0":
        return {}
    if key not in cache:
        venues = client.get("lookupvenue.php", id=key).get("venues") or []
        v = venues[0] if venues else {}
        lat = lon = None
        try:
            lat, lon = (float(x) for x in str(v.get("strMap") or "").split(","))
        except ValueError:
            pass
        city = (v.get("strLocation") or "").split(",")[0].strip()
        cache[key] = {
            "name": v.get("strVenue") or "", "city": CITY.get(city.lower(), city),
            "lat": lat, "lon": lon, "capacity": _round(v.get("intCapacity")),
        }
    return cache[key]


def _home_venue_id(client: Client, team_id, cache: dict) -> str:
    """Hemmalagets arena, när matchen själv saknar arena (Hockey Allsvenskan)."""
    key = f"team:{team_id}"
    if not team_id:
        return ""
    if key not in cache:
        teams = client.get("lookupteam.php", id=str(team_id)).get("teams") or []
        cache[key] = str((teams[0] if teams else {}).get("idVenue") or "")
    return cache[key]


def fetch_events(client: Client, start: dt.datetime, end: dt.datetime, venues: dict | None = None) -> tuple[list[dict], dict]:
    """Matcherna i LEAGUES mellan start och slut, och vad varje liga gav."""
    venues = {} if venues is None else venues
    events: dict[str, dict] = {}
    stats: dict = {"leagues": {}, "errors": []}
    for league in LEAGUES:
        report = {"label": league["label"], "sport": league["sport"], "season": None, "rounds": [], "games": 0}
        stats["leagues"][league["id"]] = report
        try:
            info = (client.get("lookupleague.php", id=league["id"]).get("leagues") or [{}])[0]
            season = info.get("strCurrentSeason")
            report["season"] = season
            upcoming = client.get("eventsnextleague.php", id=league["id"]).get("events") or []
            if not season or not upcoming:
                report["note"] = "inga kommande matcher hos källan (säsongen kan saknas)"
                continue
            first_round = _round(upcoming[0].get("intRound"))
            rounds = [0] if not first_round else range(first_round, first_round + MAX_ROUNDS)
            for number in rounds:
                games = client.get("eventsround.php", id=league["id"], r=number, s=season).get("events") or []
                report["rounds"].append({"round": number, "games": len(games)})
                if not games:
                    break
                times = [t for t in (_utc(g) for g in games) if t]
                for game in games:
                    when = _utc(game)
                    if when is None or not (start <= when <= end) or not game.get("idEvent"):
                        continue
                    venue_id = game.get("idVenue")
                    if not venue_id or str(venue_id) == "0":
                        venue_id = _home_venue_id(client, game.get("idHomeTeam"), venues)
                    game = {**game, "idVenue": venue_id, "league_label": league["label"], "sport_key": league["sport"],
                            "venue": _venue(client, venue_id, venues)}
                    events[str(game["idEvent"])] = game
                    report["games"] += 1
                if times and min(times) > end:
                    break
        except TheSportsDbError as exc:
            stats["errors"].append(f"{league['label']}: {exc}")
            report["error"] = str(exc)
    stats["calls"] = client.call_count
    stats["complete"] = not stats["errors"]
    return list(events.values()), stats


def town_in_team_name(team: str) -> str:
    """"Östersunds IK" -> "Östersund", "Visby-Roma HK" -> "Visby". Tomt när inget ord är en ort."""
    from core.areas import municipality_point
    from core.geo import CITY_COORDS

    for club, town in TEAM_TOWN.items():
        if club in team.lower():
            return town
    known = {name.lower(): name for name in CITY_COORDS}
    for word in team.replace("-", " ").split():
        for candidate in (word, word[:-1] if word.lower().endswith("s") else ""):
            if len(candidate) < 3:
                continue
            if candidate.lower() in known:
                return known[candidate.lower()]
            if municipality_point(candidate):
                return candidate
    return ""


def normalize(event: dict) -> dict | None:
    """Spelschemat som en evenemangsrad. Inga resultat."""
    start = _utc(event)
    if start is None or not event.get("idEvent"):
        return None
    sport = event.get("sport_key") or ""
    venue = event.get("venue") or {}
    city = (venue.get("city") or event.get("strCity") or "").strip()
    city = CITY.get(city.lower(), city)
    lat, lon = venue.get("lat"), venue.get("lon")
    if (lat is None or lon is None) and not city:
        # Ingen arena alls hos källan (flera lag i Hockey Allsvenskan): orten i hemmalagets namn.
        city = town_in_team_name(event.get("strHomeTeam") or "")
    if (lat is None or lon is None) and city:
        # Arenan saknar koordinater hos källan (t.ex. Guldfågeln Arena): ortens centrum, annars
        # kommunens mitt -- nog för att matchen hamnar i rätt område för föraren.
        from core.areas import municipality_point
        from core.geo import CITY_COORDS

        lat, lon = CITY_COORDS.get(city) or municipality_point(city) or (None, None)
    home, away = event.get("strHomeTeam") or "?", event.get("strAwayTeam") or "?"
    league = event.get("league_label") or event.get("strLeague") or ""
    return {
        "external_id": str(event["idEvent"]),
        "name": (f"{league}: {home} – {away}" if league else f"{home} – {away}")[:300],
        "url": f"https://www.thesportsdb.com/event/{event['idEvent']}",
        "source_status": str(event.get("strStatus") or "")[:30],
        "segment": "Sports",
        "genre": GENRE.get(sport, event.get("strSport") or ""),
        "sub_genre": "",
        "start_date": start.date(),
        "start_at": start,
        "time_known": bool(event.get("strTime") or event.get("strTimestamp")),
        "source_end": None,
        "multi_day": False,
        "venue_id": str(event.get("idVenue") or "")[:60],
        "venue_name": (venue.get("name") or event.get("strVenue") or "").strip()[:200],
        "address": "",
        "city": city[:100],
        "postal_code": "",
        "lat": lat,
        "lon": lon,
    }


def trimmed(event: dict) -> dict:
    """Det som sparas av källans svar: schemat och arenan, inga resultat."""
    venue = event.get("venue") or {}
    return {
        "id": event.get("idEvent"), "league": event.get("league_label"), "season": event.get("strSeason"),
        "round": event.get("intRound"), "timestamp": event.get("strTimestamp"),
        "home": event.get("strHomeTeam"), "away": event.get("strAwayTeam"),
        "venue": venue.get("name") or event.get("strVenue"), "capacity": venue.get("capacity"),
    }
