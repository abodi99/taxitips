"""
Tester för vägkällan (core/sources/trafikverket_road.py + väggrenarna i
taxi_relevance/text_scoring).

Två saker är värda mest: att koordinaten läses lon-först (annars hamnar E6
i Indiska oceanen) och att vägpoängen förblir kapad. Taket är inte en
detalj -- höjs det börjar appen skicka förare till köer, och en kö skapar
inga taxikunder.
"""

from __future__ import annotations

from unittest import mock

from django.test import SimpleTestCase, TestCase, override_settings

from core.models import SeverityTier
from core.sources.trafikverket_road import (
    configured_counties,
    fetch_road_situations,
    level_for_deviation,
    normalize_situation,
    parse_wgs84_geometry,
    places_from_deviation,
)
from core.taxi_relevance import enrich_alert, is_road_alert, score_road_alert
from core.text_scoring import classify_transit_alert


def road_alert(**overrides) -> dict:
    alert = {
        "id": "tv:1:1",
        "header": "Olycka E22",
        "description": "Ett körfält avstängt vid Lund.",
        "cause": "Olycka",
        # Neutral default: "Kövarning" här hade smugit in en kösignal i
        # varje test som inte handlade om köer -- score_road_alert läser
        # header, description OCH effect.
        "effect": "Vägpåverkan",
        "areas": ["Lund"],
        "routes": ["E22"],
        "stops": [],
        "source_kind": "road",
        "mode_hint": "road",
    }
    alert.update(overrides)
    return alert


class GeometryTests(TestCase):
    def test_wkt_is_lon_lat_not_lat_lon(self):
        geo = parse_wgs84_geometry({"Point": {"WGS84": "POINT (13.0007 55.6092)"}})
        # Malmö C. Läst i fel ordning hamnar punkten söder om Sri Lanka.
        self.assertAlmostEqual(geo["lat"], 55.6092)
        self.assertAlmostEqual(geo["lon"], 13.0007)

    def test_linestring_gets_a_midpoint_pin_and_a_path(self):
        geo = parse_wgs84_geometry(
            {"Line": {"WGS84": "LINESTRING (13.0 55.0, 13.1 55.1, 13.2 55.2)"}}
        )
        self.assertEqual(len(geo["path"]), 3)
        self.assertAlmostEqual(geo["lat"], 55.1)

    def test_long_stretches_are_thinned_for_the_map(self):
        points = ", ".join(f"{13 + i / 1000} {55 + i / 1000}" for i in range(300))
        geo = parse_wgs84_geometry({"Line": {"WGS84": f"LINESTRING ({points})"}})
        self.assertLessEqual(len(geo["path"]), 80)
        self.assertGreater(len(geo["path"]), 40)

    def test_missing_or_unparseable_geometry_is_none(self):
        self.assertIsNone(parse_wgs84_geometry(None))
        self.assertIsNone(parse_wgs84_geometry({"Point": {"WGS84": "POLYGON (())"}}))


class NormalizeTests(TestCase):
    def test_situation_becomes_the_same_shape_the_other_sources_use(self):
        alerts = normalize_situation({
            "Id": "SE_STA_TRISSID_1",
            "PublicationTime": "2026-09-08T10:00:00.000+02:00",
            "Deviation": [{
                "Id": "dev1",
                "Header": "Olycka",
                "Message": "Två fordon i kollision.",
                "LocationDescriptor": "E22 vid Lund",
                "RoadNumber": "E22",
                "MessageType": "Olycka",
                "SeverityText": "Stor påverkan",
                "Geometry": {"Point": {"WGS84": "POINT (13.19 55.70)"}},
            }],
        })
        alert = alerts[0]
        self.assertEqual(alert["id"], "tv:SE_STA_TRISSID_1:dev1")
        # datetime, inte sträng: den skrevs rakt igenom förut och sprack
        # först vid första jämförelsen mot en annan tidpunkt.
        self.assertEqual(alert["active_from"].year, 2026)
        self.assertEqual(alert["source_kind"], "road")
        self.assertIn("Lund", alert["areas"])
        self.assertEqual(alert["routes"], ["E22"])
        self.assertAlmostEqual(alert["lat"], 55.70)

    def test_placeless_road_events_never_land_in_skane(self):
        # feed_for gör coalesce(region, "skane") för tips utan koordinat.
        # Med region=NULL hade en väghändelse utan geometri blivit ett
        # skånskt tips oavsett var i landet den låg.
        alert = normalize_situation({"Id": "x", "Deviation": [{"Id": "d", "MessageType": "Vägarbete"}]})[0]
        self.assertEqual(alert["region"], "trafikverket")
        self.assertIsNone(alert["lat"])

    def test_a_single_deviation_object_is_handled_like_a_list(self):
        # Trafikverket skickar ett objekt, inte en lista, när det bara finns
        # en avvikelse. Utan det här blir hela situationen tyst borttappad.
        alerts = normalize_situation({"Id": "x", "Deviation": {"Id": "d", "MessageType": "Vägarbete"}})
        self.assertEqual(len(alerts), 1)

    def test_road_number_is_only_a_place_when_no_town_is_named(self):
        self.assertEqual(
            places_from_deviation({"Message": "Kö vid Malmö", "RoadNumber": "E6"}), ["Malmö"]
        )
        self.assertEqual(places_from_deviation({"Message": "Kö", "RoadNumber": "E6"}), ["E6"])


