"""
Provet: kontrollerna vid registreringen (fleet/signup_checks.py), att provet
bara visar tåg och buss (fleet/features.py), och säljarens uppföljning
(fleet/admin_followup.py).
"""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta
from unittest import mock

from django.core.cache import cache
from django.test import Client, override_settings
from django.utils import timezone

from core.models import Opportunity, SeverityTier
from fleet import commerce, features, registration, sales, sessions, signup_checks, trials
from fleet.models import (
    CompanyProfile, License, SalesFollowUp, StaffRole, Trial,
)
from fleet.push_gate import can_receive
from fleet.tests.base import FleetTestCase
from fleet.tests.test_access import MALMO, tip
from fleet.tests.test_bolagsverket import CONFIGURED, NOT_FOUND, VOLVO, registry

PHONE = "070-812 34 91"
SOLE_TRADER = "811218-9876"  # personnummer, Luhn-giltigt, född 1981


class PhoneTests(FleetTestCase):
    def test_the_forms_people_write_are_one_number(self):
        for raw in ("0708123491", "070-812 34 91", "+46 70 812 34 91", "0046708123491",
                    "46708123491", "+46 (0)70 812 34 91"):
            with self.subTest(raw=raw):
                self.assertEqual(signup_checks.check_phone(raw), "+46708123491")

    def test_only_swedish_mobile_numbers(self):
        for raw in ("040-12 34 56", "0711234567", "+4712345678", "12345", "0708"):
            with self.subTest(raw=raw), self.assertRaises(signup_checks.CheckError) as caught:
                signup_checks.check_phone(raw)
            self.assertEqual(caught.exception.reason, "invalid_phone")

    def test_numbers_typed_to_get_past_the_form(self):
        for raw in ("0700000000", "0701111111", "0701234567", "0707654321", "0701010101"):
            with self.subTest(raw=raw), self.assertRaises(signup_checks.CheckError):
                signup_checks.check_phone(raw)

    def test_a_phone_is_required(self):
        with self.assertRaises(signup_checks.CheckError) as caught:
            signup_checks.check_phone("  ")
        self.assertEqual(caught.exception.reason, "phone_required")


class IdentityTests(FleetTestCase):
    today = date(2026, 9, 29)

    def check(self, number):
        return signup_checks.check_identity(number.replace("-", ""), today=self.today)

    def test_an_org_number_can_never_be_a_personal_number(self):
        self.assertEqual(signup_checks.org_kind("5560125790"), "organisation")
        self.assertEqual(signup_checks.org_kind("8112189876"), "person")

    def test_a_sole_traders_personal_number_must_be_a_real_adult(self):
        self.assertEqual(self.check(SOLE_TRADER), "person")
        with self.assertRaises(signup_checks.CheckError) as caught:
            self.check("811232-9878")  # 32 december
        self.assertEqual(caught.exception.reason, "invalid_personal_number")
        with self.assertRaises(signup_checks.CheckError) as caught:
            self.check("150101-1231")  # elva år
        self.assertEqual(caught.exception.reason, "personal_number_minor")

    def test_groups_that_do_not_run_taxis(self):
        with self.assertRaises(signup_checks.CheckError) as caught:
            self.check("802000-0009")  # ideell förening
        self.assertEqual(caught.exception.reason, "org_group_not_allowed")

    def test_disposable_and_unconfirmed_email(self):
        with self.assertRaises(signup_checks.CheckError):
            signup_checks.check_email("a@mailinator.com")
        with self.assertRaises(signup_checks.CheckError) as caught:
            signup_checks.check_email("a@taxi.se", {"user_metadata": {"email_verified": False}})
        self.assertEqual(caught.exception.reason, "email_unverified")
        signup_checks.check_email("a@taxi.se", {"user_metadata": {"email_verified": True}})


