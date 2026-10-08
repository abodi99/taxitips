"""
Tester för järnvägskällan och klassificeringen.

Kärnfallet: de två situationer som Node gav identiska 85 poäng måste nu
skiljas åt. Om det testet faller är hela fasen meningslös.
"""

from datetime import datetime, timedelta, timezone as dt_tz

from django.test import TestCase

from zoneinfo import ZoneInfo

from core import taxi_context
from core.scoring import LAST_DEPARTURE_SCORE, classify, is_busy_station
from core.sources.trafikverket_rail import (
    RailAlert, Station, build_alerts, build_replacement_index, minutes_late, parse_point, platform_end,
)

NOW = datetime(2026, 9, 6, 22, 0, tzinfo=dt_tz.utc)


def alert(**overrides) -> RailAlert:
    base = dict(
        external_id="tvr:Mot:8780:x", header="Tåg 8780 är inställt från Motala C",
        description="", station="Motala C", train="8780", cancelled=True,
        delay_minutes=0, departure_at=NOW + timedelta(minutes=30),
        active_from=NOW, active_to=NOW + timedelta(hours=1),
        lat=58.5371, lon=15.0364,
    )
    base.update(overrides)
    return RailAlert(**base)


class TheCaseThatWasBroken(TestCase):
    """
    Node gav båda dessa line_paused/85/low. En förare kunde inte skilja
    en tom perrong från en där nästa tåg går om tio minuter.
    """

    def test_stranded_and_replaced_score_differently(self):
        stranded = classify(alert(next_departure_minutes=None, is_last_departure=True))
        replaced = classify(alert(next_departure_minutes=10))

        self.assertGreater(
            stranded.score, replaced.score,
            "en strandsatt perrong måste ranka över en med ersättare om 10 min",
        )
        self.assertEqual(stranded.tier, "line_paused")
        self.assertEqual(replaced.tier, "vehicle_cancelled")

    def test_replacement_soon_reaches_the_tier_built_for_it(self):
        result = classify(alert(next_departure_minutes=10))
        self.assertEqual(result.tier, "vehicle_cancelled")
        self.assertFalse(result.stranded)
        self.assertTrue(result.quick_alternative)
        self.assertIn("nästa avgång 10 min efter den inställda avgången", result.reasons)

    def test_next_train_soon_is_never_strong_or_pushed(self):
        # Hyllie -> Helsingborg C 2026-10-02: inställt 07:55, nästa tåg 08:00,
        # stor station. Gav 61 = Stark + push. Ingen står kvar för fem minuter
        # -- inte ens i morgonrusning, i regn, med rätt till ersättning.
        rush = datetime(2026, 10, 2, 7, 55, tzinfo=ZoneInfo("Europe/Stockholm"))
        for gap in (5, 10, 25, 30):
            a = alert(next_departure_minutes=gap, station_departures_in_window=188, departure_at=rush)
            r = classify(a)
            o = taxi_context.assess(
                r.situation(), when=rush, busy_station=True, compensation={"cap_kr": 2960},
                weather={"precipitation_mm_h": 5, "precipitation_probability_pct": 90},
            )
            self.assertNotEqual(o.level, "high", f"glapp {gap} min")
        hyllie = classify(alert(next_departure_minutes=5, station_departures_in_window=188))
        self.assertEqual(taxi_context.assess(hyllie.situation(), when=rush, busy_station=True).level, "low")

    def test_last_departure_is_the_strongest_signal(self):
        result = classify(alert(is_last_departure=True))
        self.assertEqual(result.tier, "line_paused")
        self.assertEqual(result.score, LAST_DEPARTURE_SCORE)
        self.assertTrue(result.stranded)
        self.assertEqual(result.confidence, "high")
        self.assertIn("sista avgången härifrån", result.reasons)

    def test_long_gap_ranks_below_last_departure(self):
        last = classify(alert(is_last_departure=True))
        gap = classify(alert(next_departure_minutes=120))
        self.assertGreater(last.score, gap.score)

    def test_a_half_hour_gap_needs_circumstances_to_be_strong(self):
        result = classify(alert(next_departure_minutes=40))
        self.assertTrue(result.stranded)
        saturday_noon = datetime(2026, 10, 3, 12, 0, tzinfo=ZoneInfo("Europe/Stockholm"))
        weekday_morning = datetime(2026, 10, 1, 7, 30, tzinfo=ZoneInfo("Europe/Stockholm"))
        self.assertEqual(taxi_context.assess(result.situation(), when=saturday_noon).level, "medium")
        self.assertEqual(
            taxi_context.assess(result.situation(), when=weekday_morning, busy_station=True).level, "high",
        )

    def test_unknown_keeps_the_old_conservative_answer(self):
        result = classify(alert())
        self.assertEqual(result.tier, "line_paused")
        self.assertEqual(result.confidence, "low")
        night = datetime(2026, 10, 1, 1, 0, tzinfo=ZoneInfo("Europe/Stockholm"))
        self.assertEqual(taxi_context.assess(result.situation(), when=night, busy_station=True).level, "medium")

    def test_scores_actually_spread(self):
        scores = {
            classify(alert(is_last_departure=True)).score,
            classify(alert(next_departure_minutes=10)).score,
            classify(alert(next_departure_minutes=120)).score,
            classify(alert(cancelled=False, delay_minutes=35)).score,
        }
        self.assertGreaterEqual(
            len(scores), 4, f"poängen måste spridas, fick {sorted(scores)}"
        )


