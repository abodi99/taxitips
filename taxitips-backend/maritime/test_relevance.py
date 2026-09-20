"""
Ankomsterna för taxiföraren: allt som är en känd ankomst visas, med sort och kännetecken, och
bara dubbletter, sådant utanför tidsfönstret och fartyg vid kaj utan sedd ankomst tas bort.
"""

from __future__ import annotations

import datetime as dt

from django.test import TestCase
from django.utils import timezone

from maritime import relevance
from maritime.models import FerryArrival, FerryTimetableCall


class RelevanceTests(TestCase):
    def setUp(self):
        self.now = timezone.now().replace(microsecond=0)
        self.n = 0

    def trip(self, agency, start, end, arrive_in=30, start_id=None, end_id=None):
        self.n += 1
        common = dict(service_date=timezone.localtime(self.now).date(), trip_id=f"T{self.n}", agency=agency,
                      route_name="", origin_name="", destination_name="", imported_at=self.now)
        FerryTimetableCall.objects.create(stop_id=start_id or f"s{self.n}", stop_name=start[0], lat=start[1], lon=start[2],
                                          sequence=1, arrival_at=None, departure_at=self.now, **common)
        FerryTimetableCall.objects.create(stop_id=end_id or f"e{self.n}", stop_name=end[0], lat=end[1], lon=end[2],
                                          sequence=2, arrival_at=self.now + dt.timedelta(minutes=arrive_in),
                                          departure_at=None, **common)

    def build(self, ais_only=()):
        return relevance.build(self.now, {"trips": [], "aisOnly": list(ais_only)})

    def test_every_arrival_is_shown_with_its_kind_and_the_driver_decides(self):
        visby, nynas = ("Visby hamnterminal", 57.6347, 18.2794), ("Nynäshamns färjeterminal", 58.9010, 17.9531)
        ven, landskrona = ("Ven Bäckviken", 55.9112, 12.7065), ("Landskrona Skeppsbron", 55.8694, 12.8303)
        self.trip("Destination Gotland", visby, nynas)
        self.trip("Ventrafiken", ven, landskrona)
        self.trip("Trafikverket", ("Hönö", 57.69, 11.65), ("Lilla Varholmen", 57.70, 11.70))
        self.trip("AB SL Kundtjänst", ("Slussen", 59.3195, 18.0720), ("Slussen", 59.3195, 18.0720),
                  start_id="SL", end_id="SL")
        self.trip("Västtrafik", ("Stenpiren", 57.7047, 11.9616), ("Lindholmspiren", 57.7075, 11.9380))
        FerryTimetableCall.objects.filter(stop_name="Ven Bäckviken").update(stop_has_road=False)
        data = self.build()
        kinds = {i["from"]: i["kind"] for i in data["items"]}
        self.assertEqual(kinds, {"Visby hamnterminal": "big", "Ven Bäckviken": "island", "Hönö": "road",
                                 "Slussen": "loop", "Stenpiren": "commuter"})
        self.assertEqual(data["summary"]["removed"], 0)
        self.assertEqual(data["funnel"]["start"], data["funnel"]["kept"] + data["summary"]["removed"])
        self.assertTrue(all(d["kept"] for d in data["decisions"].values()))
        stenpiren = next(i for i in data["items"] if i["from"] == "Stenpiren")
        self.assertIn("transit_both", stenpiren["traits"])

    def test_the_arrival_says_where_to_wait_and_when(self):
        self.trip("Destination Gotland", ("Visby hamnterminal", 57.6347, 18.2794),
                  ("Nynäshamns färjeterminal", 58.9010, 17.9531), arrive_in=30)
        (item,) = self.build()["items"]
        self.assertEqual(item["terminal"]["name"], "Nynäshamns färjeterminal")
        self.assertEqual(dt.datetime.fromisoformat(item["pickupFrom"]) - dt.datetime.fromisoformat(item["expectedAt"]),
                         dt.timedelta(minutes=10))
        self.assertEqual(item["expectedBasis"], "tidtabell (ingen AIS-position)")

    def ship(self, status, mmsi=219000001, terminal="goteborg", terminal_name="Göteborg Stena Line", eta_in=20):
        return {"mmsi": mmsi, "name": "STENA DANICA", "lengthM": 155, "lat": 57.7, "lon": 11.9, "knots": 12.0,
                "course": 90.0, "ageSeconds": 30, "status": status, "terminal": terminal, "terminalName": terminal_name,
                "distanceKm": 8.0, "eta": (self.now + dt.timedelta(minutes=eta_in)).isoformat() if status != "berthed" else None,
                "destination": "SEGOT"}

    def test_foreign_ferries_are_kept_and_the_pendulum_says_where_it_comes_from(self):
        data = self.build([self.ship("approaching"), self.ship("approaching", mmsi=2, terminal="helsingborg",
                                                               terminal_name="Helsingborg Knutpunkten")])
        by_id = {i["id"]: i for i in data["items"]}
        self.assertEqual(set(by_id), {"ais:219000001", "ais:2"})
        self.assertTrue(by_id["ais:219000001"]["international"])
        self.assertEqual(by_id["ais:219000001"]["from"], "")
        self.assertEqual((by_id["ais:2"]["kindLabel"], by_id["ais:2"]["from"]), ("Pendelfärja", "Helsingør"))
        self.assertEqual(dt.datetime.fromisoformat(by_id["ais:2"]["pickupFrom"]),
                         dt.datetime.fromisoformat(by_id["ais:2"]["expectedAt"]))

    def test_a_ferry_at_the_quay_counts_only_if_it_was_seen_arriving(self):
        FerryArrival.objects.create(mmsi=219000001, ship_name="STENA DANICA", length_m=155,
                                    port_name="Göteborg Stena Line", triggered_at=self.now - dt.timedelta(minutes=12))
        seen = self.build([self.ship("berthed")])
        self.assertEqual(len(seen["items"]), 1)
        self.assertTrue(seen["items"][0]["arrived"])
        unseen = self.build([self.ship("berthed", mmsi=219000002)])
        self.assertEqual(unseen["items"], [])
        self.assertEqual({s["rule"]: s["removed"] for s in unseen["funnel"]["steps"]}["berthed_unknown"], 1)

    def test_a_landing_without_road_is_shown_and_marked(self):
        self.trip("Västtrafik", ("Saltholmen", 57.6600, 11.8400), ("Brännö Rödsten", 57.6350, 11.7700))
        FerryTimetableCall.objects.filter(stop_name="Brännö Rödsten").update(stop_has_road=False)
        (item,) = self.build()["items"]
        self.assertIn("no_road", item["traits"])
        self.assertTrue(any("kolla att taxin når fram" in w for w in item["why"]))

    def test_only_a_duplicate_is_removed(self):
        ven, landskrona = ("Ven Bäckviken", 55.9112, 12.7065), ("Landskrona Skeppsbron", 55.8694, 12.8303)
        self.trip("Ventrafiken", ven, landskrona)
        self.trip("Ventrafiken", ven, landskrona)
        data = self.build()
        self.assertEqual([i["headline"] for i in data["items"]], ["Från Ven Bäckviken till Landskrona Skeppsbron"])
        self.assertEqual({s["rule"]: s["removed"] for s in data["funnel"]["steps"]},
                         {"duplicate": 1, "outside_window": 0, "berthed_unknown": 0})

    def test_an_unmatched_gotland_ferry_is_not_called_foreign(self):
        self.trip("Destination Gotland", ("Visby hamnterminal", 57.6347, 18.2794),
                  ("Oskarshamn station", 57.2650, 16.4480), arrive_in=20)
        ship = self.ship("approaching", terminal="oskarshamn", terminal_name="Oskarshamn", eta_in=25)
        data = self.build([ship])
        self.assertEqual([i["international"] for i in data["items"]], [False])
        self.assertEqual({s["rule"]: s["removed"] for s in data["funnel"]["steps"]}["duplicate"], 1)

    def test_a_running_trip_that_is_no_arrival_in_the_window_says_so(self):
        later = (self.now + dt.timedelta(hours=4)).isoformat()
        data = relevance.build(self.now, {"trips": [{"key": "d:T9", "plannedArrival": later}], "aisOnly": []})
        self.assertEqual(data["decisions"]["d:T9"]["rule"], "not_arriving")

    def test_every_port_is_listed_and_says_why_nothing_is_coming(self):
        data = relevance.build(self.now, {"trips": [], "aisOnly": []}, [self.ship("berthed")])
        ports = {p["key"]: p for p in data["ports"]}
        self.assertEqual(len(ports), 17)
        self.assertEqual(ports["umea"]["arrivals"], [])
        self.assertGreater(ports["umea"]["reachMinutes"], 0)
        self.assertTrue(any("två dygnen" in n for n in ports["umea"]["notes"]))
        self.assertTrue(any("Helsingør" in n for n in ports["helsingborg"]["notes"]))
        self.assertTrue(any("STENA DANICA ligger vid kaj, men AIS har inte sett" in n for n in ports["goteborg"]["notes"]))
