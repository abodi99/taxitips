"""
Telefonens körområde mot licensens län (fleet/device_prefs.py).

Felet som gav testerna: en bil med två län fick notiser bara i det ena. Kopplingen
satte telefonens län till baslänet, och när ett extra län tillkom såg det gamla
valet ut som en avsiktlig avsmalning och fick ligga kvar.
"""

from __future__ import annotations

from django.test import SimpleTestCase
from django.utils import timezone

from billing.models import Device
from fleet.device_prefs import ENTITLED_KEY, align_prefs_to_entitlement
from fleet.models import LicenseCounty
from fleet.tests.base import FleetTestCase


class AlignTests(SimpleTestCase):
    def test_a_county_added_to_the_licence_is_added_to_the_phone(self):
        prefs = {"counties": ["06"], ENTITLED_KEY: ["06"]}
        out, changed = align_prefs_to_entitlement(prefs, ["06", "12"])
        self.assertTrue(changed)
        self.assertEqual(out["counties"], ["06", "12"])
        self.assertEqual(out[ENTITLED_KEY], ["06", "12"])

    def test_a_county_the_driver_turned_off_stays_off(self):
        prefs = {"counties": ["12"], ENTITLED_KEY: ["06", "12"]}
        out, changed = align_prefs_to_entitlement(prefs, ["06", "12"])
        self.assertFalse(changed)
        self.assertEqual(out["counties"], ["12"])

    def test_old_prefs_without_a_record_get_the_whole_licence_once(self):
        out, changed = align_prefs_to_entitlement({"counties": ["06"]}, ["06", "12"])
        self.assertTrue(changed)
        self.assertEqual(out["counties"], ["06", "12"])
        again, changed_again = align_prefs_to_entitlement(out, ["06", "12"])
        self.assertFalse(changed_again)
        self.assertEqual(again, out)

    def test_a_county_no_longer_in_the_licence_is_removed(self):
        prefs = {"counties": ["06", "12"], ENTITLED_KEY: ["06", "12"]}
        out, _ = align_prefs_to_entitlement(prefs, ["06"])
        self.assertEqual(out["counties"], ["06"])

    def test_nothing_left_means_the_whole_licence(self):
        out, _ = align_prefs_to_entitlement({"counties": ["01"], ENTITLED_KEY: ["01"]}, ["06", "12"])
        self.assertEqual(out["counties"], ["06", "12"])

    def test_municipalities_outside_the_counties_are_dropped(self):
        prefs = {"counties": ["06"], "municipalities": ["0680", "1280"], ENTITLED_KEY: ["06", "12"]}
        out, changed = align_prefs_to_entitlement(prefs, ["06"])
        self.assertTrue(changed)
        self.assertEqual(out["municipalities"], ["0680"])

    def test_no_entitlement_touches_nothing(self):
        prefs = {"counties": ["06"]}
        self.assertEqual(align_prefs_to_entitlement(prefs, []), (prefs, False))


class PushCycleHealsTheAreaTests(FleetTestCase):
    def test_the_push_cycle_gives_the_phone_both_counties(self):
        from core import notify

        data = self.full_setup(county="06")
        device = data["device"]
        Device.objects.filter(id=device.id).update(push_token="tok", notify_prefs={"counties": ["06"]})
        LicenseCounty.objects.create(
            license=data["license"], county_code="12", kind=LicenseCounty.Kind.EXTRA,
            active_from=timezone.now(),
        )

        phones = notify._devices()

        self.assertEqual([d.id for d in phones], [device.id])
        self.assertEqual(phones[0].notify_prefs["counties"], ["06", "12"])
        device.refresh_from_db()
        self.assertEqual(device.notify_prefs["counties"], ["06", "12"])
