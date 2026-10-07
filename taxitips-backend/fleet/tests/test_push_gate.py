"""
Mottagargrinden (fleet/push_gate.py) för det KONTOBASERADE medlemskapet.

Platsen tilldelas kontot, och appen håller en öppen MembershipSession. Den
vägen skapar varken DeviceApproval eller VehicleSession. Före den här grenen
svarade grinden `device_not_approved` och en provägares telefon fick aldrig en
enda notis -- medan `access._membership_access` släppte in samma konto i appen.
Notisen och listan ska vila på samma rättighet (§3 i AGENTS.md).
"""

from __future__ import annotations

from billing.models import Device
from fleet import membership, sessions
from fleet.models import DeviceApproval
from fleet.push_gate import can_receive
from fleet.tests.base import FleetTestCase


class MembershipGateTests(FleetTestCase):
    def _membership_phone(self, county="12"):
        """En telefon utan godkänd bil, men med ett medlemskap på kontot."""
        data = self.full_setup(county=county)
        device, license = data["device"], data["license"]
        owner_id = data["owner"].user_id
        # Ingen bil: bara kontots plats.
        DeviceApproval.objects.filter(device_id=device.id).delete()
        Device.objects.filter(id=device.id).update(user_id=owner_id)
        membership.assign_to_self(license=license, user_id=owner_id)
        sessions.start_membership_session(
            user_id=owner_id, license_id=license.id, device_id=device.id,
        )
        return Device.objects.get(id=device.id), data

    def test_an_open_membership_lets_the_phone_receive(self):
        device, _ = self._membership_phone(county="12")
        verdict = can_receive(device, {"area_codes": ["12"]})
        self.assertTrue(verdict.ok, verdict.reason)
        self.assertEqual(verdict.reason, "membership")

    def test_outside_the_licensed_county_is_still_blocked(self):
        device, _ = self._membership_phone(county="12")
        verdict = can_receive(device, {"area_codes": ["01"]})
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.reason, "outside_licensed_county")

    def test_without_a_session_the_phone_is_still_blocked(self):
        # Regression: en olänkad telefon får fortfarande inget.
        data = self.full_setup(county="12")
        device = Device.objects.get(id=data["device"].id)
        DeviceApproval.objects.filter(device_id=device.id).delete()
        Device.objects.filter(id=device.id).update(user_id=data["owner"].user_id)
        verdict = can_receive(device, {"area_codes": ["12"]})
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.reason, "device_not_approved")