class LifetimeTests(TestCase):
    WHEN = datetime(2026, 10, 2, 7, 55, tzinfo=ZoneInfo("Europe/Stockholm"))

    def test_ends_when_the_next_departure_has_left(self):
        self.assertEqual(
            platform_end(self.WHEN, cancelled=True, next_gap_minutes=5),
            self.WHEN + timedelta(minutes=15),
        )

    def test_never_longer_than_an_hour(self):
        self.assertEqual(
            platform_end(self.WHEN, cancelled=True, next_gap_minutes=120),
            self.WHEN + timedelta(hours=1),
        )

    def test_replacement_and_delay(self):
        self.assertEqual(
            platform_end(self.WHEN, cancelled=True, has_replacement=True),
            self.WHEN + timedelta(minutes=30),
        )
        self.assertEqual(
            platform_end(self.WHEN, cancelled=False, delay_minutes=35),
            self.WHEN + timedelta(minutes=45),
        )


class ReplacementTrafficTests(TestCase):
    """
    Trafikverket säger själv när ersättningstrafik är insatt. Mätt på
    live-data: 35 av 59 inställda avgångar bär "Buss ersätter". Utan den
    här kontrollen rankas de som strandsatta perronger -- den vanligaste
    falska högnoteringen i hela flödet, och den som kostar en bomresa.
    """

    def test_replacement_ranks_below_everything_stranded(self):
        replaced = classify(alert(has_replacement=True,
                                  replacement_note="Buss ersätter"))
        stranded = classify(alert(is_last_departure=True))
        gap = classify(alert(next_departure_minutes=120))

        self.assertLess(replaced.score, stranded.score)
        self.assertLess(replaced.score, gap.score)
        self.assertEqual(replaced.tier, "vehicle_cancelled")

    def test_replacement_beats_the_last_departure_signal(self):
        # Sista avgången spelar ingen roll om en buss kör i stället.
        both = classify(alert(has_replacement=True, is_last_departure=True,
                              replacement_note="Buss ersätter"))
        self.assertEqual(both.tier, "vehicle_cancelled")
        self.assertLessEqual(both.score, 46)

    def test_the_reason_is_visible_to_the_driver(self):
        result = classify(alert(has_replacement=True,
                                replacement_note="Buss ersätter"))
        self.assertIn("buss ersätter", result.reasons)


class BusyStationTests(TestCase):
    def test_busy_station_ranks_above_quiet_one(self):
        quiet = alert(next_departure_minutes=45, station_departures_in_window=3)
        busy = alert(next_departure_minutes=45, station_departures_in_window=40)
        q = taxi_context.assess(classify(quiet).situation(), busy_station=is_busy_station(quiet))
        b = taxi_context.assess(classify(busy).situation(), busy_station=is_busy_station(busy))
        self.assertGreater(b.score, q.score)


