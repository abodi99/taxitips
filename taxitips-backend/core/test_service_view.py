"""
En tjänst i taget i pipeline-visualiseraren: rätt tips per tjänst, rätt grupp för föraren
(notis, bara listan, visas inte), hela kedjan per tips, och ingenting utan DEBUG.
"""

from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.test import TestCase, override_settings
from django.utils import timezone

from core import service_view
from core.models import Opportunity, SourceEvent


def tip(external_id, kind="transit", mode="bus", tier="vehicle_cancelled", score=60, **extra):
    now = timezone.now()
    return Opportunity.objects.create(
        external_id=external_id, kind=kind, mode=mode, severity_tier=tier, level="medium", title=external_id,
        start_time=now - timedelta(minutes=5), end_time=now + timedelta(hours=1), demand_score=score,
        confidence="medium", rule_id=f"{mode}.{tier}", **extra,
    )


class ServiceTests(TestCase):
    def test_each_service_gets_its_own_tips(self):
        tip("tvr:Cst:1", mode="train", tier="line_paused", score=85)
        tip("sl:1", mode="bus")
        tip("tv:1", kind="road", mode="road", tier="road_work", score=10)
        titles = {key: [c["title"] for c in service_view.build(key)["cards"]] for key in ("tag", "kollektivtrafik", "vag")}
        self.assertEqual(titles, {"tag": ["tvr:Cst:1"], "kollektivtrafik": ["sl:1"], "vag": ["tv:1"]})

    def test_the_driver_group_says_notification_list_or_hidden(self):
        tip("sl:notis", mode="bus", tier="vehicle_cancelled", score=60)
        tip("sl:alternativ", mode="bus", tier="vehicle_cancelled", score=60, has_alternative=True)
        tip("sl:lag", mode="bus", tier="vehicle_delayed", score=25)
        tip("sl:brus", mode="bus", tier="ignore", score=0)
        data = service_view.build("kollektivtrafik")
        groups = {c["title"]: c["group"] for c in data["cards"]}
        self.assertEqual(groups, {"sl:notis": "notify", "sl:alternativ": "list", "sl:lag": "list", "sl:brus": "hidden"})
        funnel = {f["label"]: f["n"] for f in data["funnel"]}
        self.assertEqual((funnel["Inte brus"], funnel["I förarens lista"], funnel["Ger notis"]), (3, 3, 1))

    def test_search_narrows_the_cards_but_not_the_funnel(self):
        tip("sl:a", mode="bus", places=["Kista"])
        tip("sl:b", mode="bus", places=["Slussen"])
        data = service_view.build("kollektivtrafik", q="kista")
        self.assertEqual([c["title"] for c in data["cards"]], ["sl:a"])
        self.assertEqual(data["funnel"][0]["n"], 2)

    def test_the_tip_detail_carries_the_raw_source_event(self):
        se = SourceEvent.objects.create(source="sl", external_id="sl:raw", raw={"header": "Stopp"})
        o = tip("sl:raw", mode="metro", tier="line_paused", score=85, source_event_ids=[str(se.id)])
        detail = service_view.tip_detail(str(o.id))
        self.assertEqual(detail["sourceEvents"][0]["raw"], {"header": "Stopp"})
        self.assertEqual(detail["notify"]["group"], "notify")


class DebugOnlyTests(TestCase):
    @override_settings(DEBUG=False)
    def test_nothing_without_debug(self):
        for url in ("/api/pipeline", "/api/pipeline/services", "/api/pipeline/service/tag"):
            self.assertEqual(self.client.get(url).status_code, 404, url)

    @override_settings(DEBUG=True)
    def test_with_debug_the_service_answers(self):
        response = self.client.get("/api/pipeline/service/vag")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["key"], "vag")


class FlightTests(TestCase):
    def test_history_counts_flight_tips_per_day_and_airport(self):
        now = timezone.now()
        for i, (iata, rule) in enumerate((("ARN", "arrival_wave"), ("ARN", "arrival_wave"), ("VBY", "last_arrival"))):
            Opportunity.objects.create(
                external_id=f"swedavia:{iata}:{i}", kind="flight", mode="", severity_tier=rule, level="medium",
                title=iata, start_time=now, end_time=now + timedelta(hours=1), demand_score=60 + i,
                confidence="low", rule_id=f"flight.{rule}",
            )
        date = timezone.localtime(now).date().isoformat()
        today = next(d for d in service_view._flight_history(now)["days"] if d["date"] == date)
        self.assertEqual((today["wave"], today["last"], today["airports"]), (2, 1, {"ARN": 2, "VBY": 1}))

    @override_settings(PREDICTHQ_ACCESS_TOKEN="test")
    def test_airport_delays_keep_sweden_and_only_copenhagen_from_denmark(self):
        results = {
            "SE": [{"id": "1", "title": "Severe Delays - Malmo Airport (MMX)", "start": "2026-09-18T09:00:00Z", "rank": 90,
                    "start_local": "2026-09-18T11:00:00", "geo": {"geometry": {"coordinates": [13.37, 55.53]}}}],
            "DK": [{"id": "2", "title": "Moderate Delays - Copenhagen Airport (CPH)", "start": "2026-09-17T23:00:00Z"},
                   {"id": "3", "title": "Moderate Delays - Aarhus Airport (AAR)", "start": "2026-09-19T07:00:00Z"}],
        }

        class FakeClient:
            call_count = 2

            def __init__(self, token):
                pass

            def get(self, url, query):
                return {"results": results[query["country"]], "next": None}

        with mock.patch("events.sources.predicthq.Client", FakeClient):
            data = service_view.airport_delays_live(90, 14)
        self.assertEqual([d["code"] for d in data["delays"]], ["MMX", "CPH"])
        self.assertEqual([a["code"] for a in data["airports"]], ["CPH", "MMX"])  # Köpenhamn först
        self.assertEqual(data["delays"][0]["lat"], 55.53)
        self.assertFalse(data["stored"])

    def test_the_level_comes_from_the_rank_not_the_title(self):
        self.assertEqual(service_view._delay_level(20), (20, "Minimal"))
        self.assertEqual(service_view._delay_level(90), (90, "Svår"))
        self.assertEqual(service_view._delay_level(55), (40, "Måttlig"))
