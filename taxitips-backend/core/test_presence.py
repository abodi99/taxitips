"""
"I tjänst": en grov ruta med kort livslängd ersätter körområdet i notisbeslutet.
Inget sparas utan brytaren, rutan skickas aldrig tillbaka, och utgångna rader
gallras.
"""

from __future__ import annotations

import datetime as dt
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from core import notify, presence
from core.models import DevicePresence, SeverityTier
from core.test_api import DEVICE_TOKEN, ApiTestCase
from core.test_notify import FakeDevice, SupabaseCompanyMixin, opportunity

MALMO_C = (55.6092, 13.0007)
LUND_C = (55.7056, 13.1868)
STOCKHOLM_C = (59.3303, 18.0588)


class CellTests(SimpleTestCase):
    def test_nearby_positions_share_a_cell_and_the_cell_is_not_the_position(self):
        a = presence.cell_for(55.604, 13.003)
        b = presence.cell_for(55.611, 13.041)
        self.assertEqual(a, b)
        self.assertNotEqual(a, (55.604, 13.003))

    def test_the_cell_centre_is_within_a_few_km_of_the_position(self):
        for lat, lon in (MALMO_C, STOCKHOLM_C, (67.8558, 20.2253)):
            cell_lat, cell_lon = presence.cell_for(lat, lon)
            self.assertLess(presence.haversine_km(lat, lon, cell_lat, cell_lon), 4.5)


def on_duty_at(lat, lon, *, minutes_left=30):
    now = timezone.now()
    cell_lat, cell_lon = presence.cell_for(lat, lon)
    return DevicePresence(
        device_id="00000000-0000-0000-0000-000000000001", cell_lat=cell_lat, cell_lon=cell_lon,
        updated_at=now, expires_at=now + dt.timedelta(minutes=minutes_left),
    )


class DecideTests(TestCase):
    def tip(self, lat, lon):
        return opportunity(severity_tier=SeverityTier.LINE_PAUSED, demand_score=80, lat=lat, lon=lon)

    def test_on_duty_nearby_is_notified_without_an_area(self):
        match = notify.decide({}, self.tip(*LUND_C), on_duty_at(*MALMO_C))
        self.assertEqual((match.ok, match.reason), (True, "near_driver"))

    def test_on_duty_far_away_is_not_notified_even_inside_the_area(self):
        match = notify.decide({"counties": ["12"]}, self.tip(*MALMO_C), on_duty_at(*STOCKHOLM_C))
        self.assertEqual((match.ok, match.reason), (False, "too_far_from_driver"))

    def test_the_driver_can_still_switch_notifications_or_types_off(self):
        tip = self.tip(*LUND_C)
        self.assertEqual(notify.decide({"enabled": False}, tip, on_duty_at(*MALMO_C)).reason, "notifications_off")
        self.assertEqual(
            notify.decide({"types": {"line_paused": False}}, tip, on_duty_at(*MALMO_C)).reason, "type_off:line_paused"
        )

    def test_a_tip_without_coordinates_is_not_near_anyone(self):
        unplaced = opportunity(severity_tier=SeverityTier.LINE_PAUSED, demand_score=80, lat=None, lon=None)
        self.assertEqual(notify.decide({}, unplaced, on_duty_at(*MALMO_C)).reason, "unplaced_tip")

    def test_without_presence_the_area_decides_as_before(self):
        self.assertEqual(notify.decide({"counties": ["12"]}, self.tip(*MALMO_C)).reason, "match")

    def test_new_reason_codes_are_documented(self):
        self.assertIn("near_driver", notify.REASONS)
        self.assertIn("too_far_from_driver", notify.REASONS)


class CycleTests(SupabaseCompanyMixin, TestCase):
    def test_the_push_cycle_uses_the_fresh_cell_and_ignores_an_expired_one(self):
        tip = opportunity(severity_tier=SeverityTier.LINE_PAUSED, demand_score=80, lat=LUND_C[0], lon=LUND_C[1])
        near, stale = FakeDevice(prefs={}), FakeDevice(prefs={})
        now = timezone.now()
        presence.set_on_duty(near.id, *MALMO_C, now)
        presence.set_on_duty(stale.id, *MALMO_C, now - presence.TTL - dt.timedelta(minutes=1))

        with patch.object(notify, "_devices", return_value=[near, stale]):
            plan = notify.plan_cycle(now=now)
        item = next(p for p in plan if p["external_id"] == tip.external_id)
        self.assertEqual([r["reason"] for r in item["recipients"]], ["near_driver"])
        self.assertEqual([r["reason"] for r in item["rejected"]], ["no_area"])

    def test_expired_rows_are_purged_and_fresh_ones_kept(self):
        now = timezone.now()
        fresh, old = FakeDevice(), FakeDevice()
        presence.set_on_duty(fresh.id, *MALMO_C, now)
        presence.set_on_duty(old.id, *MALMO_C, now - dt.timedelta(hours=2))
        self.assertEqual(presence.purge_expired(now), 1)
        self.assertEqual(list(DevicePresence.objects.values_list("device_id", flat=True)), [fresh.id])

    def test_one_row_per_device_and_no_history(self):
        device = FakeDevice()
        now = timezone.now()
        presence.set_on_duty(device.id, *MALMO_C, now)
        presence.set_on_duty(device.id, *STOCKHOLM_C, now + dt.timedelta(minutes=5))
        self.assertEqual(DevicePresence.objects.count(), 1)
        self.assertEqual(
            (DevicePresence.objects.get().cell_lat, DevicePresence.objects.get().cell_lon),
            presence.cell_for(*STOCKHOLM_C),
        )


class PresenceApiTests(ApiTestCase):
    def post(self, body, position=None, token=DEVICE_TOKEN):
        headers = {"x-device-token": token} if token else {}
        if position:
            headers["x-tt-position"] = position
        return self.client.post("/api/presence", body, content_type="application/json", headers=headers)

    def test_on_stores_only_the_cell_and_never_echoes_it(self):
        res = self.post({"on": True}, position="55.60,13.00")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body["on"])
        row = DevicePresence.objects.get(device_id=self.device.id)
        self.assertEqual((row.cell_lat, row.cell_lon), presence.cell_for(55.60, 13.00))
        # Svaret bär bara läge, livslängd och radie -- varken positionen eller rutan.
        self.assertEqual(set(body), {"ok", "on", "expiresAt", "radiusKm", "ttlMinutes"})
        self.assertNotIn(str(row.cell_lat), res.content.decode())
        self.assertTrue(self.client.get("/api/presence", headers={"x-device-token": DEVICE_TOKEN}).json()["on"])

    def test_on_without_a_position_is_refused_and_nothing_is_stored(self):
        res = self.post({"on": True})
        self.assertEqual((res.status_code, res.json()["error"]), (400, "no_position"))
        self.assertFalse(DevicePresence.objects.exists())

    def test_off_removes_the_row_at_once(self):
        self.post({"on": True}, position="55.60,13.00")
        res = self.post({"on": False})
        self.assertEqual((res.status_code, res.json()["on"]), (200, False))
        self.assertFalse(DevicePresence.objects.exists())

    def test_without_access_nothing_is_stored(self):
        res = self.post({"on": True}, position="55.60,13.00", token="unknown-token")
        self.assertEqual(res.status_code, 403)
        self.assertFalse(DevicePresence.objects.exists())