class DelayTests(TestCase):
    def test_delay_is_line_delayed_not_line_paused(self):
        result = classify(alert(cancelled=False, delay_minutes=65))
        self.assertEqual(result.tier, "line_delayed")
        self.assertTrue(result.stranded, "en timme sent är som en inställd avgång")
        self.assertEqual(classify(alert(cancelled=False, delay_minutes=35)).stranded, False)


class ParsingTests(TestCase):
    def test_wkt_is_lon_first(self):
        # Läses det lat-först hamnar Motala i Indiska oceanen.
        self.assertEqual(parse_point("POINT (12.532185 57.926905)"), (57.926905, 12.532185))
        self.assertIsNone(parse_point("skräp"))
        self.assertIsNone(parse_point(None))

    def test_minutes_late(self):
        self.assertEqual(minutes_late({
            "AdvertisedTimeAtLocation": "2026-09-06T00:00:00+02:00",
            "EstimatedTimeAtLocation": "2026-09-06T00:35:00+02:00",
        }), 35)
        self.assertEqual(minutes_late({}), 0)


class DeduplicationTests(TestCase):
    """
    Ett inställt tåg annonseras vid varje stopp. Tåg 7182 gav fem
    identiska tips ner för Norrbottensbanan -- en händelse, fem kort.
    """

    def test_one_alert_per_train_at_its_first_stop(self):
        def dep(sig, when):
            return {
                "AdvertisedTrainIdent": "7182", "LocationSignature": sig,
                "AdvertisedTimeAtLocation": when, "Canceled": True,
            }

        departures = [
            dep("Lle", "2026-09-06T22:18:00+02:00"),
            dep("Nvn", "2026-09-06T22:27:00+02:00"),
            dep("Bdn", "2026-09-06T23:08:00+02:00"),
        ]
        stations = {
            s: Station(s, n) for s, n in
            [("Lle", "Luleå"), ("Nvn", "Notviken"), ("Bdn", "Boden C")]
        }
        alerts = build_alerts(departures, stations, NOW)
        self.assertEqual(len(alerts), 1, "ett tåg = ett tips")
        self.assertEqual(alerts[0].station, "Luleå", "första stoppet, fullaste perrongen")

    def test_next_departure_is_detected_from_the_feed(self):
        departures = [
            {"AdvertisedTrainIdent": "1", "LocationSignature": "Cst",
             "AdvertisedTimeAtLocation": "2026-09-06T22:30:00+02:00", "Canceled": True},
            {"AdvertisedTrainIdent": "2", "LocationSignature": "Cst",
             "AdvertisedTimeAtLocation": "2026-09-06T22:40:00+02:00"},
        ]
        alerts = build_alerts(departures, {"Cst": Station("Cst", "Stockholm C")}, NOW)
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].next_departure_minutes, 10)

    def test_a_cancelled_next_train_does_not_count_as_replacement(self):
        departures = [
            {"AdvertisedTrainIdent": "1", "LocationSignature": "Cst",
             "AdvertisedTimeAtLocation": "2026-09-06T22:30:00+02:00", "Canceled": True},
            {"AdvertisedTrainIdent": "2", "LocationSignature": "Cst",
             "AdvertisedTimeAtLocation": "2026-09-06T22:40:00+02:00", "Canceled": True},
        ]
        alerts = build_alerts(departures, {"Cst": Station("Cst", "Stockholm C")}, NOW)
        self.assertIsNone(alerts[0].next_departure_minutes)


def replacement_record(vehicle_mode="bus", train="8780", date="2026-09-06", description="", lat=59.1, lon=15.5):
    """En ReplacementTraffic-post i samma form som live-API:t (JBS v1.0)."""
    return {
        "Source": "Test", "Id": "1", "VehicleMode": vehicle_mode, "Status": "confirmed",
        "Description": description,
        "ReplacesTrains": {"ReplacesTrain": [
            {"AdvertisedTrainIdent": train, "ScheduledDepartureDate": date},
        ]},
        "Stops": {"Stop": [
            {"Sequence": 1, "StopId": "1", "StopPosition": {"Location": {"Latitude": lat, "Longitude": lon}}},
            {"Sequence": 2, "StopId": "2", "StopPosition": {"Location": {"Latitude": lat + 1, "Longitude": lon + 1}}},
        ]},
    }


