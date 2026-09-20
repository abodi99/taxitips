"""
Tester för AISStream-källan: riktiga meddelanden och ankomstlogiken.

Det viktigaste testet är test_moored_at_startup_never_arrives. En färja som
redan ligger vid kaj när lyssnaren startar har inte anlänt. Utan den spärren
skriver varje omstart av tjänsten ett ankomsttips för varje färja i varje
hamn -- och inget annat i systemet hade märkt att tipsen var fel.
"""

from __future__ import annotations

import datetime as dt
import re

from django.test import SimpleTestCase, TestCase

from core import geo
from core.models import Opportunity, SourceEvent
from maritime import ais, tips
from maritime.models import FerryArrival
from maritime.ports import PORTS, by_key, port_for

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 9, 12, 20, 30, tzinfo=UTC)  # 22:30 i Stockholm
NYNASHAMN = by_key("nynashamn")
APPROACH = (58.918, 17.980)  # inne i Nynäshamns ruta, en bit ut från kaj
BERTH = (NYNASHAMN.lat, NYNASHAMN.lon)

# Fångade från AISStream 2026-09-12. Oförändrade, inklusive gemena
# latitude/longitude i MetaData och MMSI_String som heltal.
STATIC_ALVELI = {
    "MetaData": {
        "MMSI": 265738540, "MMSI_String": 265738540, "ShipName": "ALVELI",
        "latitude": 57.70433, "longitude": 11.93971,
        "time_utc": "2026-09-12 19:25:20.575040512 +0000 UTC",
    },
    "MessageType": "ShipStaticData",
    "Message": {"ShipStaticData": {
        "AisVersion": 2, "CallSign": "SKNC", "Destination": "",
        "Dimension": {"A": 13, "B": 20, "C": 5, "D": 3}, "Dte": False,
        "Eta": {"Day": 0, "Hour": 0, "Minute": 0, "Month": 0}, "FixType": 1,
        "ImoNumber": 0, "MaximumStaticDraught": 1.5, "MessageID": 5, "Name": "ALVELI",
        "RepeatIndicator": 0, "Spare": False, "Type": 60, "UserID": 265738540, "Valid": True,
    }},
}
POSITION_BLIDOSUND = {
    "MetaData": {
        "MMSI": 265522680, "MMSI_String": 265522680, "ShipName": "BLIDOSUND",
        "latitude": 59.32705, "longitude": 18.07521,
        "time_utc": "2026-09-12 19:25:12.190720216 +0000 UTC",
    },
    "MessageType": "PositionReport",
    "Message": {"PositionReport": {
        "MessageID": 1, "RepeatIndicator": 0, "UserID": 265522680, "Valid": True,
        "NavigationalStatus": 15, "RateOfTurn": -128, "Sog": 0, "PositionAccuracy": True,
        "Longitude": 18.075208333333332, "Latitude": 59.32705166666666, "Cog": 360,
        "TrueHeading": 511, "Timestamp": 12, "SpecialManoeuvreIndicator": 0, "Spare": 0,
        "Raim": True, "CommunicationState": 49278,
    }},
}


