"""
Länbyten: högst två per bil och kalendermånad, även under provet. Personal kan
ge ett extra byte. Att köpa ett extra län är inget byte.

Och massinbjudan av förare: varje rad för sig, en trasig rad stoppar inte de
andra, och 50 rader slår inte i timgränsen för enskilda inbjudningar.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import Client, override_settings
from django.utils import timezone

from fleet import county_changes
from fleet.models import (
    AuditEvent,
    CountyChange,
    DriverInvite,
    License,
    LicenseCounty,
    Order,
    StaffRole,
    Subscription,
)
from fleet.tests.base import FleetTestCase
from fleet.tests.test_support import SECRET, jwt

STOCKHOLM = ZoneInfo("Europe/Stockholm")


class _ApiCase(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()

    def post(self, path, body=None, user=None):
        return self.client.post(
            path, data=json.dumps(body or {}), content_type="application/json",
            headers={"authorization": f"Bearer {jwt(user or self.owner)}"},
        )

    def get(self, path, user=None):
        return self.client.get(path, headers={"authorization": f"Bearer {jwt(user or self.owner)}"})

    def trial_county(self, license, base, **extra):
        return self.post(f"/api/fleet/trial/vehicles/{license.id}/county", {"base": base, **extra})

    def active(self, license):
        rows = LicenseCounty.objects.filter(license=license, active_to__isnull=True)
        return sorted((r.kind, r.county_code) for r in rows)


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class TrialCountyChangeTests(_ApiCase):
    def setUp(self):
        super().setUp()
        self.data = self.full_setup(county="01", plate="PROV01")
        License.objects.filter(id=self.data["license"].id).update(status=License.Status.TRIAL)
        self.license = License.objects.get(id=self.data["license"].id)
        self.owner = str(self.data["owner"].user_id)

    def test_two_changes_then_the_limit_with_a_swedish_explanation(self):
        first = self.trial_county(self.license, "12")
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(first.json()["countyChanges"]["remaining"], 1)
        self.assertEqual(self.trial_county(self.license, "14").status_code, 200)

        refused = self.trial_county(self.license, "03")
        self.assertEqual(refused.status_code, 403)
        body = refused.json()
        self.assertEqual(body["reason"], "county_change_limit")
        self.assertIn("två gånger den här månaden", body["message"])
        self.assertIn("support", body["message"])
        self.assertEqual(body["detail"]["countyChanges"]["remaining"], 0)
        self.license.refresh_from_db()
        self.assertEqual(self.license.base_county, "14")

    def test_the_same_county_again_is_not_a_change(self):
        self.assertEqual(self.trial_county(self.license, "01").status_code, 200)
        self.assertEqual(county_changes.summary_for(self.license.id)["used"], 0)

    def test_extras_are_kept_swapped_but_never_widened(self):
        # En säljare har gett provbilen ett extra län.
        LicenseCounty.objects.create(
            license=self.license, county_code="12", kind=LicenseCounty.Kind.EXTRA,
            active_from=self.license.created_at,
        )
        # Byter bara baslän: extra länet ligger kvar.
        self.assertEqual(self.trial_county(self.license, "14").status_code, 200)
        self.assertEqual(self.active(self.license), [("base", "14"), ("extra", "12")])

        # Fler extra län än bilen har går inte, oavsett gränsen.
        wider = self.trial_county(self.license, "14", extras=["12", "03"])
        self.assertEqual(wider.json()["reason"], "trial_extra_county")

        # Att ta bort ett extra län smalnar av och räknas inte.
        self.assertEqual(self.trial_county(self.license, "14", extras=[]).status_code, 200)
        self.assertEqual(county_changes.summary_for(self.license.id)["used"], 1)

    def test_swapping_an_extra_county_counts(self):
        LicenseCounty.objects.create(
            license=self.license, county_code="12", kind=LicenseCounty.Kind.EXTRA,
            active_from=self.license.created_at,
        )
        response = self.trial_county(self.license, "01", extras=["03"])
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["counted"])
        self.assertEqual(self.active(self.license), [("base", "01"), ("extra", "03")])

    def test_staff_are_not_limited_and_do_not_use_the_customers_changes(self):
        admin = str(uuid.uuid4())
        StaffRole.objects.create(user_id=admin, role=StaffRole.Role.PLATFORM_ADMIN)
        for county in ("12", "14", "03"):
            response = self.post(
                f"/api/admin/licenses/{self.license.id}/counties", {"base": county}, user=admin,
            )
            self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(county_changes.summary_for(self.license.id)["used"], 0)
        self.assertEqual(AuditEvent.objects.filter(action="admin_trial_counties_set").count(), 3)

    def test_the_month_turns_in_stockholm_not_in_utc(self):
        late = datetime(2026, 10, 31, 23, 30, tzinfo=STOCKHOLM)
        county_changes.change_trial_counties(self.license, base="12", now=late)
        county_changes.change_trial_counties(self.license, base="14", now=late)
        with self.assertRaises(county_changes.CountyChangeError):
            county_changes.change_trial_counties(self.license, base="03", now=late)

        # 00:10 i Stockholm är fortfarande oktober i UTC -- men en ny månad här.
        early = datetime(2026, 11, 1, 0, 10, tzinfo=STOCKHOLM)
        summary = county_changes.summary_for(self.license.id, now=early)
        self.assertEqual((summary["month"], summary["used"], summary["remaining"]), ("2026-11", 0, 2))
        county_changes.change_trial_counties(self.license, base="03", now=early)
        self.license.refresh_from_db()
        self.assertEqual(self.license.base_county, "03")

    def test_the_company_overview_shows_changes_left_per_car(self):
        self.trial_county(self.license, "12")
        row = self.get("/api/fleet/company").json()["licenses"][0]
        self.assertEqual(
            {k: row["countyChanges"][k] for k in ("used", "limit", "extra", "remaining")},
            {"used": 1, "limit": 2, "extra": 0, "remaining": 1},
        )
        self.assertRegex(row["countyChanges"]["month"], r"^\d{4}-\d{2}$")


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class PaidCountyChangeTests(_ApiCase):
    def setUp(self):
        super().setUp()
        self.data = self.full_setup(county="12", plate="BET001")
        self.license = self.data["license"]
        self.owner = str(self.data["owner"].user_id)

    def order(self, change):
        return self.post("/api/fleet/orders", {**change, "accepted": True})

    def base_change(self, county):
        return {"baseCountyChanges": [{"licenseId": str(self.license.id), "county": county}]}

    def test_a_scheduled_base_change_counts_when_ordered(self):
        first = self.order(self.base_change("01"))
        self.assertEqual(first.status_code, 200, first.content)
        self.assertEqual(first.json()["status"], Order.Status.SCHEDULED)
        self.assertEqual(self.order(self.base_change("14")).status_code, 200)

        quote = self.post("/api/fleet/quote", self.base_change("03"))
        self.assertEqual(quote.json()["reason"], "county_change_limit")
        refused = self.order(self.base_change("03"))
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(refused.json()["reason"], "county_change_limit")
        self.assertIn("BET001", refused.json()["message"])
        self.license.refresh_from_db()
        self.assertEqual(self.license.scheduled_base_county, "14")

    def test_ordering_the_already_scheduled_county_again_is_not_a_new_change(self):
        self.order(self.base_change("01"))
        self.order(self.base_change("01"))
        self.assertEqual(county_changes.summary_for(self.license.id)["used"], 1)

    def test_buying_an_extra_county_is_not_a_change(self):
        quote = self.post("/api/fleet/quote", {
            "addCounties": [{"licenseId": str(self.license.id), "county": "01"}],
        })
        self.assertEqual(quote.status_code, 200, quote.content)
        # Även efter två byten går det att köpa ett län.
        self.order(self.base_change("01"))
        self.order(self.base_change("14"))
        quote = self.post("/api/fleet/quote", {
            "addCounties": [{"licenseId": str(self.license.id), "county": "03"}],
        })
        self.assertEqual(quote.status_code, 200, quote.content)
        self.assertEqual(CountyChange.objects.count(), 2)

    def test_a_failed_order_gives_the_change_back(self):
        self.order(self.base_change("01"))
        self.order(self.base_change("14"))
        Order.objects.filter(kind=Order.Kind.CHANGE_BASE_COUNTY).update(status=Order.Status.FAILED)
        self.assertEqual(county_changes.summary_for(self.license.id)["remaining"], 2)

    def test_a_new_attempt_on_the_same_unpaid_change_does_not_count_again(self):
        """
        Ett omedelbart baslänsbyte kostar pengar och blir en obetald order.
        Kunden avbryter i Stripe och försöker igen: samma order ska komma
        tillbaka (fleet/orders.py:find_reusable_order) och bytet ska fortfarande
        räknas EN gång -- även när bilen redan gjort sina två byten den här
        månaden. Utan återanvändningen i grinden hade återförsöket fått
        `county_change_limit` för ett byte som redan räknats på den ordern.
        """
        # Utan löpande period proportioneras inget: beloppet blir detsamma vid
        # varje försök, vilket är vad återanvändningen kräver.
        Subscription.objects.filter(company_id=self.data["company"].id).update(
            current_period_start=None, current_period_end=None
        )

        def immediate(county):
            return {
                "baseCountyChanges": [
                    {"licenseId": str(self.license.id), "county": county, "immediate": True}
                ]
            }

        with mock.patch("fleet.commerce.stripe_sync.available", return_value=True):
            first = self.order(immediate("01"))
            self.assertEqual(first.status_code, 200, first.content)
            self.assertEqual(first.json()["status"], Order.Status.PENDING_PAYMENT)
            self.assertEqual(self.order(immediate("14")).status_code, 200)
            self.assertEqual(county_changes.summary_for(self.license.id)["remaining"], 0)

            later = timezone.now() + timedelta(minutes=5)
            with mock.patch("fleet.orders.timezone.now", return_value=later):
                retry = self.order(immediate("01"))

        self.assertEqual(retry.status_code, 200, retry.content)
        self.assertEqual(retry.json()["orderId"], first.json()["orderId"])
        self.assertEqual(county_changes.summary_for(self.license.id)["used"], 2)
        self.assertEqual(CountyChange.objects.filter(order_id=first.json()["orderId"]).count(), 1)


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class AdminExtraCountyChangeTests(_ApiCase):
    def setUp(self):
        super().setUp()
        self.data = self.full_setup(county="01", plate="PROV02")
        License.objects.filter(id=self.data["license"].id).update(status=License.Status.TRIAL)
        self.license = License.objects.get(id=self.data["license"].id)
        self.owner = str(self.data["owner"].user_id)
        self.admin = str(uuid.uuid4())
        StaffRole.objects.create(user_id=self.admin, role=StaffRole.Role.SALES)

    def test_staff_allow_one_more_change_this_month(self):
        self.trial_county(self.license, "12")
        self.trial_county(self.license, "14")
        self.assertEqual(self.trial_county(self.license, "03").status_code, 403)

        granted = self.post(
            f"/api/admin/licenses/{self.license.id}/allow-county-change",
            {"note": "Flyttar verksamheten"}, user=self.admin,
        )
        self.assertEqual(granted.status_code, 200, granted.content)
        self.assertEqual(granted.json()["countyChanges"]["extra"], 1)
        self.assertEqual(granted.json()["countyChanges"]["remaining"], 1)
        event = AuditEvent.objects.get(action="admin_county_change_grant")
        self.assertEqual(event.actor_kind, "platform_admin")
        self.assertEqual(event.detail["note"], "Flyttar verksamheten")

        self.assertEqual(self.trial_county(self.license, "03").status_code, 200)
        self.assertEqual(self.trial_county(self.license, "04").json()["reason"], "county_change_limit")

        detail = self.get(f"/api/admin/companies/{self.data['company'].id}", user=self.admin).json()
        self.assertEqual(detail["licenses"][0]["countyChanges"]["used"], 3)
        self.assertEqual(detail["licenses"][0]["countyChanges"]["remaining"], 0)

    def test_support_role_and_customers_cannot_grant(self):
        support = str(uuid.uuid4())
        StaffRole.objects.create(user_id=support, role=StaffRole.Role.SUPPORT)
        path = f"/api/admin/licenses/{self.license.id}/allow-county-change"
        self.assertEqual(self.post(path, {}, user=support).status_code, 403)
        self.assertEqual(self.post(path, {}).status_code, 403)
        self.assertEqual(county_changes.summary_for(self.license.id)["extra"], 0)


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class BulkDriverInviteTests(_ApiCase):
    def setUp(self):
        super().setUp()
        self.company = self.make_company()
        self.owner = str(self.make_owner(self.company).user_id)
        self.make_subscription(self.company)
        _v1, self.first = self.make_license(self.company, plate="AAA111", county="01")

    def bulk(self, rows, user=None):
        return self.post("/api/fleet/driver-invites/bulk", {"rows": rows}, user=user)

    def test_one_car_company_needs_no_plate_and_50_rows_all_go_out(self):
        rows = [{"email": f"forare{i}@exempel.test", "label": f"Förare {i}"} for i in range(50)]
        response = self.bulk(rows)
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual((body["sent"], body["failed"]), (50, 0), body["results"][-1])
        self.assertEqual(DriverInvite.objects.filter(license=self.first).count(), 50)

    def test_mixed_rows_each_get_their_own_answer(self):
        _v2, second = self.make_license(self.company, plate="BBB222", county="12")
        response = self.bulk([
            {"email": "anna@exempel.test", "plate": "aaa 111", "label": "Anna"},
            {"email": "bo@exempel.test", "licenseId": str(second.id)},
            {"email": "inte-en-adress", "plate": "AAA111"},
            {"email": "cia@exempel.test", "plate": "ZZZ999"},
            {"email": "dan@exempel.test"},
            {"email": "Anna@Exempel.test", "plate": "BBB222"},
            {"email": "eva@exempel.test", "licenseId": "trasigt"},
        ])
        self.assertEqual(response.status_code, 200, response.content)
        results = response.json()["results"]
        self.assertEqual(
            [(r["email"], r["ok"], r.get("reason")) for r in results],
            [
                ("anna@exempel.test", True, None),
                ("bo@exempel.test", True, None),
                ("inte-en-adress", False, "invalid_email"),
                ("cia@exempel.test", False, "unknown_vehicle"),
                ("dan@exempel.test", False, "plate_required"),
                ("Anna@Exempel.test", False, "duplicate_email"),
                ("eva@exempel.test", False, "unknown_license"),
            ],
        )
        self.assertTrue(all(r["message"] for r in results if not r["ok"]))
        self.assertEqual(results[0]["plate"], "AAA111")
        self.assertEqual(DriverInvite.objects.get(email="bo@exempel.test").license_id, second.id)
        self.assertEqual(DriverInvite.objects.count(), 2)

    def test_another_companys_car_is_not_found(self):
        other = self.make_company(name="Annat AB", org_number="5560000001")
        _v, other_license = self.make_license(other, plate="OTH001")
        results = self.bulk([
            {"email": "x@exempel.test", "licenseId": str(other_license.id)},
            {"email": "y@exempel.test", "plate": "OTH001"},
        ]).json()["results"]
        self.assertEqual([r["reason"] for r in results], ["unknown_license", "unknown_vehicle"])
        self.assertFalse(DriverInvite.objects.exists())

    def test_at_most_200_rows_and_at_least_one(self):
        rows = [{"email": f"f{i}@exempel.test"} for i in range(201)]
        self.assertEqual(self.bulk(rows).json()["reason"], "too_many_rows")
        self.assertEqual(self.bulk([]).json()["reason"], "rows_required")
        self.assertFalse(DriverInvite.objects.exists())

    def test_a_driver_without_rights_cannot_bulk_invite(self):
        driver = str(self.make_owner(self.company, role="driver").user_id)
        self.assertEqual(self.bulk([{"email": "a@exempel.test"}], user=driver).status_code, 403)