class ReplacementTrafficJoin(TestCase):
    """
    ReplacementTraffic (JBS v1.0) ger en riktig koppling till det inställda
    tåget i stället för en gissning på Deviation-text -- se _replacement()
    i trafikverket_rail.py.
    """

    def _departures(self, **dep_overrides):
        dep = {
            "AdvertisedTrainIdent": "8780", "LocationSignature": "Mot",
            "AdvertisedTimeAtLocation": "2026-09-06T22:30:00+02:00", "Canceled": True,
        }
        dep.update(dep_overrides)
        return [dep]

    def test_join_hit_marks_replacement_even_without_matching_deviation_text(self):
        # Ingen "buss ersätter"-fras i Deviation -- bara ett strukturerat
        # ReplacementTraffic-träff ska ändå sätta has_replacement.
        idx = build_replacement_index([replacement_record()])
        alerts = build_alerts(
            self._departures(Deviation=[{"Description": "Spårändrat"}]),
            {"Mot": Station("Mot", "Motala C")}, NOW, replacement_index=idx,
        )
        self.assertTrue(alerts[0].has_replacement)
        self.assertEqual(alerts[0].replacement_mode, "bus")
        self.assertIn("Ersättningsbuss", alerts[0].replacement_note)

    def test_taxi_mode_gets_a_distinct_label(self):
        idx = build_replacement_index([replacement_record(vehicle_mode="taxi")])
        alerts = build_alerts(self._departures(), {"Mot": Station("Mot", "Motala C")}, NOW, replacement_index=idx)
        self.assertEqual(alerts[0].replacement_mode, "taxi")
        self.assertIn("Ersättningstaxi", alerts[0].replacement_note)

    def test_join_hit_overrides_coordinates_to_the_replacement_stop(self):
        idx = build_replacement_index([replacement_record(lat=59.123, lon=15.456)])
        alerts = build_alerts(
            self._departures(), {"Mot": Station("Mot", "Motala C", lat=58.5371, lon=15.0364)},
            NOW, replacement_index=idx,
        )
        self.assertEqual((alerts[0].lat, alerts[0].lon), (59.123, 15.456))
        self.assertEqual(alerts[0].replacement_coords, (59.123, 15.456))

    def test_text_match_fallback_still_works_with_no_join_hit(self):
        # Tom/annan index -- reservlösningen (textmatchning) ska fortfarande
        # fungera, ingen regression mot befintligt beteende.
        idx = build_replacement_index([replacement_record(train="9999")])  # annat tåg
        alerts = build_alerts(
            self._departures(Deviation=[{"Description": "Buss ersätter"}]),
            {"Mot": Station("Mot", "Motala C", lat=58.5371, lon=15.0364)},
            NOW, replacement_index=idx,
        )
        self.assertTrue(alerts[0].has_replacement)
        self.assertIsNone(alerts[0].replacement_mode, "textmatchning bär inget strukturerat fordonsläge")
        self.assertEqual((alerts[0].lat, alerts[0].lon), (58.5371, 15.0364), "ingen träff -> stationens koordinat")

    def test_a_train_with_no_replacement_anywhere_is_unaffected(self):
        alerts = build_alerts(self._departures(), {"Mot": Station("Mot", "Motala C")}, NOW, replacement_index={})
        self.assertFalse(alerts[0].has_replacement)


