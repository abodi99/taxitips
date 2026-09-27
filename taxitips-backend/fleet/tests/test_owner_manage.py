"""
Ägaren hanterar bilar och förare i appen: län och borttagning för provbilar,
namn på förarnas telefoner. Aldrig ett annat bolags, och aldrig en betald bil
direkt (den avslutas vid förnyelse, så att fakturan stämmer).
"""

from __future__ import annotations

import json

from django.test import Client, override_settings

from billing.models import Device
from fleet.models import DeviceApproval, License, LicenseCounty, Trial
from fleet.tests.base import FleetTestCase
from fleet.tests.test_support import SECRET, jwt


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class OwnerManageTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.data = self.full_setup(county="01", plate="PROV01")
        License.objects.filter(id=self.data["license"].id).update(status=License.Status.TRIAL)
        self.data["license"].refresh_from_db()
        self.owner = str(self.data["owner"].user_id)

    def post(self, path, body=None, user=None):
        return self.client.post(
            path, data=json.dumps(body or {}), content_type="application/json",
            headers={"authorization": f"Bearer {jwt(user or self.owner)}"},
        )

    def test_the_owner_moves_a_trial_car_to_another_county(self):
        license = self.data["license"]
        response = self.post(f"/api/fleet/trial/vehicles/{license.id}/county", {"base": "12"})
        self.assertEqual(response.status_code, 200, response.content)
        license.refresh_from_db()
        self.assertEqual(license.base_county, "12")
        active = LicenseCounty.objects.filter(license=license, active_to__isnull=True)
        self.assertEqual([c.county_code for c in active], ["12"])

    def test_the_owner_removes_a_trial_car_and_its_shift_ends(self):
        from fleet import sessions

        license = self.data["license"]
        sessions.start_session(device_id=self.data["device"].id, license_id=license.id)
        response = self.post(f"/api/fleet/trial/vehicles/{license.id}/remove")
        self.assertEqual(response.status_code, 200, response.content)
        license.refresh_from_db()
        self.assertEqual(license.status, License.Status.CANCELED)
        self.assertIsNone(sessions.active_session_for_device(self.data["device"].id))

    def test_a_paid_car_is_never_changed_directly(self):
        license = self.data["license"]
        License.objects.filter(id=license.id).update(status=License.Status.ACTIVE)
        for path in (f"/api/fleet/trial/vehicles/{license.id}/county", f"/api/fleet/trial/vehicles/{license.id}/remove"):
            with self.subTest(path=path):
                self.assertEqual(self.post(path, {"base": "12"}).json()["reason"], "paid_license")

    def test_another_companys_car_does_not_exist_for_you(self):
        other = self.full_setup(county="14", plate="ANNAN1")
        response = self.post(f"/api/fleet/trial/vehicles/{other['license'].id}/remove")
        self.assertEqual(response.status_code, 404)

    def test_the_owner_names_a_drivers_phone(self):
        approval = self.data["approval"]
        response = self.post(f"/api/fleet/approvals/{approval.id}/label", {"label": "  Anna  Svensson "})
        self.assertEqual(response.json()["label"], "Anna Svensson", response.content)
        self.assertEqual(DeviceApproval.objects.get(id=approval.id).label, "Anna Svensson")
        self.assertEqual(Device.objects.get(id=approval.device_id).label, "Anna Svensson")
        self.assertEqual(self.post(f"/api/fleet/approvals/{approval.id}/label", {"label": " "}).json()["reason"], "label_required")

    def test_a_driver_without_rights_cannot_manage(self):
        driver = self.make_owner(self.data["company"], role="driver")
        response = self.post(
            f"/api/fleet/trial/vehicles/{self.data['license'].id}/remove", user=str(driver.user_id),
        )
        self.assertEqual(response.status_code, 403)