def _utc(t: dt.datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M:%S.000000000 +0000 UTC")


def static_msg(mmsi=265000001, *, type_=69, name="GOTLAND", length=(150, 45), eta=None, at=NOW):
    return {
        "MetaData": {"MMSI": mmsi, "ShipName": name, "time_utc": _utc(at)},
        "MessageType": "ShipStaticData",
        "Message": {"ShipStaticData": {
            "Type": type_, "Name": name, "Destination": "NYNASHAMN", "Valid": True,
            "Dimension": {"A": length[0], "B": length[1], "C": 10, "D": 10},
            "Eta": eta or {"Day": 0, "Hour": 24, "Minute": 60, "Month": 0},
            "UserID": mmsi,
        }},
    }


def position_msg(mmsi, lat, lon, sog, *, nav=0, at=NOW):
    return {
        "MetaData": {"MMSI": mmsi, "ShipName": "GOTLAND", "latitude": lat, "longitude": lon, "time_utc": _utc(at)},
        "MessageType": "PositionReport",
        "Message": {"PositionReport": {
            "UserID": mmsi, "Valid": True, "NavigationalStatus": nav,
            "Sog": sog, "Latitude": lat, "Longitude": lon,
        }},
    }


def eta_dict(t: dt.datetime) -> dict:
    return {"Month": t.month, "Day": t.day, "Hour": t.hour, "Minute": t.minute}


def vessel(**static_kwargs) -> FerryArrival:
    update = ais.parse_message(static_msg(**static_kwargs), NOW)
    v = FerryArrival(mmsi=update.mmsi)
    ais.apply_static(v, update)
    return v


def feed(v: FerryArrival, point, sog, minutes, *, nav=0) -> str | None:
    """En position `minutes` efter NOW, och ankomstbeslutet den gav."""
    t = NOW + dt.timedelta(minutes=minutes)
    update = ais.parse_message(position_msg(v.mmsi, point[0], point[1], sog, nav=nav, at=t), t)
    ais.apply_position(v, update)
    return ais.evaluate(v, t)


class ParseTests(SimpleTestCase):
    def test_real_static_message(self):
        u = ais.parse_message(STATIC_ALVELI, NOW)
        self.assertEqual(u.kind, "static")
        self.assertEqual(u.mmsi, 265738540)
        self.assertEqual(u.ship_type, 60)
        self.assertEqual(u.length_m, 33)
        self.assertEqual(u.name, "ALVELI")
        self.assertIsNone(u.eta)
        self.assertEqual(u.timestamp, dt.datetime(2026, 9, 12, 19, 25, 20, 575040, tzinfo=UTC))

    def test_real_position_message(self):
        u = ais.parse_message(POSITION_BLIDOSUND, NOW)
        self.assertEqual(u.kind, "position")
        self.assertAlmostEqual(u.lat, 59.32705, places=4)
        self.assertAlmostEqual(u.lon, 18.07521, places=4)
        self.assertEqual(u.sog, 0.0)
        self.assertEqual(u.nav_status, 15)
        self.assertIsNone(u.ship_type, "PositionReport bär ingen typ")

    def test_position_falls_back_to_lowercase_metadata(self):
        msg = position_msg(265000001, 58.9, 17.95, 3)
        del msg["Message"]["PositionReport"]["Latitude"]
        del msg["Message"]["PositionReport"]["Longitude"]
        u = ais.parse_message(msg, NOW)
        self.assertEqual((u.lat, u.lon), (58.9, 17.95))

    def test_unavailable_speed_is_unknown_not_fast(self):
        self.assertIsNone(ais.parse_sog(102.3))
        self.assertEqual(ais.parse_sog(0), 0.0)

    def test_unavailable_position_is_dropped(self):
        self.assertIsNone(ais.parse_message(position_msg(265000001, 91, 181, 0), NOW))

    def test_eta_sentinels_are_none(self):
        self.assertIsNone(ais.parse_eta({"Month": 0, "Day": 0, "Hour": 24, "Minute": 60}, NOW))
        self.assertIsNone(ais.parse_eta({"Month": 0, "Day": 0, "Hour": 0, "Minute": 0}, NOW))

    def test_stale_eta_is_none(self):
        # DROTTNING SILVIA bar den här ETA:n i september.
        self.assertIsNone(ais.parse_eta({"Month": 6, "Day": 20, "Hour": 19, "Minute": 0}, NOW))

    def test_eta_rolls_over_new_year(self):
        new_years_eve = dt.datetime(2026, 12, 31, 23, 0, tzinfo=UTC)
        eta = ais.parse_eta({"Month": 1, "Day": 1, "Hour": 1, "Minute": 30}, new_years_eve)
        self.assertEqual(eta, dt.datetime(2027, 1, 1, 1, 30, tzinfo=UTC))

    def test_other_message_types_are_ignored(self):
        self.assertIsNone(ais.parse_message({"MessageType": "AidsToNavigationReport"}, NOW))
        self.assertIsNone(ais.parse_message("inte ett objekt", NOW))

    def test_passenger_range(self):
        self.assertFalse(ais.is_passenger(59))
        self.assertTrue(ais.is_passenger(60))
        self.assertTrue(ais.is_passenger(69))
        self.assertFalse(ais.is_passenger(70))
        self.assertFalse(ais.is_passenger(None))


class PortTests(SimpleTestCase):
    def test_every_terminal_lies_in_its_own_box(self):
        for port in PORTS:
            self.assertIs(port_for(port.lat, port.lon), port, port.key)

    def test_boxes_do_not_overlap(self):
        for i, a in enumerate(PORTS):
            for b in PORTS[i + 1:]:
                overlap = a.south < b.north and b.south < a.north and a.west < b.east and b.west < a.east
                self.assertFalse(overlap, f"{a.key} och {b.key} överlappar")

    def test_subscription_is_latitude_first(self):
        sub = ais.subscription("nyckel")
        self.assertEqual(len(sub["BoundingBoxes"]), len({str(p.approach_box) for p in PORTS}))
        for (south, west), (north, east) in sub["BoundingBoxes"]:
            self.assertTrue(55 < south < north < 70, "latitud först")
            self.assertTrue(10 < west < east < 25)
        self.assertEqual(sub["FilterMessageTypes"], list(ais.MESSAGE_TYPES))
        for mtype in ("StandardClassBPositionReport", "ExtendedClassBPositionReport", "StaticDataReport"):
            self.assertIn(mtype, sub["FilterMessageTypes"], "klass B är en tredjedel av trafiken")

    def test_every_approach_area_holds_its_port_box(self):
        for port in PORTS:
            south, west, north, east = port.approach_bounds
            self.assertTrue(
                south <= port.south and west <= port.west and port.north <= north and port.east <= east, port.key,
            )

    def test_map_only_ports_say_why(self):
        self.assertFalse(by_key("helsingborg").tips)
        for port in PORTS:
            if not port.tips:
                self.assertTrue(port.note, port.key)

    def test_ports_reach_drivers_in_their_market(self):
        # Bara hamnar som ger tips behöver marknadsnycklarna.
        for port in (p for p in PORTS if p.tips):
            self.assertIn(port.region, geo.REGION_ANCHOR, port.key)
            self.assertIn(port.city, geo.REGION_CITIES[port.region], port.key)


class ArrivalTests(SimpleTestCase):
    def test_moored_at_startup_never_arrives(self):
        ferry = vessel()
        for minute in range(0, 60, 3):
            self.assertIsNone(feed(ferry, BERTH, 0, minute, nav=ais.NAV_MOORED))
        self.assertFalse(ferry.is_processed)

    def test_slowing_after_being_underway_arrives_once(self):
        ferry = vessel()
        self.assertIsNone(feed(ferry, APPROACH, 16, 0))
        self.assertIsNone(feed(ferry, APPROACH, 9, 3))
        self.assertEqual(feed(ferry, BERTH, 3.5, 6), ais.REASON_SLOWING)
        self.assertIsNone(feed(ferry, BERTH, 0.4, 9))
        self.assertIsNone(feed(ferry, BERTH, 0, 30, nav=ais.NAV_MOORED))
        self.assertTrue(ferry.is_processed)

    def test_non_passenger_ship_never_arrives(self):
        cargo = vessel(type_=70)
        feed(cargo, APPROACH, 14, 0)
        self.assertIsNone(feed(cargo, BERTH, 2, 5))

    def test_manoeuvring_right_after_arrival_does_not_rearm(self):
        ferry = vessel()
        feed(ferry, APPROACH, 14, 0)
        feed(ferry, BERTH, 3, 5)
        feed(ferry, BERTH, 7, 10)
        self.assertTrue(ferry.is_processed)

    def test_departure_rearms_for_the_next_arrival(self):
        ferry = vessel()
        feed(ferry, APPROACH, 14, 0)
        feed(ferry, BERTH, 3, 5)
        feed(ferry, APPROACH, 12, 90)
        self.assertFalse(ferry.is_processed)

    def test_long_silence_starts_a_new_call_but_not_an_arrival(self):
        ferry = vessel()
        feed(ferry, APPROACH, 14, 0)
        feed(ferry, BERTH, 3, 5)
        self.assertIsNone(feed(ferry, BERTH, 0, 5 + 4 * 60, nav=ais.NAV_MOORED))
        self.assertFalse(ferry.is_processed)
        self.assertFalse(ferry.was_underway)

    def test_eta_of_a_moored_ferry_does_not_arrive(self):
        # ETA:n gäller nästa destination, inte hamnen färjan ligger i.
        ferry = vessel(eta=eta_dict(NOW + dt.timedelta(minutes=30)))
        self.assertIsNone(feed(ferry, BERTH, 0, 0, nav=ais.NAV_MOORED))

    def test_eta_while_underway_in_port_arrives(self):
        ferry = vessel(eta=eta_dict(NOW + dt.timedelta(minutes=40)))
        self.assertEqual(feed(ferry, APPROACH, 15, 0), ais.REASON_ETA)


class AssessTests(SimpleTestCase):
    def arrived(self, *, length, minutes=6, **kwargs):
        ferry = vessel(length=length, **kwargs)
        feed(ferry, APPROACH, 15, minutes - 6)
        reason = feed(ferry, BERTH, 3, minutes)
        return ferry, reason

    def test_small_passenger_boat_arrives_but_gets_no_tip(self):
        boat, reason = self.arrived(length=(13, 20))
        self.assertEqual(reason, ais.REASON_SLOWING)
        self.assertIsNone(tips.assess(boat, NYNASHAMN, reason, NOW))

    def test_large_evening_ferry(self):
        ferry, reason = self.arrived(length=(150, 45))
        a = tips.assess(ferry, NYNASHAMN, reason, NOW)
        self.assertEqual(a.score, 55 + tips.LATE_BONUS)
        self.assertEqual(a.rule_id, "boat.arrival_wave")
        self.assertEqual(a.confidence, "medium")
        self.assertEqual(a.end - a.start, dt.timedelta(minutes=tips.TAIL_MINUTES))

    def test_midday_ferry_gets_no_evening_bonus(self):
        ferry, reason = self.arrived(length=(100, 40), minutes=-10 * 60)  # 12:30 lokalt
        a = tips.assess(ferry, NYNASHAMN, reason, NOW)
        self.assertEqual(a.score, 45)
        self.assertFalse(any("Kvällsankomst" in r for r in a.reasons))

    def test_eta_arrival_has_low_confidence(self):
        ferry = vessel(eta=eta_dict(NOW + dt.timedelta(minutes=40)))
        reason = feed(ferry, APPROACH, 15, 0)
        self.assertEqual(tips.assess(ferry, NYNASHAMN, reason, NOW).confidence, "low")

    def test_never_invents_a_passenger_count(self):
        ferry, reason = self.arrived(length=(150, 45))
        text = " ".join(tips.assess(ferry, NYNASHAMN, reason, NOW).reasons)
        self.assertIsNone(re.search(r"\d+\s*(passagerare|resenärer|personer)", text))


class WriteTipTests(TestCase):
    def write(self):
        ferry = vessel()
        feed(ferry, APPROACH, 15, 0)
        reason = feed(ferry, BERTH, 3, 6)
        assessment = tips.assess(ferry, NYNASHAMN, reason, NOW)
        return ferry, tips.write_tip(ferry, NYNASHAMN, assessment, reason)

    def test_tip_is_explainable(self):
        ferry, ext = self.write()
        tip = Opportunity.objects.get(external_id=ext)
        event = SourceEvent.objects.get(external_id=ext)
        self.assertEqual((tip.kind, tip.mode, tip.region), ("ferry", "boat", "sl"))
        self.assertEqual(tip.places, ["Nynäshamn", "Stockholm"])
        self.assertEqual(tip.source_event_ids, [str(event.id)])
        self.assertEqual(tip.rule_id, "boat.arrival_wave")
        self.assertTrue(tip.reasons)
        self.assertIsNotNone(tip.end_time)
        self.assertEqual(event.source, "aisstream")
        self.assertEqual(event.raw["mmsi"], ferry.mmsi)
        self.assertEqual(event.raw["trigger"], ais.REASON_SLOWING)

    def test_same_arrival_written_twice_is_one_tip(self):
        ferry, ext = self.write()
        assessment = tips.assess(ferry, NYNASHAMN, ais.REASON_SLOWING, NOW)
        tips.write_tip(ferry, NYNASHAMN, assessment, ais.REASON_SLOWING)
        self.assertEqual(Opportunity.objects.filter(external_id=ext).count(), 1)


class ExplainTests(SimpleTestCase):
    """Förklaringen pipeline-sidan visar per fartyg."""

    def stage(self, v, now=NOW):
        from maritime import explain
        return explain.verdict(v, now)["stage"]

    def test_type_is_known_but_no_position_yet(self):
        self.assertEqual(self.stage(vessel()), "no_position")

    def test_small_boat_is_too_short_even_after_arriving(self):
        boat = vessel(length=(13, 20))
        feed(boat, APPROACH, 12, 0)
        feed(boat, BERTH, 2, 5)
        self.assertEqual(self.stage(boat, NOW + dt.timedelta(minutes=5)), "too_short")

    def test_ferry_moored_at_startup_is_still(self):
        ferry = vessel()
        feed(ferry, BERTH, 0, 0, nav=ais.NAV_MOORED)
        self.assertEqual(self.stage(ferry), "still")

    def test_ferry_underway_in_port_is_a_candidate(self):
        from maritime import explain
        ferry = vessel()
        feed(ferry, APPROACH, 14, 0)
        self.assertEqual(explain.verdict(ferry, NOW), {**explain.verdict(ferry, NOW), "stage": "underway", "candidate": True})

    def test_arrived_ferry_is_handled(self):
        ferry = vessel()
        feed(ferry, APPROACH, 14, 0)
        feed(ferry, BERTH, 3, 5)
        self.assertEqual(self.stage(ferry, NOW + dt.timedelta(minutes=5)), "handled")

    def test_silent_ferry(self):
        ferry = vessel()
        feed(ferry, BERTH, 0, 0)
        self.assertEqual(self.stage(ferry, NOW + dt.timedelta(minutes=30)), "silent")

    def test_type_labels(self):
        from maritime import explain
        self.assertEqual(explain.type_label(69), ("Passagerarfartyg", "60–69"))
        self.assertEqual(explain.type_label("70")[0], "Lastfartyg")
        self.assertEqual(explain.type_label(None)[0], "Okänd typ")
        self.assertEqual(explain.type_label(0)[0], "Okänd typ")


class ExplainBuildTests(TestCase):
    def test_renders_without_a_running_listener(self):
        from maritime import explain
        block = explain.build(NOW)
        self.assertNotIn("error", block)
        self.assertEqual(len(block["funnel"]), 9)
        self.assertIn("klass B", " ".join(f["label"] for f in block["funnel"]))
        self.assertEqual(len(block["ports"]), len(PORTS))
        self.assertFalse(block["status"]["connected"])
        self.assertIn("run_ais_stream", block["status"]["lastError"])


# Fångade från AISStream 2026-09-12, oförändrade. Klass B: ingen
# NavigationalStatus, och Cog 360 / TrueHeading 511 betyder "saknas".
CLASS_B_SVANOE = {
    "MetaData": {"MMSI": 265688670, "MMSI_String": 265688670, "ShipName": "SVANOE",
                 "latitude": 59.32608, "longitude": 18.08891,
                 "time_utc": "2026-09-12 20:10:04.595970288 +0000 UTC"},
    "MessageType": "StandardClassBPositionReport",
    "Message": {"StandardClassBPositionReport": {
        "AssignedMode": False, "ClassBBand": True, "ClassBDisplay": False, "ClassBDsc": True,
        "ClassBMsg22": True, "ClassBUnit": False, "Cog": 360, "CommunicationState": 82938,
        "CommunicationStateIsItdma": True, "Latitude": 59.32608166666667, "Longitude": 18.088905,
        "MessageID": 18, "PositionAccuracy": False, "Raim": False, "RepeatIndicator": 0, "Sog": 0,
        "Spare1": 0, "Spare2": 0, "Timestamp": 4, "TrueHeading": 511, "UserID": 265688670, "Valid": True,
    }},
}
# Del A: bara namnet. ReportB är ogiltig och nollad -- inklusive ShipType 0.
STATIC_REPORT_A_SASKIA = {
    "MetaData": {"MMSI": 265611350, "MMSI_String": 265611350, "ShipName": "SASKIA",
                 "latitude": 59.30546, "longitude": 18.08759,
                 "time_utc": "2026-09-12 20:10:10.647294245 +0000 UTC"},
    "MessageType": "StaticDataReport",
    "Message": {"StaticDataReport": {
        "MessageID": 24, "PartNumber": False, "RepeatIndicator": 0,
        "ReportA": {"Name": "SASKIA", "Valid": True},
        "ReportB": {"CallSign": "", "Dimension": {"A": 0, "B": 0, "C": 0, "D": 0}, "FixType": 0,
                    "ShipType": 0, "Spare": 0, "Valid": False, "VenderIDModel": 0,
                    "VenderIDSerial": 0, "VendorIDName": ""},
        "Reserved": 0, "UserID": 265611350, "Valid": True,
    }},
}


def static_report_b(mmsi=265000002, *, type_=60, length=(80, 30), width=(5, 4), at=NOW):
    return {
        "MetaData": {"MMSI": mmsi, "ShipName": "", "time_utc": _utc(at)},
        "MessageType": "StaticDataReport",
        "Message": {"StaticDataReport": {
            "MessageID": 24, "PartNumber": True, "UserID": mmsi, "Valid": True,
            "ReportA": {"Name": "", "Valid": False},
            "ReportB": {"CallSign": "SFB1", "ShipType": type_, "Valid": True,
                        "Dimension": {"A": length[0], "B": length[1], "C": width[0], "D": width[1]}},
        }},
    }


def class_b_position(mmsi, lat, lon, sog, *, at=NOW, cog=90.0, heading=90):
    return {
        "MetaData": {"MMSI": mmsi, "ShipName": "", "latitude": lat, "longitude": lon, "time_utc": _utc(at)},
        "MessageType": "StandardClassBPositionReport",
        "Message": {"StandardClassBPositionReport": {
            "UserID": mmsi, "Valid": True, "Sog": sog, "Cog": cog, "TrueHeading": heading,
            "Latitude": lat, "Longitude": lon,
        }},
    }


class ClassBTests(SimpleTestCase):
    def test_real_class_b_position(self):
        u = ais.parse_message(CLASS_B_SVANOE, NOW)
        self.assertEqual((u.kind, u.ais_class, u.message_type), ("position", "B", "StandardClassBPositionReport"))
        self.assertIsNone(u.nav_status, "klass B sänder ingen navigationsstatus")
        self.assertIsNone(u.cog, "360 = kurs saknas")
        self.assertIsNone(u.heading, "511 = riktning saknas")
        self.assertEqual(u.sog, 0.0)
        self.assertFalse(u.has_static)

    def test_static_report_part_a_is_name_only(self):
        u = ais.parse_message(STATIC_REPORT_A_SASKIA, NOW)
        self.assertEqual((u.kind, u.name, u.ais_class), ("static", "SASKIA", "B"))
        self.assertFalse(u.has_static)
        self.assertEqual(ais.static_fields(u), {"ship_name": "SASKIA"})

    def test_part_a_never_wipes_a_known_type(self):
        ferry = vessel(type_=69)
        ais.apply_static(ferry, ais.parse_message(STATIC_REPORT_A_SASKIA, NOW))
        self.assertEqual(ferry.ship_type, 69)
        self.assertEqual(ferry.length_m, 195)

    def test_static_report_part_b(self):
        u = ais.parse_message(static_report_b(type_=60, length=(80, 30), width=(5, 4)), NOW)
        self.assertTrue(u.has_static)
        self.assertEqual((u.ship_type, u.length_m, u.width_m, u.call_sign), (60, 110, 9, "SFB1"))
        self.assertFalse(u.has_voyage, "klass B har ingen destination eller ETA")

    def test_extended_class_b_carries_static_data(self):
        msg = {
            "MetaData": {"MMSI": 265000003, "ShipName": "", "time_utc": _utc(NOW)},
            "MessageType": "ExtendedClassBPositionReport",
            "Message": {"ExtendedClassBPositionReport": {
                "UserID": 265000003, "Valid": True, "Sog": 11.5, "Cog": 180.0, "TrueHeading": 181,
                "Latitude": 58.91, "Longitude": 17.97, "Name": "WAXHOLM III", "Type": 60,
                "Dimension": {"A": 20, "B": 12, "C": 4, "D": 3},
            }},
        }
        u = ais.parse_message(msg, NOW)
        self.assertEqual((u.kind, u.has_static, u.ship_type, u.length_m, u.name), ("position", True, 60, 32, "WAXHOLM III"))
        self.assertEqual((u.cog, u.heading), (180.0, 181))

    def test_long_range_is_class_a_with_status(self):
        msg = {
            "MetaData": {"MMSI": 265000004, "time_utc": _utc(NOW)},
            "MessageType": "LongRangeAisBroadcastMessage",
            "Message": {"LongRangeAisBroadcastMessage": {
                "UserID": 265000004, "Valid": True, "NavigationalStatus": 0, "Sog": 17, "Cog": 45,
                "Latitude": 57.64, "Longitude": 18.27, "PositionLatency": False,
            }},
        }
        u = ais.parse_message(msg, NOW)
        self.assertEqual((u.kind, u.ais_class, u.nav_status, u.sog), ("position", "A", 0, 17.0))

    def test_type_zero_means_unknown(self):
        self.assertIsNone(ais.parse_message(static_msg(type_=0), NOW).ship_type)

    def test_class_b_passenger_ferry_can_arrive(self):
        update = ais.parse_message(static_report_b(type_=60, length=(90, 25)), NOW)
        ferry = FerryArrival(mmsi=update.mmsi)
        ais.apply_static(ferry, update)
        for minutes, point, sog in ((0, APPROACH, 12), (6, BERTH, 3)):
            t = NOW + dt.timedelta(minutes=minutes)
            ais.apply_position(ferry, ais.parse_message(class_b_position(ferry.mmsi, *point, sog, at=t), t))
            reason = ais.evaluate(ferry, t)
        self.assertEqual(reason, ais.REASON_SLOWING)


class MapTests(TestCase):
    def test_map_shows_only_fresh_positions(self):
        from maritime import explain
        from maritime.models import AisVessel
        AisVessel.objects.create(mmsi=265000010, name="FRESH", ship_type=70, ais_class="A",
                                 latitude=59.35, longitude=18.11, position_at=NOW - dt.timedelta(minutes=10))
        AisVessel.objects.create(mmsi=265000011, name="STALE", ship_type=60, ais_class="B",
                                 latitude=59.35, longitude=18.11, position_at=NOW - dt.timedelta(hours=3))
        block = explain.build(NOW)
        self.assertEqual([r["name"] for r in block["map"]], ["FRESH"])
        self.assertEqual(block["mapSummary"]["stale"], 1)
        self.assertEqual(block["map"][0]["typeLabel"], "Lastfartyg")
        self.assertFalse(block["map"][0]["passenger"])

    def test_message_type_table_covers_the_whole_schema(self):
        from maritime import explain
        block = explain.build(NOW)
        self.assertEqual(len(block["messageTypes"]), 25)
        self.assertEqual({t["type"] for t in block["messageTypes"] if t["subscribed"]}, set(ais.MESSAGE_TYPES))


class PendingBufferTests(SimpleTestCase):
    """
    Positioner medan fartygstypen är okänd spelas upp i ordning. Med bara den senaste
    positionen sågs en färja som saktade in innan typen hördes först vid kaj -- och
    blev aldrig en ankomst.
    """

    def replay(self, points):
        v = vessel()
        buffer = None
        for minutes, point, sog in points:
            update = ais.parse_message(position_msg(v.mmsi, *point, sog, at=NOW + dt.timedelta(minutes=minutes)), NOW)
            buffer = ais.buffer_position(buffer, update)
        reasons = []
        for update in sorted(buffer, key=lambda u: u.timestamp):
            ais.apply_position(v, update)
            reasons.append(ais.evaluate(v, NOW + dt.timedelta(minutes=points[-1][0])))
        return buffer, reasons

    def test_slowing_before_the_type_arrives_is_still_an_arrival(self):
        _, reasons = self.replay([(0, APPROACH, 14.0), (3, APPROACH, 8.0), (6, BERTH, 2.0)])
        self.assertIn(ais.REASON_SLOWING, reasons)

    def test_only_the_last_position_would_have_missed_it(self):
        _, reasons = self.replay([(6, BERTH, 2.0)])
        self.assertNotIn(ais.REASON_SLOWING, reasons)

    def test_the_buffer_keeps_half_an_hour(self):
        buffer, _ = self.replay([(0, APPROACH, 14.0), (40, APPROACH, 8.0), (45, BERTH, 2.0)])
        self.assertEqual(len(buffer), 2)