class NewFieldsTests(TestCase):
    """Fälten som API-inventeringen (docs/api-field-inventory.md) pekade ut."""

    def normalize(self, dep, others=None):
        from datetime import datetime, timezone as dt_tz

        from core.sources.trafikverket_rail import _normalize

        when = datetime(2026, 9, 8, 18, 0, tzinfo=dt_tz.utc)
        base = {
            "LocationSignature": "Mlm", "AdvertisedTrainIdent": "1612",
            "AdvertisedTimeAtLocation": "2026-09-08T20:00:00.000+02:00",
            "Canceled": True,
        }
        base.update(dep)
        return _normalize(base, None, [base, *(others or [])], when)

    def test_the_product_name_beats_the_information_owner(self):
        # InformationOwner tillskrev en Kalmar-avgång "Jönköpings
        # Länstrafik"; produktnamnet är det som står på tavlan.
        alert = self.normalize({
            "InformationOwner": "Jönköpings Länstrafik",
            "ProductInformation": [{"Code": "PNA025", "Description": "Pågatågen"}],
        })
        self.assertTrue(alert.header.startswith("Pågatågen 1612"))
        self.assertEqual(alert.product, "Pågatågen")

    def test_the_track_placeholder_is_not_shown(self):
        # 132 av 4 000 avgångar har "x", som betyder att stationen saknar
        # spårnumrering -- inte att spåret heter x.
        self.assertEqual(self.normalize({"TrackAtLocation": "x"}).track, "")
        self.assertNotIn("Spår", self.normalize({"TrackAtLocation": "x"}).description)
        self.assertIn("Spår 3", self.normalize({"TrackAtLocation": "3"}).description)

    def test_the_replacement_code_is_read_before_the_words(self):
        alert = self.normalize({"Deviation": [{"Code": "ANA007", "Description": "Buss ersätter"}]})
        self.assertTrue(alert.has_replacement)
        self.assertEqual(alert.replacement_mode, "bus")

    def test_other_information_carries_replacements_too(self):
        alert = self.normalize({
            "OtherInformation": [{"Code": "ONA151", "Description": "Buss ersätter Floda - Alingsås."}]
        })
        self.assertTrue(alert.has_replacement)
        self.assertIn("Floda", alert.replacement_note)

    def test_a_bus_as_the_next_departure_is_said_out_loud(self):
        # Att kalla ersättningsbussen "nästa avgång" utan att säga att det
        # är en buss gör beskedet fel på ett sätt som spelar roll.
        bus = {
            "LocationSignature": "Mlm", "AdvertisedTrainIdent": "9999",
            "AdvertisedTimeAtLocation": "2026-09-08T20:20:00.000+02:00",
            "TypeOfTraffic": [{"Code": "YNA002", "Description": "Buss"}],
        }
        alert = self.normalize({}, others=[bus])
        self.assertTrue(alert.next_departure_is_bus)
        self.assertIn("Nästa avgång är en buss", alert.description)

    def test_stored_text_has_clock_times_never_a_relative_duration(self):
        later = {
            "LocationSignature": "Mlm", "AdvertisedTrainIdent": "9001",
            "AdvertisedTimeAtLocation": "2026-09-08T21:50:00.000+02:00",
        }
        alert = self.normalize({}, others=[later])
        self.assertIn("Nästa avgång går 21:50.", alert.description)
        self.assertNotRegex(alert.description, r"\bom \d+ (min|tim)")

    def test_delay_is_estimated_minus_advertised_and_shows_the_new_time(self):
        alert = self.normalize({
            "Canceled": False,
            "AdvertisedTimeAtLocation": "2026-09-08T13:30:00.000+02:00",
            "EstimatedTimeAtLocation": "2026-09-08T13:50:00.000+02:00",
        })
        self.assertIn("20 min försenat", alert.header)
        self.assertIn("försenad 20 minuter", alert.description)
        self.assertIn("Ny avgång 13:50", alert.description)


