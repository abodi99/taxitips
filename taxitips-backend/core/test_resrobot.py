"""
ResRobot som nästa resa mot samma slutstation: rätt resa, aldrig ett inställt tåg,
inom budgeten, och nyckeln syns aldrig i loggen.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from core.scoring import classify
from core.sources import resrobot
from core.sources.trafikverket_rail import Station, build_alerts

TZ = ZoneInfo("Europe/Stockholm")
WHEN = datetime(2026, 9, 15, 6, 2, tzinfo=TZ)
KEY = "test-key-never-logged"
STATIONS = {"Ldo": Station("Ldo", "Lindome", 57.5767, 12.0747), "G": Station("G", "Göteborg C", 57.7089, 11.9730)}


def leg(num, clock, category="Länstrafik tåg", origin=None, **extra):
    return {
        "type": "JNY", "Origin": {"date": "2026-09-15", "time": clock, **(origin or {})},
        "Product": [{"num": num, "catOutL": category}], **extra,
    }


# Formen är den ResRobot svarade med 2026-09-15 för Lindome -> Göteborg C.
TRIP = {"Trip": [
    {"LegList": {"Leg": [leg("3022", "06:02:00")]}},
    {"LegList": {"Leg": [leg("3174", "06:13:00")]}},
    {"LegList": {"Leg": [leg("3024", "06:28:00")]}},
]}
NEARBY = {"stopLocationOrCoordLocation": [
    {"StopLocation": {"extId": "740059904", "name": "Fageredsvägen (Mölndal kn)", "dist": 432}},
    {"StopLocation": {"extId": "740000557", "name": "Lindome station (Mölndal kn)", "dist": 17}},
]}
GOTEBORG = {"stopLocationOrCoordLocation": [
    {"StopLocation": {"extId": "740000002", "name": "Göteborg Centralstation", "dist": 40}},
]}


def nearby(params):
    return Response(GOTEBORG if params["originCoordLat"] > 57.65 else NEARBY)


class Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


class Session:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, params=None, timeout=None):
        path = url.rsplit("/", 1)[-1]
        self.calls.append(path)
        route = self.routes[path]
        return route(params) if callable(route) else route


class ParsingTests(SimpleTestCase):
    def test_a_trip_using_a_cancelled_train_is_skipped(self):
        answer = resrobot.first_alternative(TRIP, WHEN, {"3022"})
        self.assertEqual((answer["label"], answer["mode"], answer["departs_at"][11:16]), ("Länstrafik tåg 3174", "tåg", "06:13"))

    def test_the_cancelled_train_itself_is_not_its_own_alternative(self):
        # SL:s pendeltåg: `num` är linjen (43), inte tågnumret (2871) -- live 2026-09-15.
        body = {"Trip": [
            {"LegList": {"Leg": [leg("43", "06:02:00")]}},
            {"LegList": {"Leg": [leg("43", "06:17:00")]}},
        ]}
        self.assertEqual(resrobot.first_alternative(body, WHEN, {"2871"})["departs_at"][11:16], "06:17")

    def test_a_bus_is_an_alternative_and_says_so(self):
        body = {"Trip": [{"LegList": {"Leg": [leg("761", "06:07:00", "Länstrafik buss"), leg("3174", "06:20:00")]}}]}
        answer = resrobot.first_alternative(body, WHEN, set())
        self.assertEqual((answer["mode"], answer["changes"]), ("buss", 1))

    def test_a_bus_line_with_a_cancelled_trains_number_is_not_confused_with_it(self):
        body = {"Trip": [{"LegList": {"Leg": [leg("3022", "06:07:00", "Länstrafik buss")]}}]}
        self.assertIsNotNone(resrobot.first_alternative(body, WHEN, {"3022"}))

    def test_realtime_and_unreachable_legs(self):
        late = {"Trip": [{"LegList": {"Leg": [leg("3174", "06:13:00", origin={"rtTime": "06:19:00"})]}}]}
        self.assertEqual(resrobot.first_alternative(late, WHEN, set())["departs_at"][11:16], "06:19")
        dead = {"Trip": [{"LegList": {"Leg": [leg("3174", "06:13:00", reachable=False)]}}]}
        self.assertIsNone(resrobot.first_alternative(dead, WHEN, set()))

    def test_the_station_stop_beats_a_nearer_bus_stop(self):
        self.assertEqual(resrobot.nearest_station_stop(NEARBY), "740000557")


class FinderTests(SimpleTestCase):
    def finder(self, routes, **kwargs):
        session = Session(routes)
        finder = resrobot.AlternativeFinder(KEY, stations=STATIONS, now=WHEN - timedelta(minutes=20), session=session, **kwargs)
        return finder, session

    def test_stops_are_looked_up_once_and_then_the_trip(self):
        finder, session = self.finder({"location.nearbystops": nearby, "trip": Response(TRIP)})
        answer = finder("tvr:Ldo:3022:x", "Ldo", "G", WHEN, {"3022"})
        self.assertEqual(answer["label"], "Länstrafik tåg 3174")
        finder("tvr:Ldo:3022:y", "Ldo", "G", WHEN, {"3022"})
        self.assertEqual(session.calls.count("location.nearbystops"), 2)  # origin och destination, en gång var
        self.assertEqual(finder.detail()["calls"], 4)

    def test_a_fresh_previous_answer_costs_no_call(self):
        previous = {"tvr:Ldo:3022:x": {"basis": "resrobot", "departs_at": WHEN.isoformat(), "trains": ["3174"],
                                       "checked_at": (WHEN - timedelta(minutes=25)).isoformat()}}
        finder, session = self.finder({}, previous=previous)
        self.assertIsNotNone(finder("tvr:Ldo:3022:x", "Ldo", "G", WHEN, {"3022"}))
        self.assertEqual(session.calls, [])

    def test_a_previous_answer_is_dropped_when_its_train_is_now_cancelled(self):
        previous = {"tvr:Ldo:3022:x": {"basis": "resrobot", "trains": ["3174"], "checked_at": WHEN.isoformat()}}
        finder, session = self.finder({"location.nearbystops": nearby, "trip": Response(TRIP)}, previous=previous)
        answer = finder("tvr:Ldo:3022:x", "Ldo", "G", WHEN, {"3022", "3174"})
        self.assertEqual(answer["label"], "Länstrafik tåg 3024")

    def test_budget_and_run_limit_stop_calls(self):
        finder, session = self.finder({}, state={"month": "2026-09", "calls": resrobot.MONTHLY_BUDGET})
        self.assertIsNone(finder("tvr:Ldo:3022:x", "Ldo", "G", WHEN, set()))
        self.assertEqual(session.calls, [])
        self.assertEqual(finder.detail()["run"]["budget_exhausted"], 1)

    def test_repeated_errors_pause_calls_into_the_next_run(self):
        # Som första liverundan via beat: varje hållplatsuppslag gav INT_HAFAS_CONNECTION_ERROR.
        error = Response({"errorCode": "INT_HAFAS_CONNECTION_ERROR"}, status=500)
        finder, session = self.finder({"location.nearbystops": error})
        with self.assertLogs("core.sources.resrobot", level="WARNING"):
            for n in range(5):
                self.assertIsNone(finder(f"tvr:S{n}:1:x", "Ldo", "G", WHEN, set()))
        self.assertEqual(len(session.calls), resrobot.MAX_ERRORS_PER_RUN)

        later_session = Session({"location.nearbystops": error})
        later = resrobot.AlternativeFinder(
            KEY, stations=STATIONS, now=WHEN - timedelta(minutes=15), session=later_session, state=finder.detail(),
        )
        self.assertIsNone(later("tvr:S9:1:x", "Ldo", "G", WHEN, set()))
        self.assertEqual(later_session.calls, [])
        self.assertEqual(later.detail()["run"]["paused"], 1)

    def test_last_months_count_starts_over(self):
        state = resrobot.load_state({"month": "2026-08", "calls": 999, "stops": {"Ldo": "740000557"}}, WHEN)
        self.assertEqual((state["calls"], state["stops"]), (0, {"Ldo": "740000557"}))

    def test_far_future_departures_are_not_looked_up(self):
        finder, session = self.finder({})
        self.assertIsNone(finder("x", "Ldo", "G", WHEN + timedelta(hours=5), set()))
        self.assertEqual(session.calls, [])

    def test_errors_fall_back_quietly_and_never_log_the_key(self):
        finder, _ = self.finder({"location.nearbystops": Response(ValueError("bad json")),
                                 "trip": Response({"errorCode": "API_AUTH"}, status=401)})
        with self.assertLogs("core.sources.resrobot", level="WARNING") as logs:
            self.assertIsNone(finder("x", "Ldo", "G", WHEN, set()))
        self.assertNotIn(KEY, "\n".join(logs.output))


class RailIntegrationTests(SimpleTestCase):
    def departures(self):
        return [
            {"AdvertisedTrainIdent": "3022", "LocationSignature": "Ldo", "AdvertisedTimeAtLocation": WHEN.isoformat(),
             "Canceled": True, "ToLocation": [{"LocationName": "G"}]},
            # Nästa tåg från stationen går åt andra hållet -- ingen hjälp för den som ska till Göteborg.
            {"AdvertisedTrainIdent": "3175", "LocationSignature": "Ldo",
             "AdvertisedTimeAtLocation": (WHEN + timedelta(minutes=15)).isoformat(), "ToLocation": [{"LocationName": "Kb"}]},
        ]

    def test_the_resrobot_answer_replaces_the_direction_blind_next_departure(self):
        def alternative_for(external_id, sig, to_sig, when, cancelled):
            self.assertEqual((sig, to_sig, cancelled), ("Ldo", "G", {"3022"}))
            return resrobot.first_alternative(TRIP, when, cancelled) | {"checked_at": WHEN.isoformat()}

        (alert,) = build_alerts(self.departures(), STATIONS, WHEN - timedelta(minutes=20), alternative_for=alternative_for)
        self.assertEqual((alert.next_departure_minutes, alert.alternative_basis), (11, "resrobot"))
        self.assertIn("Nästa resa mot Göteborg C: Länstrafik tåg 3174 06:13", alert.description)
        self.assertIn("nästa resa mot Göteborg C om 11 min", classify(alert).reasons)

    def test_without_an_answer_the_station_next_departure_stands(self):
        (alert,) = build_alerts(self.departures(), STATIONS, WHEN - timedelta(minutes=20), alternative_for=lambda *a: None)
        self.assertEqual((alert.next_departure_minutes, alert.alternative_basis), (15, "station"))
