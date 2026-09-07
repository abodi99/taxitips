"""
Tester för järnvägskällan och klassificeringen.

Kärnfallet: de två situationer som Node gav identiska 85 poäng måste nu
skiljas åt. Om det testet faller är hela fasen meningslös.
"""

from datetime import datetime, timedelta, timezone as dt_tz

from django.test import TestCase

from core.scoring import classify
from core.sources.trafikverket_rail import (
    RailAlert, Station, build_alerts, build_replacement_index, minutes_late, parse_point,
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
        # vehicle_cancelled/tak 55 fanns redan i scoring.js men nåddes
        # aldrig av tåg -- det är felet den här fasen rättar.
        result = classify(alert(next_departure_minutes=10))
        self.assertEqual(result.tier, "vehicle_cancelled")
        self.assertLessEqual(result.score, 61)  # 55 + ev. stationsbonus
        self.assertIn("nästa avgång om 10 min", result.reasons)

    def test_last_departure_is_the_strongest_signal(self):
        result = classify(alert(is_last_departure=True))
        self.assertEqual(result.tier, "line_paused")
        self.assertGreaterEqual(result.score, 85)
        self.assertEqual(result.confidence, "high")
        self.assertIn("sista avgången härifrån", result.reasons)

    def test_long_gap_ranks_below_last_departure(self):
        last = classify(alert(is_last_departure=True))
        gap = classify(alert(next_departure_minutes=120))
        self.assertGreater(last.score, gap.score)

    def test_unknown_keeps_the_old_conservative_answer(self):
        # Utan information behåller vi Nodes beteende, men nu som undantag
        # i stället för regeln alla föll i.
        result = classify(alert())
        self.assertEqual(result.tier, "line_paused")
        self.assertEqual(result.confidence, "low")

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
        quiet = classify(alert(is_last_departure=True, station_departures_in_window=3))
        busy = classify(alert(is_last_departure=True, station_departures_in_window=40))
        self.assertGreater(busy.score, quiet.score)


class DelayTests(TestCase):
    def test_delay_is_line_delayed_not_line_paused(self):
        result = classify(alert(cancelled=False, delay_minutes=45))
        self.assertEqual(result.tier, "line_delayed")
        self.assertLessEqual(result.score, 45)


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
