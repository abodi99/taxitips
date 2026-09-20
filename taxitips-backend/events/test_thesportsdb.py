"""
TheSportsDB: de svenska ligorna med stor publik, omgång för omgång (gratisnyckeln ger bara en
"nästa match"), arenan med koordinater och kapacitet, tider i UTC, och ett fel som syns.
"""

from __future__ import annotations

import datetime as dt
import io
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from core.models import SourceStatus
from events.models import Event
from events.sources import thesportsdb

START = dt.datetime(2026, 9, 19, tzinfo=dt.timezone.utc)
END = START + dt.timedelta(days=30)


class FakeResponse:
    def __init__(self, data, status=200):
        self.status_code, self._data = status, data

    def json(self):
        return self._data


def game(event_id, when, home, away, round_no, venue="15901"):
    return {"idEvent": event_id, "strTimestamp": when, "strTime": when[11:], "dateEvent": when[:10],
            "strHomeTeam": home, "strAwayTeam": away, "intRound": str(round_no), "idVenue": venue,
            "strStatus": "NS", "intHomeScore": None}


ROUNDS = {
    ("4347", 22): [game("1", "2026-09-20T12:00:00", "Djurgården", "Elfsborg", 22)],
    ("4347", 23): [game("2", "2026-10-10T13:00:00", "AIK", "Brommapojkarna", 23)],
    ("4347", 24): [game("3", "2026-11-30T13:00:00", "Malmö FF", "Hammarby", 24)],  # utanför fönstret
    ("4419", 2): [game("4", "2026-09-22T17:00:00", "Rögle BK", "Djurgårdens IF", 2, venue="25328")],
    ("5162", 0): [{**game("5", "2026-09-25T17:00:00", "AIK IF", "Modo Hockey", 0, venue="0"), "idHomeTeam": "137307"}],
}


class FakeSession:
    def __init__(self, fail=()):
        self.calls = []
        self.fail = set(fail)

    def get(self, url, params=None, timeout=None):
        path = url.rsplit("/", 1)[-1]
        params = dict(params or {})
        self.calls.append((path, params))
        if params.get("id") in self.fail:
            return FakeResponse({}, status=503)
        if path == "lookupleague.php":
            season = {"4347": "2026", "4419": "2026-2027", "5162": "2026-2027", "5136": "2025-2026"}[params["id"]]
            return FakeResponse({"leagues": [{"strCurrentSeason": season}]})
        if path == "eventsnextleague.php":
            first = {"4347": "22", "4419": "2", "5162": "0"}.get(params["id"])
            return FakeResponse({"events": [{"intRound": first}] if first is not None else None})
        if path == "eventsround.php":
            return FakeResponse({"events": ROUNDS.get((params["id"], int(params["r"])))})
        if path == "lookupteam.php":
            return FakeResponse({"teams": [{"idVenue": "25328"}]})
        if path == "lookupvenue.php":
            venue = {"15901": ("Tele2 Arena", "Stockholm, Sweden", "59.29081, 18.08534", "30000"),
                     "25328": ("Catena Arena", "Ängelholm", "56.225833, 12.845", "6310")}[params["id"]]
            return FakeResponse({"venues": [dict(zip(("strVenue", "strLocation", "strMap", "intCapacity"), venue))]})
        return FakeResponse({})


def client(session, slept=None):
    return thesportsdb.Client("123", session=session, sleep=(slept.append if slept is not None else (lambda s: None)),
                              clock=lambda: 0.0)


