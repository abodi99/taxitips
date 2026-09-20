"""
Tidtabell och AIS per tur: rätt fartyg kopplas, fel kurs kopplas inte, ett fartyg räknas bara
en gång, och en tur utanför AIS-täckningen säger det i stället för att gissa.
"""

from __future__ import annotations

import datetime as dt

from django.test import TestCase
from django.utils import timezone

from core.geo import haversine_km
from maritime import voyages
from maritime.models import AisVessel, FerryTimetableCall

# I Göteborgs inseglingsområde: A och B ligger ungefär 21 km isär.
A = (57.60, 11.60)
B = (57.70, 11.90)


class VoyageTests(TestCase):
    def setUp(self):
        self.now = timezone.now().replace(microsecond=0)

    def trip(self, trip_id="T1", start=A, end=B, depart_ago=15, arrive_in=15, agency="Västtrafik"):
        common = dict(service_date=timezone.localtime(self.now).date(), trip_id=trip_id, agency=agency,
                      route_name="281", origin_name="Från", destination_name="Till", imported_at=self.now)
        FerryTimetableCall.objects.create(stop_id=f"{trip_id}a", stop_name="Från", lat=start[0], lon=start[1], sequence=1,
                                          arrival_at=None, departure_at=self.now - dt.timedelta(minutes=depart_ago), **common)
        FerryTimetableCall.objects.create(stop_id=f"{trip_id}b", stop_name="Till", lat=end[0], lon=end[1], sequence=2,
                                          arrival_at=self.now + dt.timedelta(minutes=arrive_in), departure_at=None, **common)

    def vessel(self, mmsi, lat, lon, knots=15.0, course=None, ship_type=60, ais_class="A", length_m=40):
        return AisVessel.objects.create(mmsi=mmsi, name=f"FARTYG {mmsi}", ship_type=ship_type, ais_class=ais_class,
                                        length_m=length_m, latitude=lat, longitude=lon, speed_knots=knots, course=course,
                                        position_at=self.now - dt.timedelta(minutes=1))

    def test_the_ferry_at_the_expected_position_heading_for_port_is_matched_with_an_eta(self):
        self.trip()
        mid = ((A[0] + B[0]) / 2, (A[1] + B[1]) / 2)
        course = voyages._bearing(*mid, *B)
        self.vessel(265000001, *mid, knots=15.0, course=course)
        (row,) = voyages.build(self.now)["trips"]
        self.assertEqual((row["status"], row["vessel"]["mmsi"]), ("matched", 265000001))
        expected_minutes = haversine_km(*mid, *B) * voyages.ROUTE_FACTOR / (15.0 * voyages.KNOT_KMH) * 60
        self.assertAlmostEqual(row["delayMinutes"], round(expected_minutes - 15), delta=1)
        self.assertEqual(row["etaBasis"], "sträcka och fart")

    def test_a_ship_heading_the_other_way_is_not_the_ferry(self):
        self.trip()
        mid = ((A[0] + B[0]) / 2, (A[1] + B[1]) / 2)
        self.vessel(265000002, *mid, knots=15.0, course=voyages._bearing(*mid, *A))
        (row,) = voyages.build(self.now)["trips"]
        self.assertEqual((row["status"], row["vessel"]), ("no_match", None))

    def test_a_cruise_ship_is_never_an_archipelago_boat(self):
        self.trip()
        mid = ((A[0] + B[0]) / 2, (A[1] + B[1]) / 2)
        self.vessel(265000009, *mid, knots=15.0, course=voyages._bearing(*mid, *B), length_m=316)
        (row,) = voyages.build(self.now)["trips"]
        self.assertEqual((row["status"], row["vessel"]), ("no_match", None))

    def test_before_departure_the_ferry_waits_at_the_origin(self):
        self.trip(depart_ago=-10, arrive_in=40)
        self.vessel(265000003, *A, knots=0.0)
        (row,) = voyages.build(self.now)["trips"]
        self.assertEqual((row["phase"], row["status"], row["delayMinutes"]), ("before", "matched", 0))

    def test_one_vessel_is_never_two_ferries(self):
        self.trip("T1")
        self.trip("T2")
        mid = ((A[0] + B[0]) / 2, (A[1] + B[1]) / 2)
        self.vessel(265000004, *mid, knots=15.0, course=voyages._bearing(*mid, *B))
        statuses = sorted(r["status"] for r in voyages.build(self.now)["trips"])
        self.assertEqual(statuses, ["matched", "no_match"])

    def test_outside_ais_coverage_says_so(self):
        self.trip(start=(58.3, 20.5), end=(58.5, 20.9))
        (row,) = voyages.build(self.now)["trips"]
        self.assertEqual(row["status"], "no_coverage")

    def test_pleasure_boats_are_never_candidates(self):
        self.trip()
        mid = ((A[0] + B[0]) / 2, (A[1] + B[1]) / 2)
        self.vessel(265000005, *mid, knots=15.0, course=voyages._bearing(*mid, *B), ship_type=37, ais_class="B")
        (row,) = voyages.build(self.now)["trips"]
        self.assertEqual(row["status"], "no_match")

    def test_at_the_quay_after_planned_time_has_no_invented_delay(self):
        self.trip(depart_ago=40, arrive_in=-5)
        self.vessel(265000006, *B, knots=0.0)
        (row,) = voyages.build(self.now)["trips"]
        self.assertEqual((row["status"], row["delayMinutes"], row["etaBasis"]), ("matched", None, "framme"))
