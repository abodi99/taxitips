"""
Åtkomstkontrollen: gamla tokens, spärrade telefoner, länsrättigheter och
gränsen mellan företag och roller.

Testerna går via HTTP där det går. Ett test som anropar `access.resolve()`
direkt bevisar att funktionen är rätt; ett som anropar `/api/alerts` bevisar
att vyn faktiskt använder den -- och det var den senare sortens fel som en
gång släppte igenom noll inloggade ägare.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.test import Client
from django.utils import timezone

from billing.models import Company
from core.models import Opportunity, SeverityTier
from fleet import access, licensing, pairing, roles, sessions
from fleet.models import (
    CompanyProfile,
    DeviceApproval,
    License,
    LicenseCounty,
    Subscription,
    SubscriptionStatus,
)
from fleet.roles import Perm, PermissionDenied
from fleet.tests.base import FleetTestCase

MALMO = {"lat": 55.6050, "lon": 13.0038}
STOCKHOLM = {"lat": 59.3300, "lon": 18.0600}


def tip(**overrides) -> Opportunity:
    now = timezone.now()
    fields = {
        "external_id": f"test:{uuid.uuid4()}",
        "kind": "transit", "mode": "train",
        "severity_tier": SeverityTier.LINE_PAUSED,
        "title": "Stopp i trafiken", "summary": "Ingen trafik.",
        "lat": MALMO["lat"], "lon": MALMO["lon"], "region": "skane",
        "area_codes": ["12"],
        "start_time": now - timedelta(minutes=10),
        "end_time": now + timedelta(hours=1),
        "demand_score": 85, "reasons": ["stoppad linje"], "rule_id": "train.line_paused",
    }
    fields.update(overrides)
    return Opportunity.objects.create(**fields)


class DriverAccessTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.data = self.full_setup(county="12")
        self.secret = self.data["secret"]
        sessions.start_session(
            device_id=self.data["device"].id, license_id=self.data["license"].id
        )

    def get_alerts(self, token=None, **params):
        return self.client.get(
            "/api/alerts", {**MALMO, **params},
            headers={"x-device-token": token or self.secret},
        ).json()

    def test_paired_driver_in_a_licensed_county_sees_tips(self):
        tip()
        body = self.get_alerts()
        self.assertTrue(body["entitled"], body)
        self.assertEqual(len(body["alerts"]), 1)

    def test_hashed_secret_is_the_credential_not_the_installation_id(self):
        """Installations-id:t i `devices.token` är inte längre ett bevis."""
        tip()
        body = self.get_alerts(token=self.data["device"].token)
        self.assertFalse(body["entitled"])

    def test_blocked_phone_loses_access_while_its_token_is_still_valid(self):
        """
        §3: åtkomsträtten gäller billicensen och måste kunna spärras även medan
        en gammal token fortfarande är giltig.
        """
        tip()
        self.assertTrue(self.get_alerts()["entitled"])

        pairing.block_device(approval=self.data["approval"], actor_user_id=None)

        body = self.get_alerts()
        self.assertFalse(body["entitled"])
        self.assertEqual(body["alerts"], [])

    def test_without_an_active_session_no_tips_are_handed_out(self):
        tip()
        session = sessions.active_session_for_device(self.data["device"].id)
        sessions.end_session(session, reason="driver_end")

        body = self.get_alerts()
        self.assertFalse(body["entitled"])
        self.assertEqual(body["reason"], "no_active_session")

    def test_a_county_the_licence_does_not_pay_for_is_not_visible(self):
        """Länsrättigheten hör till bilen. Ett filter kan inte vidga den (§5)."""
        tip(area_codes=["01"], lat=STOCKHOLM["lat"], lon=STOCKHOLM["lon"], region="sl")
        body = self.get_alerts(counties="01", **STOCKHOLM)
        self.assertEqual(body["alerts"], [])
        self.assertEqual(body.get("reason"), "no_entitled_county")

    def test_gps_position_alone_grants_nothing(self):
        """
        §5: GPS-position ger inte automatisk behörighet. Föraren står i
        Stockholm, licensen är köpt för Skåne.
        """
        tip(area_codes=["01"], lat=STOCKHOLM["lat"], lon=STOCKHOLM["lon"], region="sl")
        body = self.get_alerts(**STOCKHOLM)
        self.assertEqual(body["alerts"], [])

    def test_a_purchased_extra_county_becomes_visible(self):
        licensing.activate_extra_county(license=self.data["license"], county_code="01")
        tip(area_codes=["01"], lat=STOCKHOLM["lat"], lon=STOCKHOLM["lon"], region="sl")
        body = self.get_alerts(**STOCKHOLM)
        self.assertEqual(len(body["alerts"]), 1)

    def test_direct_link_to_a_tip_outside_the_licence_is_not_found(self):
        """§3: samma regler gäller detaljer och direktlänkar."""
        other = tip(area_codes=["01"], lat=STOCKHOLM["lat"], lon=STOCKHOLM["lon"])
        response = self.client.get(
            f"/api/opportunities/{other.id}", headers={"x-device-token": self.secret}
        )
        self.assertEqual(response.status_code, 404)

    def test_expired_period_locks_the_driver_out(self):
        tip()
        Subscription.objects.filter(company_id=self.data["company"].id).update(
            current_period_end=timezone.now() - timedelta(days=1),
            grace_until=None, status=SubscriptionStatus.ACTIVE,
        )
        body = self.get_alerts()
        self.assertFalse(body["entitled"])
        self.assertEqual(body["reason"], "period_expired")

    def test_ferries_and_events_use_the_same_gate(self):
        """
        §3: samma regler gäller lista, karta, detaljer, historik och
        realtidsflöden -- inte bara /api/alerts.
        """
        pairing.block_device(approval=self.data["approval"], actor_user_id=None)
        for path in ("/api/ferries", "/api/events", "/api/notifications"):
            with self.subTest(path=path):
                response = self.client.get(
                    path, {**MALMO}, headers={"x-device-token": self.secret}
                )
                body = response.json()
                entitled = body.get("entitled")
                self.assertTrue(
                    response.status_code in (401, 403) or entitled is False,
                    f"{path} gav {response.status_code}: {body}",
                )


class CompanyIsolationTests(FleetTestCase):
    """§11: företag och roller kan inte komma åt varandras data."""

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.a = self.full_setup(plate="AAA111", county="12")
        self.b = self.full_setup(plate="BBB222", county="01")
        # `full_setup` gör ett bolag per anrop; organisationsnumret krockar
        # inte eftersom ingen av dem är verifierad.
        sessions.start_session(device_id=self.a["device"].id, license_id=self.a["license"].id)

    def test_a_phone_cannot_start_a_session_on_another_companys_licence(self):
        with self.assertRaises(sessions.SessionError) as caught:
            sessions.start_session(
                device_id=self.a["device"].id, license_id=self.b["license"].id, force=True
            )
        self.assertEqual(caught.exception.reason, "not_approved")

    def test_a_pairing_code_cannot_cross_company_boundaries(self):
        with self.assertRaises(pairing.PairingError) as caught:
            pairing.issue_code(
                license=self.a["license"], vehicle=self.b["vehicle"], created_by=None
            )
        self.assertEqual(caught.exception.reason, "vehicle_company_mismatch")

    def test_a_licence_cannot_be_moved_to_another_companys_vehicle(self):
        with self.assertRaises(licensing.LicensingError) as caught:
            licensing.change_vehicle_permanently(
                license=self.a["license"], new_vehicle=self.b["vehicle"]
            )
        self.assertEqual(caught.exception.reason, "vehicle_company_mismatch")


class RolePermissionTests(FleetTestCase):
    """§1: bara behöriga personer får köpa, säga upp eller ändra ekonomi."""

    def test_owner_has_every_customer_permission(self):
        principal = roles.Principal(
            user_id=str(uuid.uuid4()), company_id=str(uuid.uuid4()), role=roles.OWNER,
            permissions=roles.permissions_for(roles.OWNER),
        )
        for permission in (
            Perm.PURCHASE, Perm.CANCEL_SUBSCRIPTION, Perm.MANAGE_VEHICLES,
            Perm.MANAGE_DEVICES, Perm.MANAGE_MEMBERS, Perm.TRANSFER_OWNERSHIP,
        ):
            with self.subTest(permission=permission):
                roles.require(principal, permission)

    def test_fleet_admin_cannot_buy_or_cancel(self):
        principal = roles.Principal(
            user_id=str(uuid.uuid4()), company_id=str(uuid.uuid4()), role=roles.FLEET_ADMIN,
            permissions=roles.permissions_for(roles.FLEET_ADMIN),
        )
        roles.require(principal, Perm.MANAGE_VEHICLES)
        for permission in (Perm.PURCHASE, Perm.CANCEL_SUBSCRIPTION):
            with self.subTest(permission=permission):
                with self.assertRaises(PermissionDenied):
                    roles.require(principal, permission)

    def test_finance_cannot_pair_phones(self):
        principal = roles.Principal(
            user_id=str(uuid.uuid4()), company_id=str(uuid.uuid4()), role=roles.FINANCE,
            permissions=roles.permissions_for(roles.FINANCE),
        )
        roles.require(principal, Perm.PURCHASE)
        with self.assertRaises(PermissionDenied):
            roles.require(principal, Perm.MANAGE_DEVICES)

    def test_driver_role_has_no_administrative_permissions(self):
        principal = roles.Principal(
            user_id=str(uuid.uuid4()), company_id=str(uuid.uuid4()), role=roles.DRIVER,
            permissions=roles.permissions_for(roles.DRIVER),
        )
        for permission in (Perm.VIEW_COMPANY, Perm.MANAGE_DEVICES, Perm.PURCHASE):
            with self.subTest(permission=permission):
                with self.assertRaises(PermissionDenied):
                    roles.require(principal, permission)

    def test_sales_can_invite_but_not_read_customer_billing(self):
        principal = roles.Principal(
            user_id=str(uuid.uuid4()), staff_role="sales",
            permissions=roles.staff_permissions_for("sales"),
        )
        roles.require(principal, Perm.CREATE_SALES_INVITE)
        for permission in (Perm.VIEW_BILLING, Perm.PURCHASE, Perm.REVIEW_CASES):
            with self.subTest(permission=permission):
                with self.assertRaises(PermissionDenied):
                    roles.require(principal, permission)

    def test_two_factor_is_required_for_money_once_enforced(self):
        principal = roles.Principal(
            user_id=str(uuid.uuid4()), company_id=str(uuid.uuid4()), role=roles.OWNER,
            aal="aal1", permissions=roles.permissions_for(roles.OWNER),
        )
        yesterday = (timezone.now() - timedelta(days=1)).isoformat()
        with self.settings(FLEET_TWO_FACTOR_REQUIRED_FROM=yesterday):
            with self.assertRaises(PermissionDenied) as caught:
                roles.require(principal, Perm.PURCHASE)
            self.assertEqual(caught.exception.reason, "two_factor_required")
            # Icke-ekonomiska behörigheter påverkas inte.
            roles.require(principal, Perm.VIEW_COMPANY)

    def test_two_factor_is_not_enforced_before_the_configured_date(self):
        """§2: införande utan oannonserad utelåsning."""
        principal = roles.Principal(
            user_id=str(uuid.uuid4()), company_id=str(uuid.uuid4()), role=roles.OWNER,
            aal="aal1", permissions=roles.permissions_for(roles.OWNER),
        )
        with self.settings(FLEET_TWO_FACTOR_REQUIRED_FROM=""):
            roles.require(principal, Perm.PURCHASE)
        tomorrow = (timezone.now() + timedelta(days=1)).isoformat()
        with self.settings(FLEET_TWO_FACTOR_REQUIRED_FROM=tomorrow):
            roles.require(principal, Perm.PURCHASE)

    def test_aal2_session_satisfies_the_requirement(self):
        principal = roles.Principal(
            user_id=str(uuid.uuid4()), company_id=str(uuid.uuid4()), role=roles.OWNER,
            aal="aal2", permissions=roles.permissions_for(roles.OWNER),
        )
        yesterday = (timezone.now() - timedelta(days=1)).isoformat()
        with self.settings(FLEET_TWO_FACTOR_REQUIRED_FROM=yesterday):
            roles.require(principal, Perm.PURCHASE)


class AdminScopeTests(FleetTestCase):
    """§1: administrationsvyn ger inte obegränsad tillgång till förarflödena."""

    def test_member_access_is_limited_to_the_purchased_counties(self):
        data = self.full_setup(county="12")
        company = data["company"]
        entitled = access.company_counties(company.id)
        self.assertEqual(entitled, ("12",))

        licensing.activate_extra_county(license=data["license"], county_code="01")
        self.assertEqual(access.company_counties(company.id), ("01", "12"))

    def test_a_cancelled_licence_stops_contributing_counties(self):
        data = self.full_setup(county="12")
        License.objects.filter(id=data["license"].id).update(status=License.Status.CANCELED)
        self.assertEqual(access.company_counties(data["company"].id), ())


class PairingDefaultsTests(FleetTestCase):
    """En nyparkopplad telefon ska kunna få notiser utan att någon öppnar inställningarna."""

    def test_a_paired_phone_inherits_the_licence_counties(self):
        data = self.full_setup(county="14")
        licensing.activate_extra_county(license=data["license"], county_code="12")
        issued = pairing.issue_code(
            license=data["license"], vehicle=data["vehicle"], created_by=None
        )
        result = pairing.redeem_code(
            code=issued.code, installation_id="installation-abcdef123456", label="Testbil"
        )

        from billing.models import Device

        device = Device.objects.get(id=result.device_id)
        self.assertEqual(sorted(device.notify_prefs.get("counties", [])), ["12", "14"])

    def test_an_existing_choice_is_not_overwritten(self):
        data = self.full_setup(county="14")
        device = self.make_device(data["company"])
        Device = type(device)
        Device.objects.filter(id=device.id).update(notify_prefs={"counties": ["01"]})
        issued = pairing.issue_code(
            license=data["license"], vehicle=data["vehicle"], created_by=None
        )
        pairing.redeem_code(code=issued.code, installation_id=device.token)

        device.refresh_from_db()
        self.assertEqual(device.notify_prefs["counties"], ["01"])
