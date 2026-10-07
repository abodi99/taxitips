"""
Notisinställningar som någon annan än föraren ändrar: kundens administratör i
portalen och plattformens personal i adminwebben (fleet/notify_settings.py).

Det som går sönder tyst här är behörigheten -- en administratör som kan ändra
ett annat företags telefon, eller ett län som smyger sig in utanför licensen
och sedan aldrig ger en notis -- och standarden som aldrig når nya telefoner.
"""

from __future__ import annotations

import json
import uuid

from django.test import Client, override_settings
from django.utils import timezone

from billing.models import Device
from fleet import pairing
from fleet.models import AuditEvent, CompanyNotifyDefault, StaffRole
from fleet.tests.base import FleetTestCase
from fleet.tests.test_support import SECRET, jwt


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class CustomerNotifySettingsTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.data = self.full_setup(county="01", plate="NOT001")
        self.owner = str(self.data["owner"].user_id)
        self.device = self.data["device"]

    def call(self, method, path, body=None, user=None):
        headers = {"authorization": f"Bearer {jwt(user or self.owner)}"}
        if method == "get":
            return self.client.get(path, headers=headers)
        return self.client.post(
            path, data=json.dumps(body or {}), content_type="application/json", headers=headers,
        )

    def test_the_owner_sees_every_phone_with_its_mode(self):
        response = self.call("get", "/api/fleet/notify-settings")
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertTrue(data["canManage"])
        phone = next(p for p in data["phones"] if p["deviceId"] == str(self.device.id))
        # En telefon som aldrig rört något har Rekommenderat.
        self.assertEqual(phone["preset"], "recommended")
        self.assertEqual(phone["entitledCounties"], ["01"])
        self.assertEqual([p["id"] for p in data["presetCatalog"]][:4],
                         ["recommended", "strongest", "everything", "silent"])

    def test_an_owner_app_phone_shows_the_companys_counties(self):
        # Ägarapp: telefonraden bär kontot och har inget godkännande. Utan
        # fallbacken visade portalen inga län för en telefon som i appen såg
        # hela bolagets, och administratören kunde inte sätta området.
        from fleet import notify_settings

        owner_app = Device.objects.create(
            id=uuid.uuid4(), company_id=self.data["company"].id, token="owner-app-token",
            label="Ägarapp", kind="owner_app", notify_prefs={},
            created_at=timezone.now(), user_id=self.data["owner"].user_id,
        )
        counties, restricted = notify_settings.device_entitlement(owner_app)
        self.assertEqual(counties, ["01"])
        self.assertTrue(restricted)

    def test_the_owner_changes_a_drivers_phone(self):
        response = self.call(
            "post", f"/api/fleet/devices/{self.device.id}/notify-prefs",
            {"weak": True, "quietHours": {"from": 1, "to": 6}, "maxPerHour": 4,
             "categories": {"road": False}},
        )
        self.assertEqual(response.status_code, 200, response.content)
        prefs = Device.objects.get(id=self.device.id).notify_prefs
        self.assertIs(prefs["weak"], True)
        self.assertEqual(prefs["quietHours"], {"from": 1, "to": 6})
        self.assertEqual(prefs["maxPerHour"], 4)
        self.assertIs(prefs["categories"]["road"], False)
        self.assertEqual(response.json()["phone"]["preset"], "custom")
        event = AuditEvent.objects.get(action="device_notify_prefs_changed")
        self.assertEqual(event.actor_kind, "customer")
        self.assertEqual(str(event.subject_id), str(self.device.id))

    def test_a_preset_is_one_tap(self):
        self.call("post", f"/api/fleet/devices/{self.device.id}/notify-prefs", {"preset": "silent"})
        self.assertIs(Device.objects.get(id=self.device.id).notify_prefs["enabled"], False)
        self.call("post", f"/api/fleet/devices/{self.device.id}/notify-prefs", {"preset": "recommended"})
        prefs = Device.objects.get(id=self.device.id).notify_prefs
        self.assertIs(prefs["enabled"], True)
        self.assertIs(prefs["weak"], False)

    def test_counties_never_widen_beyond_the_cars_licence(self):
        self.call(
            "post", f"/api/fleet/devices/{self.device.id}/notify-prefs", {"counties": ["01", "12"]},
        )
        self.assertEqual(Device.objects.get(id=self.device.id).notify_prefs["counties"], ["01"])
        # Inga län kryssade = hela bilens område, aldrig tyst utan att det syns.
        self.call("post", f"/api/fleet/devices/{self.device.id}/notify-prefs", {"counties": []})
        self.assertEqual(Device.objects.get(id=self.device.id).notify_prefs["counties"], ["01"])

    def test_another_companys_phone_does_not_exist_for_you(self):
        other = self.full_setup(county="14", plate="ANNAN2")
        response = self.call(
            "post", f"/api/fleet/devices/{other['device'].id}/notify-prefs", {"preset": "silent"},
        )
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("enabled", Device.objects.get(id=other["device"].id).notify_prefs)

    def test_a_driver_without_manage_devices_cannot_change_others(self):
        driver = self.make_owner(self.data["company"], role="driver")
        response = self.call(
            "post", f"/api/fleet/devices/{self.device.id}/notify-prefs", {"preset": "silent"},
            user=str(driver.user_id),
        )
        self.assertEqual(response.status_code, 403)
        response = self.call("post", "/api/fleet/notify-default", {"preset": "silent"},
                             user=str(driver.user_id))
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("enabled", Device.objects.get(id=self.device.id).notify_prefs)

    def test_the_company_default_reaches_a_new_phone_when_it_is_paired(self):
        response = self.call(
            "post", "/api/fleet/notify-default",
            {"weak": True, "quietHours": {"from": 1, "to": 6}, "counties": ["12"], "pauseHours": 3},
        )
        self.assertEqual(response.status_code, 200, response.content)
        stored = CompanyNotifyDefault.objects.get(company_id=self.data["company"].id).prefs
        # Bara reglerna: område och paus hör inte till en standard.
        self.assertNotIn("counties", stored)
        self.assertNotIn("pausedUntil", stored)

        paired = pairing.approve_device(
            company_id=self.data["company"].id, license=self.data["license"],
            vehicle=self.data["vehicle"], approved_by=self.data["owner"].user_id,
            installation_id=f"install-{uuid.uuid4().hex}", device_label="Ny telefon",
            approval_label="Ny telefon",
        )
        prefs = Device.objects.get(id=paired.device_id).notify_prefs
        self.assertIs(prefs["weak"], True)
        self.assertEqual(prefs["quietHours"], {"from": 1, "to": 6})
        # Området är bilens län, inte standardens.
        self.assertEqual(prefs["counties"], ["01"])

    def test_a_phone_already_in_the_company_keeps_the_drivers_own_choices(self):
        Device.objects.filter(id=self.device.id).update(notify_prefs={"counties": ["01"], "weak": False})
        self.call("post", "/api/fleet/notify-default", {"preset": "silent"})
        pairing.approve_device(
            company_id=self.data["company"].id, license=self.data["license"],
            vehicle=self.data["vehicle"], approved_by=self.data["owner"].user_id,
            installation_id=self.device.token, device_label="Förare 1", approval_label="Förare 1",
        )
        self.assertNotIn("enabled", Device.objects.get(id=self.device.id).notify_prefs)

    def test_apply_to_phones_rewrites_the_rules_but_not_the_area(self):
        Device.objects.filter(id=self.device.id).update(notify_prefs={"counties": ["01"]})
        response = self.call(
            "post", "/api/fleet/notify-default", {"preset": "everything", "applyToPhones": True},
        )
        self.assertEqual(response.json()["phonesChanged"], 1)
        prefs = Device.objects.get(id=self.device.id).notify_prefs
        self.assertIs(prefs["weak"], True)
        self.assertEqual(prefs["counties"], ["01"])


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class AdminNotifySettingsTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.data = self.full_setup(county="12", plate="ADM001")
        self.device = self.data["device"]
        self.sales = str(uuid.uuid4())
        StaffRole.objects.create(user_id=self.sales, role=StaffRole.Role.SALES)

    def post(self, path, body, user):
        return self.client.post(
            path, data=json.dumps(body), content_type="application/json",
            headers={"authorization": f"Bearer {jwt(user)}"},
        )

    def test_platform_staff_change_a_phone_and_it_is_logged(self):
        company = self.data["company"]
        response = self.post(
            f"/api/admin/companies/{company.id}/devices/{self.device.id}/notify-prefs",
            {"preset": "strongest"}, self.sales,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["phone"]["preset"], "strongest")
        event = AuditEvent.objects.get(action="admin_device_notify_prefs_changed")
        self.assertEqual(event.actor_kind, "platform_admin")
        self.assertEqual(str(event.actor_user_id), self.sales)
        self.assertEqual(event.detail["preset"], "strongest")

    def test_the_company_page_carries_the_notify_settings(self):
        response = self.client.get(
            f"/api/admin/companies/{self.data['company'].id}",
            headers={"authorization": f"Bearer {jwt(self.sales)}"},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["notify"]["phones"][0]["preset"], "recommended")

    def test_support_reads_but_does_not_change(self):
        support = str(uuid.uuid4())
        StaffRole.objects.create(user_id=support, role=StaffRole.Role.SUPPORT)
        company = self.data["company"]
        response = self.post(
            f"/api/admin/companies/{company.id}/devices/{self.device.id}/notify-prefs",
            {"preset": "silent"}, support,
        )
        self.assertEqual(response.status_code, 403)

    def test_a_phone_in_another_company_is_not_found_under_this_one(self):
        other = self.full_setup(county="14", plate="ADM002")
        response = self.post(
            f"/api/admin/companies/{self.data['company'].id}/devices/{other['device'].id}/notify-prefs",
            {"preset": "silent"}, self.sales,
        )
        self.assertEqual(response.status_code, 404)

    def test_a_customer_is_not_staff(self):
        response = self.post(
            f"/api/admin/companies/{self.data['company'].id}/notify-default",
            {"preset": "silent"}, str(self.data["owner"].user_id),
        )
        self.assertEqual(response.status_code, 403)