class CompleteFetchTests(TestCase):
    """
    Pollen hämtade alla avgångar i landet med limit 4000; dagtid finns 14 000-15 000.
    Nu: störda avgångar och avgångar vid drabbade stationer, sida för sida.
    """

    def rail(self, disrupted, station_rows):
        import re

        from core.sources.trafikverket_rail import TrafikverketRail

        rail = TrafikverketRail("key")
        rail.queries = []

        def fake_query(xml):
            rail.queries.append(xml)
            skip = int(re.search(r'skip="(\d+)"', xml).group(1))
            size = int(re.search(r'limit="(\d+)"', xml).group(1))
            if 'name="Canceled"' in xml:
                rows = disrupted
            else:
                wanted = set(re.findall(r'name="LocationSignature" value="([^"]+)"', xml))
                rows = [r for r in station_rows if r["LocationSignature"] in wanted]
            return {"TrainAnnouncement": rows[skip:skip + size]}

        rail._query = fake_query
        return rail

    @staticmethod
    def row(train, sig, clock, **extra):
        return {
            "ActivityId": f"{train}-{sig}", "AdvertisedTrainIdent": train, "LocationSignature": sig,
            "AdvertisedTimeAtLocation": f"2026-09-15T{clock}:00.000+02:00",
            "ScheduledDepartureDateTime": "2026-09-15T00:00:00.000+02:00", **extra,
        }

    def test_every_page_is_read(self):
        from unittest.mock import patch

        from core.sources import trafikverket_rail as tvr

        disrupted = [self.row(str(7000 + i), f"S{i}", "08:00", Canceled=True) for i in range(5)]
        with patch.object(tvr, "PAGE_SIZE", 2):
            rail = self.rail(disrupted, [])
            rows = rail._departures()
        self.assertEqual(sum(1 for r in rows if r.get("Canceled")), 5)
        self.assertEqual((rail.last_stats["cancelled_trains"], rail.last_stats["complete"]), (5, True))

    def test_a_page_cap_is_reported_not_hidden(self):
        from unittest.mock import patch

        from core.sources import trafikverket_rail as tvr

        disrupted = [self.row(str(7000 + i), f"S{i}", "08:00", Canceled=True) for i in range(3)]
        with patch.object(tvr, "PAGE_SIZE", 2), patch.object(tvr, "MAX_PAGES", 1):
            rail = self.rail(disrupted, [])
            rail._departures()
        self.assertFalse(rail.last_stats["complete"])

    def test_station_departures_are_fetched_only_where_a_tip_can_arise(self):
        disrupted = [
            self.row("7182", "Lle", "22:18", Canceled=True),
            self.row("7182", "Bdn", "23:08", Canceled=True),  # längre ner på linjen: inget eget tips
            self.row("90", "Mot", "21:00", EstimatedTimeAtLocation="2026-09-15T21:05:00.000+02:00"),  # 5 min
        ]
        station_rows = [self.row("7184", "Lle", "22:40"), self.row("7186", "Bdn", "23:30"), self.row("91", "Mot", "21:30")]
        rail = self.rail(disrupted, station_rows)
        rows = rail._departures()
        station_queries = [q for q in rail.queries if 'name="Canceled"' not in q]
        self.assertEqual(len(station_queries), 1)
        self.assertIn('value="Lle"', station_queries[0])
        self.assertNotIn('value="Bdn"', station_queries[0])
        self.assertEqual(
            (rail.last_stats["tip_stations"], rail.last_stats["cancelled_trains"], rail.last_stats["cancelled_departures"]),
            (1, 1, 2),
        )
        (only,) = build_alerts(rows, {"Lle": Station("Lle", "Luleå")}, NOW)
        self.assertEqual((only.station, only.next_departure_minutes), ("Luleå", 22))


class DirectionTests(TestCase):
    """
    Landskrona 2026-10-02: 20:39 mot Göteborg C inställt. "Nästa avgång 20:50"
    var nästa tåg från stationen oavsett riktning -- glappet blev 11 min och
    tipset Svagt, fast resenärerna mot Göteborg kunde stå kvar i en timme.
    """

    WHEN = datetime(2026, 10, 2, 18, 39, tzinfo=dt_tz.utc)

    def dep(self, minutes_after: int, to: str, canceled: bool = False) -> dict:
        t = self.WHEN + timedelta(minutes=minutes_after)
        return {
            "AdvertisedTimeAtLocation": t.isoformat(), "Canceled": canceled,
            "ToLocation": [{"LocationName": to}],
        }

    def test_only_trains_to_the_same_destination_count(self):
        from core.sources.trafikverket_rail import _next_departure

        cancelled = self.dep(0, "G", canceled=True)
        station = [cancelled, self.dep(11, "M"), self.dep(64, "G")]
        gap, is_last, _at, _bus = _next_departure(cancelled, station, self.WHEN)
        self.assertEqual(gap, 64)
        self.assertFalse(is_last)

    def test_no_train_to_the_destination_is_unknown_not_last(self):
        from core.sources.trafikverket_rail import _next_departure

        cancelled = self.dep(0, "G", canceled=True)
        gap, is_last, at, _bus = _next_departure(cancelled, [cancelled, self.dep(11, "M")], self.WHEN)
        self.assertEqual((gap, is_last, at), (None, False, None))


