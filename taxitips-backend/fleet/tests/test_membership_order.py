"""
§14: portalen köper ett medlemskap i ETT län -- utan registreringsnummer.

En orderpost utan platta ska bli en kontobaserad plats (en licens utan bil), och
tilldelningen (kontot som köper, eller en annan e-post) följer med ordern.
Med platta är allt som förut (en billicens).
"""

from __future__ import annotations

from fleet import access, orders
from fleet.models import License, VehicleAssignment
from fleet.tests.base import FleetTestCase


class MembershipOrderTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.company = self.make_company()
        self.make_subscription(self.company, days_left=20)
        self.owner = self.make_owner(self.company)

    def _buy(self, spec):
        plan = orders.plan_change(self.company.id, add_vehicles=[spec])
        order = orders.create_order(self.company.id, plan, created_by=self.owner.user_id)
        orders.mark_order_paid(order)
        return License.objects.get(company_id=self.company.id)

    def test_a_plate_less_order_is_a_membership_without_a_vehicle(self):
        license = self._buy(orders.VehicleSpec(base_county="12", assign_self=True))
        self.assertEqual(license.base_county, "12")
        # Ingen bil knöts: platsen hör till kontot.
        self.assertFalse(VehicleAssignment.objects.filter(license=license).exists())
        self.assertTrue(license.is_assigned_to(self.owner.user_id))
        self.assertEqual(access.license_counties(license.id), ("12",))

    def test_the_place_can_be_assigned_to_another_email(self):
        license = self._buy(
            orders.VehicleSpec(base_county="14", assignee_email="forare@taxi.test")
        )
        self.assertEqual(license.assignee_email, "forare@taxi.test")
        self.assertIsNone(license.assignee_user_id)

    def test_a_plate_still_creates_a_vehicle_license(self):
        # Regression: med registreringsnummer blir det en billicens som förut.
        license = self._buy(orders.VehicleSpec(plate="ABC123", base_county="12"))
        self.assertTrue(license.assignments.filter(ended_at__isnull=True).exists())