class FetchTests(SimpleTestCase):
    def test_rounds_in_the_window_with_the_venue(self):
        session = FakeSession()
        events, stats = thesportsdb.fetch_events(client(session), START, END)
        self.assertEqual(sorted(e["idEvent"] for e in events), ["1", "2", "4", "5"])  # 3 är i november
        self.assertTrue(stats["complete"])
        self.assertIn("inga kommande", stats["leagues"]["5136"]["note"])  # Handbollsligan utan säsong
        tele2 = next(e for e in events if e["idEvent"] == "1")["venue"]
        self.assertEqual((tele2["city"], tele2["lat"], tele2["capacity"]), ("Stockholm", 59.29081, 30000))
        # Arenan slås upp en gång, inte en gång per match.
        self.assertEqual(sum(1 for path, p in session.calls if path == "lookupvenue.php" and p["id"] == "15901"), 1)

    def test_the_row_is_the_schedule_in_utc_and_no_results_are_stored(self):
        events, _ = thesportsdb.fetch_events(client(FakeSession()), START, END)
        shl = next(e for e in events if e["idEvent"] == "4")
        row = thesportsdb.normalize(shl)
        self.assertEqual(row["name"], "SHL: Rögle BK – Djurgårdens IF")
        self.assertEqual(row["start_at"], dt.datetime(2026, 9, 22, 17, tzinfo=dt.timezone.utc))
        self.assertEqual((row["genre"], row["city"], row["lon"]), ("Ice Hockey", "Ängelholm", 12.845))
        self.assertNotIn("intHomeScore", thesportsdb.trimmed(shl))

    def test_calls_stay_under_thirty_a_minute(self):
        slept = []
        thesportsdb.fetch_events(client(FakeSession(), slept), START, END)
        self.assertTrue(all(s >= thesportsdb.MIN_INTERVAL_S for s in slept[1:]))
        self.assertLessEqual(60 / thesportsdb.MIN_INTERVAL_S, 30)

    def test_a_failing_league_is_reported_and_the_fetch_is_incomplete(self):
        _, stats = thesportsdb.fetch_events(client(FakeSession(fail={"4419"})), START, END)
        self.assertFalse(stats["complete"])
        self.assertTrue(stats["errors"][0].startswith("SHL"))


@override_settings(THESPORTSDB_API_KEY="123")
class PollTests(TestCase):
    def test_poll_stores_the_games_and_remembers_the_venues(self):
        fake = client(FakeSession())
        with mock.patch.object(thesportsdb, "Client", lambda key: fake), \
                mock.patch("django.utils.timezone.now", return_value=START):
            call_command("poll_events", "--source", "thesportsdb", "--days", "30", stdout=io.StringIO())
        self.assertEqual(Event.objects.filter(source="thesportsdb").count(), 4)
        status = SourceStatus.objects.get(source="thesportsdb")
        self.assertTrue(status.ok)
        self.assertIn("15901", status.detail["venues"])

    def test_a_game_without_venue_gets_the_home_teams_arena(self):
        events, _ = thesportsdb.fetch_events(client(FakeSession()), START, END)
        allsvenskan_hockey = next(e for e in events if e["idEvent"] == "5")
        self.assertEqual(allsvenskan_hockey["venue"]["name"], "Catena Arena")


class EndTimeTests(SimpleTestCase):
    def test_the_end_depends_on_the_sport(self):
        from events import ingest

        events, _ = thesportsdb.fetch_events(client(FakeSession()), START, END)
        rows = {e["idEvent"]: ingest.build_row(e, ingest.THESPORTSDB) for e in events}
        football, hockey = rows["1"], rows["4"]
        self.assertEqual(football["end_at"] - football["start_at"], dt.timedelta(minutes=115))
        self.assertEqual(hockey["end_at"] - hockey["start_at"], dt.timedelta(minutes=150))
        self.assertEqual((hockey["genre"], hockey["segment"]), ("Ice Hockey", "Sports"))
        self.assertIn("hockeymatch", hockey["end_note"])

    def test_a_venue_without_coordinates_is_placed_by_its_town(self):
        row = thesportsdb.normalize({**game("9", "2026-09-20T12:00:00", "Kalmar", "Häcken", 22, venue="7"),
                                     "sport_key": "football", "venue": {"name": "Guldfågeln Arena", "city": "Kalmar"}})
        self.assertIsNotNone(row["lat"])
        from core import areas
        self.assertEqual(areas.place_for(row["lat"], row["lon"])[1], "0880")  # Kalmar kommun
        gbg = thesportsdb.normalize({**game("10", "2026-09-20T12:00:00", "Häcken", "AIK", 22, venue="8"),
                                     "sport_key": "football", "venue": {"name": "Bravida Arena", "city": "Gothenburg"}})
        self.assertEqual(gbg["city"], "Göteborg")

    def test_the_town_in_the_team_name_is_the_last_resort(self):
        self.assertEqual(thesportsdb.town_in_team_name("Östersunds IK"), "Östersund")
        self.assertEqual(thesportsdb.town_in_team_name("BIK Karlskoga"), "Karlskoga")
        self.assertEqual(thesportsdb.town_in_team_name("Almtuna IS"), "Uppsala")
        self.assertEqual(thesportsdb.town_in_team_name("Okänt Lag"), "")