class TravelOptionsDepartureTests(TestCase):
    def test_the_wait_is_counted_from_the_cancelled_departure(self):
        from core.alternatives import travel_options

        dep = datetime(2026, 10, 2, 18, 39, tzinfo=dt_tz.utc)
        out = travel_options(
            next_departure_at=dep + timedelta(minutes=11), next_departure_minutes=11,
            is_last_departure=False, has_alternative=False, alternative_note="",
            now=datetime(2026, 10, 2, 17, 50, tzinfo=dt_tz.utc),
            departure_at=dep, destination="Göteborg C",
        )
        self.assertEqual(out["departure"]["clock"], "20:39")
        self.assertEqual(out["departure"]["destination"], "Göteborg C")
        self.assertEqual(out["departure"]["status"], "cancelled")
        self.assertEqual(out["gap_minutes"], 11)
        self.assertEqual(out["next_clock"], "20:50")

    def test_a_delay_carries_the_new_time(self):
        from core.alternatives import travel_options

        dep = datetime(2026, 10, 2, 18, 39, tzinfo=dt_tz.utc)
        out = travel_options(
            next_departure_at=None, next_departure_minutes=None, is_last_departure=False,
            has_alternative=False, alternative_note="", now=dep - timedelta(minutes=30),
            departure_at=dep, destination="Göteborg C", delay_minutes=35,
        )
        self.assertEqual(out["departure"]["status"], "delayed")
        self.assertEqual(out["departure"]["new_clock"], "21:14")
        self.assertIsNone(out["gap_minutes"])


class VanishedTests(TestCase):
    """
    Hämtningen ser bara avgångar vars annonserade tid ligger framåt. Ett tåg som
    passerat sin avgångstid saknas därför i nästa runda -- utan att störningen är
    över. Mätt 2026-10-08: 3 711 tips avslutades i snitt 0,7 min efter avgången,
    45-59 min före sin egen sluttid.
    """

    def tip(self, external_id, departure_at, end_time, kind="transit"):
        from core.models import Opportunity, SeverityTier

        return Opportunity.objects.create(
            external_id=external_id, kind=kind, mode="train",
            severity_tier=SeverityTier.LINE_PAUSED, level="high", title="Inställt",
            summary="", demand_score=75, region="rail",
            start_time=departure_at - timedelta(minutes=90),
            end_time=end_time, departure_at=departure_at,
        )

    def close(self, current_ids, now):
        from core.management.commands.poll_rail import close_vanished

        return close_vanished(current_ids, now)

    def test_a_departed_train_keeps_its_own_end(self):
        planned_end = NOW + timedelta(minutes=50)
        departed = self.tip("tvr:Mot:8780:a", NOW - timedelta(minutes=3), planned_end)
        self.assertEqual(self.close([], NOW), 0)
        departed.refresh_from_db()
        self.assertEqual((departed.end_time, departed.expired_reason), (planned_end, None))

    def test_a_train_missing_before_its_departure_is_closed(self):
        upcoming = self.tip("tvr:Mot:8782:b", NOW + timedelta(minutes=40), NOW + timedelta(minutes=100))
        self.assertEqual(self.close([], NOW), 1)
        upcoming.refresh_from_db()
        self.assertEqual((upcoming.end_time, upcoming.expired_reason), (NOW, "source_removed"))

    def test_a_train_still_in_the_fetch_is_not_touched(self):
        kept = self.tip("tvr:Mot:8784:c", NOW + timedelta(minutes=40), NOW + timedelta(minutes=100))
        self.assertEqual(self.close(["tvr:Mot:8784:c"], NOW), 0)
        kept.refresh_from_db()
        self.assertIsNone(kept.expired_reason)

    def test_the_clock_margin_protects_a_departure_right_now(self):
        self.tip("tvr:Mot:8786:d", NOW + timedelta(seconds=60), NOW + timedelta(minutes=70))
        self.assertEqual(self.close([], NOW), 0)

    def test_other_sources_are_not_touched(self):
        self.tip("sl:123", NOW + timedelta(minutes=40), NOW + timedelta(minutes=100))
        self.assertEqual(self.close([], NOW), 0)
