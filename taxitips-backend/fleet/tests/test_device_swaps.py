"""
Telefonbyte: högst ett per kalendermånad, admin kan ge extra.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import Client, RequestFactory, override_settings
from django.utils import timezone

from billing.models import Device
from fleet import access, device_swaps
from fleet.tests.base import FleetTestCase
from fleet.tests.test_support import SECRET, jwt

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


@override_settings(SUPABASE_JWT_SECRET=SECRET, SUPABASE_URL="http://auth.test", SUPABASE_SERVICE_ROLE_KEY="svc")
class OneAccountOnePhoneTests(FleetTestCase):
    """
    Ägarens beslut 2026-10-11: ett konto, en telefon. Byter kontot telefon
    tappar den gamla inloggningen -- direkt i åtkomstkontrollen, och i
    Supabase Auth så att den inte kan förnya sin token.
    """

    def setUp(self):
        super().setUp()
        self.data = self.full_setup()
        self.user_id = str(self.data["owner"].user_id)
        self.token = jwt(self.user_id)

    def register(self, installation_id):
        with mock.patch("fleet.auth_admin.requests.post") as post:
            post.return_value.status_code = 204
            response = Client().post(
                "/api/device/session",
                data=json.dumps({"installation_id": installation_id, "platform": "android"}),
                content_type="application/json",
                headers={"authorization": f"Bearer {self.token}"},
            )
        return response, post

    def resolve(self, installation_id):
        request = RequestFactory().get(
            "/api/alerts",
            headers={"x-device-token": installation_id, "authorization": f"Bearer {self.token}"},
        )
        return access.resolve(request)

    def test_the_first_phone_does_not_sign_anyone_out(self):
        response, post = self.register("iphone-install-0001")
        self.assertEqual(response.status_code, 200, response.content)
        post.assert_not_called()
        self.assertNotEqual(self.resolve("iphone-install-0001").reason, "account_moved")

    def test_a_swap_signs_out_the_old_phone(self):
        self.register("iphone-install-0001")
        response, post = self.register("samsung-install-0001")
        self.assertEqual(response.status_code, 200, response.content)
        post.assert_called_once()
        url = post.call_args.args[0]
        self.assertEqual(url, "http://auth.test/auth/v1/logout?scope=others")
        # Den NYA telefonens token: den inloggningen ska behållas.
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], f"Bearer {self.token}")

        old = self.resolve("iphone-install-0001")
        self.assertEqual((old.ok, old.reason), (False, "account_moved"))
        self.assertIn("annan telefon", old.message)
        self.assertNotEqual(self.resolve("samsung-install-0001").reason, "account_moved")

    def test_a_phone_mid_login_is_not_stopped(self):
        """En ny telefon som ännu inte kopplats har aldrig haft kontot."""
        self.register("iphone-install-0001")
        Device.objects.create(
            id=uuid.uuid4(), company_id=self.data["company"].id, token="samsung-install-0001",
            label="Ny", kind="owner_app", notify_prefs={}, created_at=timezone.now(),
            last_seen_at=timezone.now(),
        )
        self.assertNotEqual(self.resolve("samsung-install-0001").reason, "account_moved")

    def test_the_limit_still_holds_and_the_old_phone_keeps_out(self):
        self.register("iphone-install-0001")
        self.register("samsung-install-0001")
        response, post = self.register("iphone-install-0001")
        self.assertEqual((response.status_code, response.json()["reason"]), (403, "device_swap_limit"))
        post.assert_not_called()
        self.assertEqual(self.resolve("iphone-install-0001").reason, "account_moved")

    def test_moving_back_with_an_extra_swap_flips_it(self):
        self.register("iphone-install-0001")
        self.register("samsung-install-0001")
        device_swaps.grant_extra_swap(user_id=self.user_id, actor_user_id=None, note="test")
        response, _post = self.register("iphone-install-0001")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertNotEqual(self.resolve("iphone-install-0001").reason, "account_moved")
        self.assertEqual(self.resolve("samsung-install-0001").reason, "account_moved")
