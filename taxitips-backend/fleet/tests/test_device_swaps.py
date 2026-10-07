"""
Telefonbyte: högst ett per kalendermånad, admin kan ge extra.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from django.utils import timezone

from billing.models import Device
from fleet import device_swaps
from fleet.tests.base import FleetTestCase

STOCKHOLM = ZoneInfo("Europe/Stockholm")


class DeviceSwapTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.company = self.make_company()
        self.user_id = uuid.uuid4()
        self.now = datetime(2026, 10, 15, 12, 0, tzinfo=STOCKHOLM)

    def _phone(self, label="Telefon"):
        return Device.objects.create(
            id=uuid.uuid4(),
            company_id=self.company.id,
            token=f"install-{uuid.uuid4().hex}",
            label=label,
            kind="owner_app",
            notify_prefs={},
            created_at=self.now,
            last_seen_at=self.now,
        )

    def test_first_swap_ok_second_blocked(self):
        a = self._phone("A")
        b = self._phone("B")
        c = self._phone("C")

        r0 = device_swaps.link_account_device(
            user_id=self.user_id, device=a, via="owner_app", now=self.now,
        )
        self.assertFalse(r0["is_swap"])
        self.assertEqual(r0["remaining"], 1)

        r1 = device_swaps.link_account_device(
            user_id=self.user_id, device=b, via="owner_app", now=self.now,
        )
        self.assertTrue(r1["is_swap"])
        self.assertEqual(r1["remaining"], 0)

        with self.assertRaises(device_swaps.DeviceSwapError) as ctx:
            device_swaps.link_account_device(
                user_id=self.user_id, device=c, via="owner_app", now=self.now,
            )
        self.assertEqual(ctx.exception.reason, "device_swap_limit")
        self.assertIn("en gång", ctx.exception.message)

    def test_same_phone_again_is_not_a_swap(self):
        phone = self._phone()
        device_swaps.link_account_device(
            user_id=self.user_id, device=phone, via="owner_app", now=self.now,
        )
        again = device_swaps.link_account_device(
            user_id=self.user_id, device=phone, via="owner_app", now=self.now,
        )
        self.assertFalse(again["is_swap"])
        self.assertEqual(device_swaps.swaps_used(self.user_id, now=self.now), 0)

    def test_admin_grant_allows_extra_swap(self):
        a = self._phone("A")
        b = self._phone("B")
        c = self._phone("C")
        device_swaps.link_account_device(
            user_id=self.user_id, device=a, via="owner_app", now=self.now,
        )
        device_swaps.link_account_device(
            user_id=self.user_id, device=b, via="owner_app", now=self.now,
        )
        with self.assertRaises(device_swaps.DeviceSwapError):
            device_swaps.link_account_device(
                user_id=self.user_id, device=c, via="owner_app", now=self.now,
            )

        grant = device_swaps.grant_extra_swap(
            user_id=self.user_id, actor_user_id=uuid.uuid4(), note="Support", now=self.now,
        )
        self.assertEqual(grant["remaining"], 1)
        self.assertEqual(grant["month"], "2026-10")

        r = device_swaps.link_account_device(
            user_id=self.user_id, device=c, via="owner_app", now=self.now,
        )
        self.assertTrue(r["is_swap"])
        self.assertEqual(r["remaining"], 0)

    def test_admin_override_bypasses_limit(self):
        a = self._phone("A")
        b = self._phone("B")
        c = self._phone("C")
        device_swaps.link_account_device(
            user_id=self.user_id, device=a, via="owner_app", now=self.now,
        )
        device_swaps.link_account_device(
            user_id=self.user_id, device=b, via="owner_app", now=self.now,
        )
        r = device_swaps.link_account_device(
            user_id=self.user_id, device=c, via="owner_app",
            admin_override=True, actor_user_id=uuid.uuid4(), now=self.now,
        )
        self.assertTrue(r["is_swap"])
        # Admin-override räknas inte mot användarens kvot.
        self.assertEqual(device_swaps.swaps_used(self.user_id, now=self.now), 1)

    def test_month_boundary_resets(self):
        a = self._phone("A")
        b = self._phone("B")
        c = self._phone("C")
        oct_now = self.now
        device_swaps.link_account_device(
            user_id=self.user_id, device=a, via="owner_app", now=oct_now,
        )
        device_swaps.link_account_device(
            user_id=self.user_id, device=b, via="owner_app", now=oct_now,
        )
        self.assertEqual(device_swaps.remaining_swaps(self.user_id, now=oct_now), 0)

        nov = datetime(2026, 11, 1, 0, 5, tzinfo=STOCKHOLM)
        self.assertEqual(device_swaps.swaps_used(self.user_id, now=nov), 0)
        self.assertEqual(device_swaps.remaining_swaps(self.user_id, now=nov), 1)
        r = device_swaps.link_account_device(
            user_id=self.user_id, device=c, via="owner_app", now=nov,
        )
        self.assertTrue(r["is_swap"])
        self.assertEqual(r["remaining"], 0)

    def test_summary_for_admin(self):
        a = self._phone("A")
        b = self._phone("B")
        device_swaps.link_account_device(
            user_id=self.user_id, device=a, via="owner_app", now=self.now,
        )
        later = datetime(2026, 10, 15, 13, 0, tzinfo=STOCKHOLM)
        device_swaps.link_account_device(
            user_id=self.user_id, device=b, via="owner_app", now=later,
        )
        summary = device_swaps.summary_for(self.user_id, now=later)
        self.assertEqual(summary["used"], 1)
        self.assertEqual(summary["limit"], 1)
        self.assertEqual(summary["remaining"], 0)
        self.assertEqual(summary["month"], "2026-10")
        self.assertEqual(len(summary["history"]), 2)
        self.assertTrue(summary["history"][0]["isSwap"])
        self.assertFalse(summary["history"][1]["isSwap"])
