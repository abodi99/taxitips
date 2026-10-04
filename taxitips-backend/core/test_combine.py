"""
Kombinationslagret: dubbletter blir en rad, knutpunkter och ankomster förstärks -- och
inget kombineras som inte faktiskt delar plats och tid.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from django.test import SimpleTestCase
from django.utils import timezone

from core import combine
from core.test_api import DEVICE_TOKEN, MALMO, ApiTestCase, opportunity

NOW = dt.datetime(2026, 9, 14, 8, 0, tzinfo=dt.timezone.utc)
LUND_C = (55.7056, 13.1868)


def tip(external_id, *, lat=LUND_C[0], lon=LUND_C[1], **overrides):
    fields = {
        "external_id": external_id, "kind": "transit", "mode": "train", "severity_tier": "vehicle_cancelled",
        "demand_score": 60, "confidence": "low", "has_alternative": False, "lat": lat, "lon": lon,
        "start_time": NOW - dt.timedelta(minutes=10), "end_time": NOW + dt.timedelta(hours=1), "title": "Tåg inställt",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


class FindTests(SimpleTestCase):
    def test_the_same_cancellation_from_two_sources_is_one_row(self):
        found = combine.find([
            tip("tvr:1", demand_score=60),
            tip("skane:1", demand_score=70, lat=LUND_C[0] + 0.0005),  # ~55 m
        ], NOW)
        self.assertEqual([(f.rule_id, f.effect, f.primary, f.members) for f in found],
                         [("combo.duplicate", "merge", "skane:1", ("tvr:1",))])
        self.assertIn("tvr", found[0].reason)

    def test_the_same_source_is_never_a_duplicate(self):
        self.assertEqual(combine.find([tip("tvr:1"), tip("tvr:2")], NOW), [])

    def test_far_apart_or_at_different_times_is_nothing(self):
        far = tip("skane:1", lat=LUND_C[0] + 0.02)  # ~2 km
        later = tip("skane:2", start_time=NOW + dt.timedelta(hours=3), end_time=NOW + dt.timedelta(hours=4))
        self.assertEqual(combine.find([tip("tvr:1"), far], NOW), [])
        self.assertEqual(combine.find([tip("tvr:1"), later], NOW), [])

    def test_different_modes_at_the_same_stop_reinforce(self):
        found = combine.find([tip("tvr:1", demand_score=70), tip("skane:9", mode="bus", demand_score=55)], NOW)
        self.assertEqual([(f.rule_id, f.primary, f.boost) for f in found], [("combo.hub", "tvr:1", combine.HUB_BOOST)])

    def test_a_stated_alternative_is_never_reinforced(self):
        found = combine.find([tip("tvr:1"), tip("skane:9", mode="bus", has_alternative=True)], NOW)
        self.assertEqual(found, [])

    def test_an_arrival_wave_with_stopped_transit_is_reinforced(self):
        arrival = tip("swedavia:ARN:1", kind="flight", mode="air", severity_tier="arrival_wave", lat=59.6519, lon=17.9186)
        train = tip("tvr:ARN", lat=59.6490, lon=17.9290, severity_tier="line_paused")  # Arlanda C, ~700 m
        found = combine.find([arrival, train], NOW)
        self.assertEqual([(f.rule_id, f.primary, f.boost) for f in found],
                         [("combo.arrival", "swedavia:ARN:1", combine.ARRIVAL_BOOST)])

    def test_road_is_context_and_never_combined(self):
        self.assertEqual(combine.find([tip("tvr:1"), tip("trafikverket:1", kind="road", mode="road")], NOW), [])


def stop(station, minutes, *, train="13871", day="2026-09-14", lat=LUND_C[0], lon=LUND_C[1], **overrides):
    """Ett inställt tågs tips vid en station; avgången `minutes` från NOW."""
    departure = NOW + dt.timedelta(minutes=minutes)
    return tip(
        f"tvr:{station[:3]}:{train}:{day}T{departure:%H:%M}:00.000+02:00",
        departure_at=departure, places=[station], start_time=departure - dt.timedelta(minutes=1),
        end_time=departure + dt.timedelta(minutes=30), lat=lat, lon=lon, **overrides,
    )


class SameTrainTests(SimpleTestCase):
    """Västtågen 13871 stod som sju rader samtidigt 2026-10-04, en per station."""

    def test_one_row_per_train_at_the_station_it_reaches_next(self):
        herrljunga = stop("Herrljunga C", -20, lat=58.08)
        ljung = stop("Ljung", -10, lat=58.01)
        borgstena = stop("Borgstena", 3, lat=57.88)
        fristad = stop("Fristad", 10, lat=57.83)
        found = combine.find([fristad, herrljunga, borgstena, ljung], NOW)
        self.assertEqual(len(found), 1)
        self.assertEqual((found[0].rule_id, found[0].effect), ("combo.same_train", "merge"))
        self.assertEqual(found[0].primary, borgstena.external_id)
        self.assertEqual(
            set(found[0].members), {herrljunga.external_id, ljung.external_id, fristad.external_id},
        )
        # Klockslag i svensk tid, i tågets ordning.
        self.assertEqual(
            found[0].reason, "Samma tåg gäller även Herrljunga C 09:40, Ljung 09:50, Fristad 10:10.",
        )

    def test_a_station_that_just_passed_still_counts_as_now(self):
        just_passed = stop("Ljung", -3, lat=58.01)
        later = stop("Fristad", 10, lat=57.83)
        self.assertEqual(combine.find([later, just_passed], NOW)[0].primary, just_passed.external_id)

    def test_when_every_station_has_passed_the_last_one_stays(self):
        first = stop("Herrljunga C", -40, lat=58.08)
        last = stop("Ljung", -20, lat=58.01)
        self.assertEqual(combine.find([first, last], NOW)[0].primary, last.external_id)

    def test_long_lists_end_with_a_count(self):
        stops = [stop(f"Station {i}", i * 4, lat=58 - i * 0.05) for i in range(7)]
        reason = combine.find(stops, NOW)[0].reason
        self.assertTrue(reason.endswith("och 2 stationer till."), reason)

    def test_the_same_number_on_another_day_is_another_train(self):
        self.assertEqual(
            combine.find([stop("Ljung", 5, lat=58.01), stop("Ljung", 5, day="2026-09-15", lat=58.01)], NOW), [],
        )

    def test_hidden_stations_are_neither_duplicates_nor_hubs(self):
        borgstena = stop("Borgstena", 3)
        ljung = stop("Ljung", 10)
        bus = tip("skane:9", mode="bus", demand_score=55)
        found = combine.find([borgstena, ljung, bus], NOW)
        hub = [f for f in found if f.rule_id == "combo.hub"]
        self.assertEqual(len(hub), 1)
        self.assertNotIn(ljung.external_id, (hub[0].primary, *hub[0].members))


class FeedTests(ApiTestCase):
    def test_the_duplicate_is_hidden_and_the_primary_says_why(self):
        now = timezone.now()
        opportunity(external_id="skane:1", title="Tåg 1234 inställt (Skånetrafiken)", demand_score=85, mode="train",
                    lat=55.6092, lon=13.0007, start_time=now - dt.timedelta(minutes=5))
        opportunity(external_id="tvr:1", title="Tåg 1234 inställt (Trafikverket)", demand_score=70, mode="train",
                    lat=55.6095, lon=13.0010, start_time=now - dt.timedelta(minutes=5))
        combine.run()
        body = self.client.get("/api/alerts", MALMO, headers={"x-device-token": DEVICE_TOKEN}).json()
        titles = [a["title"] for a in body["alerts"]]
        self.assertEqual(titles, ["Tåg 1234 inställt (Skånetrafiken)"])
        self.assertIn("combo.duplicate", body["alerts"][0]["combined"])
        self.assertTrue(any("rapporteras även av tvr" in r for r in body["alerts"][0]["reasons"]))

    def test_one_train_is_one_row_in_the_driver_list(self):
        now = timezone.now()
        # Samma tågdag för alla stationer, även när testet körs nära midnatt.
        day = f"{timezone.localtime(now):%Y-%m-%d}"
        for station, minutes, lat in (("Lund C", -10, 55.7056), ("Hjärup", 4, 55.6707), ("Burlöv", 12, 55.6370)):
            departure = now + dt.timedelta(minutes=minutes)
            opportunity(
                external_id=f"tvr:{station[:3]}:1234:{day}T{timezone.localtime(departure):%H:%M}:00.000+02:00",
                title=f"Pågatåg 1234 är inställt från {station}", demand_score=70, mode="train",
                places=[station], lat=lat, lon=13.10, departure_at=departure,
                start_time=departure - dt.timedelta(minutes=1), end_time=departure + dt.timedelta(minutes=30),
            )
        combine.run()
        body = self.client.get("/api/alerts", MALMO, headers={"x-device-token": DEVICE_TOKEN}).json()
        trains = [a for a in body["alerts"] if "1234" in a["title"]]
        self.assertEqual([a["title"] for a in trains], ["Pågatåg 1234 är inställt från Hjärup"])
        self.assertIn("combo.same_train", trains[0]["combined"])
        self.assertTrue(any(r.startswith("Samma tåg gäller även Lund C") for r in trains[0]["reasons"]))