@CONFIGURED
class RegistrationRulesTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def register(self, **overrides):
        args = {
            "user_id": str(uuid.uuid4()), "email": f"{uuid.uuid4().hex[:6]}@taxi.test",
            "org_number": "556012-5790", "contact_name": "Anna", "contact_phone": PHONE,
        }
        args.update(overrides)
        return registration.register(**args)

    def test_a_company_bolagsverket_does_not_know_is_refused(self):
        with registry(NOT_FOUND), self.assertRaises(sales.SalesError) as caught:
            self.register(company_name="Påhittat AB")
        self.assertEqual(caught.exception.reason, "org_not_in_registry")

    def test_a_sole_trader_writes_the_name_and_is_flagged(self):
        with registry(NOT_FOUND):
            result = self.register(org_number=SOLE_TRADER, company_name="Annas Taxi")
        profile = CompanyProfile.objects.get(company_id=result.company.id)
        self.assertEqual(profile.contact_phone, "+46708123491")
        self.assertIsNotNone(profile.email_verified_at)
        codes = [f["code"] for f in signup_checks.flags(profile)]
        self.assertIn("sole_trader", codes)

    def test_a_non_taxi_company_is_flagged_for_the_seller(self):
        with registry(VOLVO):
            result = self.register()
        profile = CompanyProfile.objects.get(company_id=result.company.id)
        self.assertIn("not_taxi_industry", [f["code"] for f in signup_checks.flags(profile)])

    def test_one_phone_number_one_trial(self):
        with registry(VOLVO):
            self.register()
        with registry(NOT_FOUND), self.assertRaises(sales.SalesError) as caught:
            self.register(org_number=SOLE_TRADER, company_name="Annas Taxi", contact_phone="0708123491")
        self.assertEqual(caught.exception.reason, "phone_in_use")

    def test_a_self_registered_trial_has_one_car_and_one_county(self):
        with registry(VOLVO):
            result = self.register(vehicles=[{"plate": "ABC123", "baseCounty": "12"}])
        self.assertEqual(result.trial.vehicle_limit, 1)
        with self.assertRaises(sales.SalesError) as caught:
            sales._add_trial_vehicles(
                result.trial, sales._vehicle_specs([{"plate": "DEF456", "baseCounty": "12"}]),
                actor_user_id=None, now=timezone.now(),
            )
        self.assertEqual(caught.exception.reason, "trial_vehicle_limit")

    def test_extra_counties_are_not_part_of_a_self_registered_trial(self):
        with registry(VOLVO), self.assertRaises(sales.SalesError) as caught:
            self.register(vehicles=[{"plate": "ABC123", "baseCounty": "12", "extraCounties": ["01"]}])
        self.assertEqual(caught.exception.reason, "trial_extra_county")

    def test_a_seller_can_still_give_three_cars(self):
        self.assertEqual(trials.vehicle_limit_for(Trial.Source.SALES), 3)

    def test_the_precheck_answers_before_an_account_exists(self):
        client = Client()
        with registry(NOT_FOUND):
            body = client.post(
                "/api/fleet/register/check",
                json.dumps({"orgNumber": "556012-5790", "contactPhone": PHONE}),
                content_type="application/json",
            ).json()
        self.assertEqual((body["ok"], body["field"]), (False, "orgNumber"))
        body = client.post(
            "/api/fleet/register/check",
            json.dumps({"orgNumber": SOLE_TRADER, "contactPhone": "0700000000"}),
            content_type="application/json",
        ).json()
        self.assertEqual(body["field"], "phone")