class SourceTimeTests(TestCase):
    """
    Tiderna kommer från avvikelsen, inte från publiceringen.

    PublicationTime sätts om varje gång Trafikverket republicerar en post,
    så ett vägarbete från 2024 såg nyskapat ut vid varje pollcykel -- mätt
    medianfel 862 timmar (docs/api-field-inventory.md).
    """

    def deviation(self, **extra):
        dev = {"Id": "d", "MessageType": "Vägarbete", "MessageCode": "Vägarbete"}
        dev.update(extra)
        return normalize_situation({
            "Id": "s", "PublicationTime": "2026-09-08T12:00:00.000+02:00",
            "Deviation": [dev],
        })[0]

    def test_start_time_comes_from_the_deviation(self):
        alert = self.deviation(StartTime="2024-04-24T14:49:00.000+02:00")
        self.assertEqual(alert["active_from"].year, 2024)

    def test_publication_time_is_only_a_fallback(self):
        self.assertEqual(self.deviation()["active_from"].year, 2026)

    def test_the_sources_own_end_time_is_kept_raw_for_the_poller_to_cap(self):
        # Verklig data: EndTime 2029-10-31 för ett pågående vägarbete.
        # Kapningen görs i poll_road, inte här -- adaptern ska rapportera
        # vad källan sa, inte tolka det.
        alert = self.deviation(EndTime="2029-10-31T23:59:00.000+01:00")
        self.assertEqual(alert["active_to"].year, 2029)


class LevelTests(TestCase):
    def test_road_closed_icon_is_high_without_any_text_matching(self):
        self.assertEqual(
            level_for_deviation({"IconId": "roadClosed", "MessageType": "Vägarbete"}), "high"
        )

    def test_the_message_code_is_read_not_just_the_type(self):
        # MessageType har tre värden och kallar en avstängd väg "Vägarbete".
        # Mätt före ändringen: 25 av 33 "Vägen avstängd" klassades low.
        self.assertEqual(
            level_for_deviation({"MessageType": "Vägarbete", "MessageCode": "Vägen avstängd"}),
            "high",
        )

    def test_the_specific_code_reaches_the_scoring_as_cause(self):
        alert = normalize_situation({
            "Id": "s",
            "Deviation": [{"Id": "d", "MessageType": "Vägarbete", "MessageCode": "Vägen avstängd"}],
        })[0]
        self.assertEqual(alert["cause"], "Vägen avstängd")


class CountyTests(TestCase):
    @override_settings(TRAFIKVERKET_COUNTIES="all")
    def test_all_means_all_21_counties(self):
        self.assertEqual(len(configured_counties()), 21)

    @override_settings(TRAFIKVERKET_COUNTIES="skane,stockholm,skane")
        # Dubbletter tas bort: länsfiltret är ett OR och samma kod två
        # gånger ger bara en dyrare fråga.
    def test_names_map_to_scb_codes_without_duplicates(self):
        self.assertEqual(configured_counties(), ["12", "1"])

    @override_settings(TRAFIKVERKET_COUNTIES="atlantis")
    def test_unknown_county_names_are_dropped(self):
        self.assertEqual(configured_counties(), [])


@override_settings(MARKET_SCOPE="skane")
class ScoreTests(TestCase):
    def test_road_alerts_are_recognised_by_id_prefix_too(self):
        self.assertTrue(is_road_alert({"id": "tv:1:2"}))
        self.assertFalse(is_road_alert({"id": "sl:123"}))

    def test_the_cap_holds(self):
        # Ingen väghändelse får nå pushgränsen (50). Höjs något av de här
        # talen börjar appen skicka förare till köer.
        for alert in [
            road_alert(),
            road_alert(header="Vägen avstängd", cause="Avstängning", description="Helt avstängd vid Malmö."),
            road_alert(header="Kövarning", cause="Kövarning", description="Köbildning mot Lund."),
            road_alert(header="Vägarbete", cause="Vägarbete", description="Beläggningsarbete i Lund."),
        ]:
            with self.subTest(alert["header"]):
                self.assertLessEqual(score_road_alert(alert)["score"], 15)

    def test_accident_outside_the_market_scores_lower_than_inside(self):
        inside = score_road_alert(road_alert(description="Olycka vid Lund."))
        outside = score_road_alert(
            road_alert(header="Olycka", areas=["Umeå"], routes=[],
                       description="Olycka vid Umeå.")
        )
        self.assertEqual(inside["score"], 15)
        self.assertEqual(outside["score"], 8)

    def test_roadwork_far_away_is_ignored_entirely(self):
        result = score_road_alert(
            road_alert(header="Vägarbete", cause="Vägarbete", areas=["Umeå"],
                       description="Beläggningsarbete på E4 vid Umeå.")
        )
        self.assertEqual(result["level"], "ignore")
        self.assertEqual(result["score"], 0)

    def test_night_roadwork_is_ignored(self):
        result = score_road_alert(
            road_alert(header="Vägarbete", cause="Vägarbete", areas=["Lund"],
                       description="Avstängt kl 19 till 05:00 i Lund.")
        )
        self.assertEqual(result["level"], "ignore")

    def test_plain_traffic_message_carries_no_taxi_signal(self):
        result = score_road_alert(
            road_alert(header="Trafikmeddelande", cause="Trafikmeddelande",
                       description="Information om vägen.", areas=["Lund"])
        )
        self.assertEqual(result["why"], "Väginfo utan taxirelevans")

    @override_settings(MARKET_SCOPE="national")
    def test_national_scope_puts_every_road_event_in_the_market(self):
        result = score_road_alert(
            road_alert(header="Olycka", areas=["Umeå"], routes=[],
                       description="Olycka vid Umeå.")
        )
        self.assertEqual(result["score"], 15)