class TrialScopeTests(FleetTestCase):
    """Ett prov visar tåg och buss. Resten syns som låst, och lämnas aldrig ut."""

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.company = self.make_company(name="Prov AB", org_number="5566778899", status="inactive")
        self.trial = trials.create_trial(
            company_id=self.company.id, country="SE", org_number="5566778899",
            source=Trial.Source.SELF_SIGNUP, requires_payment_method=False,
        )
        now = timezone.now()
        Trial.objects.filter(id=self.trial.id).update(
            status=Trial.Status.ACTIVE, started_at=now - timedelta(days=2),
            ends_at=now + timedelta(days=12),
        )
        from fleet import orders

        orders.get_or_create_subscription(self.company.id)
        self.vehicle, self.license = self.make_license(self.company, plate="PRV123", county="12")
        License.objects.filter(id=self.license.id).update(status=License.Status.TRIAL, trial=self.trial)
        self.device = self.make_device(self.company, push_token="fcm-token")
        _approval, self.secret = self.approve(self.company, self.license, self.vehicle, self.device)
        sessions.start_session(device_id=self.device.id, license_id=self.license.id)
        self.train = tip(title="Inställt tåg")
        self.flight = tip(kind="flight", mode="flight", title="Tre plan landar")
        self.ferry = tip(kind="ferry", mode="ferry", title="Färjan lägger till")

    def get(self, path, **params):
        return self.client.get(path, params, headers={"x-device-token": self.secret})

    def test_the_feed_shows_train_and_bus_and_counts_the_rest(self):
        body = self.get("/api/alerts", **MALMO).json()
        self.assertEqual([a["title"] for a in body["alerts"]], ["Inställt tåg"])
        self.assertEqual(body["features"]["plan"], "trial")
        self.assertEqual(body["features"]["hiddenCounts"], {"flight": 1, "ferry": 1})
        self.assertIn("events", body["features"]["locked"])

    def test_a_direct_link_to_a_locked_tip_is_refused(self):
        response = self.get(f"/api/opportunities/{self.flight.id}")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], features.LOCKED_REASON)
        self.assertEqual(self.get(f"/api/opportunities/{self.train.id}").status_code, 200)

    def test_ferries_and_events_are_locked(self):
        self.assertEqual(self.get("/api/ferries", **MALMO).json()["reason"], features.LOCKED_REASON)
        self.assertEqual(self.get("/api/events", **MALMO).json()["reason"], features.LOCKED_REASON)

    def test_no_notification_about_a_locked_tip(self):
        from core import notify

        verdict = can_receive(self.device, notify.snapshot_of(self.flight))
        self.assertEqual(verdict.reason, "trial_category_locked:flight")
        self.assertTrue(can_receive(self.device, notify.snapshot_of(self.train)).ok)

    def test_a_customer_who_committed_during_the_trial_sees_everything(self):
        with mock.patch.object(commerce, "has_active_trial_commit", return_value=True):
            body = self.get("/api/alerts", **MALMO).json()
        self.assertEqual(len(body["alerts"]), 3)
        self.assertEqual(body["features"]["plan"], "full")

    def test_a_paying_customer_sees_everything(self):
        Trial.objects.filter(id=self.trial.id).update(status=Trial.Status.CONVERTED)
        License.objects.filter(id=self.license.id).update(status=License.Status.ACTIVE)
        self.make_subscription(self.company)
        body = self.get("/api/alerts", **MALMO).json()
        self.assertEqual(len(body["alerts"]), 3)

    def test_a_coupon_opens_everything(self):
        Trial.objects.filter(id=self.trial.id).update(source=Trial.Source.COUPON)
        self.assertTrue(features.for_company(self.company.id).full)

    def test_the_trial_and_the_paid_feed_never_share_an_etag(self):
        trial_etag = self.get("/api/alerts", **MALMO)["ETag"]
        with mock.patch.object(commerce, "has_active_trial_commit", return_value=True):
            full = self.client.get(
                "/api/alerts", MALMO, headers={"x-device-token": self.secret, "if-none-match": trial_etag},
            )
        self.assertEqual(full.status_code, 200)


class FollowUpTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.staff_user = uuid.uuid4()
        StaffRole.objects.create(user_id=self.staff_user, role=StaffRole.Role.SALES)
        self.company = self.make_company(name="Ring Mig AB", org_number="5566778899", status="inactive")
        CompanyProfile.objects.filter(company_id=self.company.id).update(
            contact_name="Anna", contact_phone="+46708123491", contact_email="anna@taxi.test",
        )
        trial = trials.create_trial(
            company_id=self.company.id, country="SE", org_number="5566778899",
            source=Trial.Source.SELF_SIGNUP, requires_payment_method=False,
        )
        now = timezone.now()
        Trial.objects.filter(id=trial.id).update(
            status=Trial.Status.ACTIVE, started_at=now - timedelta(days=12),
            ends_at=now + timedelta(days=2),
        )

    def as_staff(self):
        # Behörigheten prövas i test_admin.py; här gäller listan och anteckningen.
        return mock.patch("fleet.admin_followup._staff", return_value=mock.Mock(user_id=self.staff_user))

    def test_the_seller_sees_whom_to_call_and_writes_the_outcome(self):
        with self.as_staff():
            body = self.client.get("/api/admin/followups").json()
        row = body["followUps"][0]
        self.assertEqual((row["name"], row["phone"], row["stage"]), ("Ring Mig AB", "+46708123491", "ending"))
        self.assertEqual(row["followUp"]["outcome"], "not_contacted")

        with self.as_staff():
            response = self.client.post(
                f"/api/admin/followups/{self.company.id}",
                json.dumps({"outcome": "call_back", "note": "Ring efter lunch",
                            "nextContactAt": "2026-10-02", "contacted": True}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200, response.content)
        follow = SalesFollowUp.objects.get(company_id=self.company.id)
        self.assertEqual((follow.outcome, follow.contact_attempts), ("call_back", 1))
        from zoneinfo import ZoneInfo

        local = follow.next_contact_at.astimezone(ZoneInfo("Europe/Stockholm"))
        self.assertEqual((local.date().isoformat(), local.hour), ("2026-10-02", 9))

    def test_a_trial_that_was_bought_after_it_ended_leaves_the_list(self):
        Trial.objects.filter(company_id=self.company.id).update(
            status=Trial.Status.ENDED, ends_at=timezone.now() - timedelta(days=1),
        )
        self.make_subscription(self.company)
        with self.as_staff():
            body = self.client.get("/api/admin/followups").json()
        self.assertEqual(body["followUps"], [])