@override_settings(MARKET_SCOPE="skane")
class TierTests(TestCase):
    def classify(self, alert):
        return classify_transit_alert(alert, enrich_alert(alert))

    def test_tiers_label_without_re_scoring(self):
        cases = [
            (road_alert(), SeverityTier.ROAD_ACCIDENT_OR_CLOSURE, 15),
            (road_alert(header="Vägen avstängd", cause="Avstängning",
                        description="Helt avstängd vid Malmö."),
             SeverityTier.ROAD_ACCIDENT_OR_CLOSURE, 15),
            (road_alert(header="Kövarning", cause="Kövarning",
                        description="Köbildning mot Lund."),
             SeverityTier.ROAD_WORK_OR_QUEUE, 10),
            (road_alert(header="Vägarbete", cause="Vägarbete",
                        description="Vägarbete i Lund."),
             SeverityTier.ROAD_WORK, 5),
        ]
        for alert, tier, score in cases:
            with self.subTest(alert["header"]):
                result = self.classify(alert)
                self.assertEqual(result.tier, tier)
                self.assertEqual(result.score, score)
                self.assertEqual(result.mode, "road")

    def test_ignored_road_alert_stays_ignored_through_the_chain(self):
        result = self.classify(
            road_alert(header="Trafikmeddelande", cause="Trafikmeddelande",
                       description="Information.", areas=["Lund"])
        )
        self.assertEqual(result.tier, SeverityTier.IGNORE)
        self.assertEqual(result.score, 0)


POST = "core.sources.trafikverket_road.requests.post"


def _page(ids: range) -> mock.Mock:
    response = mock.Mock(ok=True, status_code=200, content=b"{}")
    response.json.return_value = {"RESPONSE": {"RESULT": [{"Situation": [
        {"Id": f"SE_STA_TRISSID_{i}", "Deviation": []} for i in ids
    ]}]}}
    return response


class PagingTests(SimpleTestCase):
    """
    Vägpollen hämtade tidigare en sida med limit=min(100 × län, 2000) och fick
    2 000 av 3 496 situationer. Nu följs skip tills en sida är kort.
    """

    def test_follows_skip_until_a_short_page(self):
        pages = [_page(range(0, 1000)), _page(range(1000, 2000)), _page(range(2000, 2486))]
        with mock.patch(POST, side_effect=pages) as post:
            fetched = fetch_road_situations("nyckel", ["1"])
        self.assertEqual(fetched["situations"], 2486)
        self.assertEqual(fetched["pages"], 3)
        self.assertTrue(fetched["complete"])
        bodies = [call.kwargs["data"].decode() for call in post.call_args_list]
        for body, skip in zip(bodies, ("0", "1000", "2000")):
            self.assertIn(f'limit="1000" skip="{skip}" orderby="Id"', body)

    def test_a_situation_repeated_across_pages_is_counted_once(self):
        with mock.patch(POST, side_effect=[_page(range(0, 1000)), _page(range(999, 1500))]):
            fetched = fetch_road_situations("nyckel", ["1"])
        self.assertEqual(fetched["situations"], 1500)

    def test_the_page_cap_marks_the_answer_incomplete(self):
        with mock.patch("core.sources.trafikverket_road.MAX_PAGES", 2):
            with mock.patch(POST, side_effect=[_page(range(0, 1000)), _page(range(1000, 2000))]):
                fetched = fetch_road_situations("nyckel", ["1"])
        self.assertFalse(fetched["complete"])
        self.assertEqual(fetched["situations"], 2000)

    def test_an_error_on_a_later_page_fails_the_round(self):
        error = mock.Mock(ok=False, status_code=500, content=b"{}")
        error.json.return_value = {"RESPONSE": {"RESULT": [{"ERROR": {"MESSAGE": "Internal error"}}]}}
        with mock.patch(POST, side_effect=[_page(range(0, 1000)), error]):
            with self.assertRaises(RuntimeError):
                fetch_road_situations("nyckel", ["1"])
