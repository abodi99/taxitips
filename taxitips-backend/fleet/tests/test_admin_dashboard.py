"""
Adminwebbens dashboard (fleet/admin_dashboard.py).

Först vem som kommer in -- dashboarden visar MRR och kunder över ALLA bolag,
så en kund får aldrig se den. Sedan att tratten och veckotrenden räknar rätt
på ett dataset litet nog att räkna för hand, och att risklägena och
supportsiffrorna är samma som i vyerna man klickar sig vidare till.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.test import Client, override_settings
from django.utils import timezone

from fleet import device_swaps
from fleet.models import (
    DeviceLinkEvent,
    DeviceSwapGrant,
    Order,
    StaffRole,
    Subscription,
    SubscriptionStatus,
    SupportThread,
    Trial,
)
from fleet.tests.base import FleetTestCase, price_version
from fleet.tests.test_admin import SECRET, jwt

SECTIONS = ("ledning", "salj", "support", "uppfoljning", "drift", "anvandning")


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class DashboardTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.admin_id = str(uuid.uuid4())
        StaffRole.objects.create(user_id=self.admin_id, role=StaffRole.Role.SUPPORT)

    def get(self, user_id):
        return self.client.get(
            "/api/admin/dashboard", headers={"authorization": f"Bearer {jwt(user_id)}"},
        )

    def body(self):
        response = self.get(self.admin_id)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    # --- helpers ----------------------------------------------------------

    def trial(self, company, *, started=True, days_left=5):
        now = timezone.now()
        return Trial.objects.create(
            company_id=company.id, org_key=f"SE{company.org_number}",
            source=Trial.Source.SELF_SIGNUP,
            status=Trial.Status.ACTIVE if started else Trial.Status.PENDING,
            started_at=now - timedelta(days=2) if started else None,
            ends_at=now + timedelta(days=days_left) if started else None,
        )

    def paid_order(self, company, *, monthly=79900, paid_at=None):
        return Order.objects.create(
            company_id=company.id, kind=Order.Kind.INITIAL, status=Order.Status.PAID,
            price_version=price_version(), quantity_before=0, quantity_after=1,
            amount_now_ore=monthly, vat_now_ore=monthly // 4, total_now_ore=monthly + monthly // 4,
            next_period_amount_ore=monthly, paid_at=paid_at or timezone.now(),
        )

    # --- behörighet -------------------------------------------------------

    def test_without_login_nothing_is_returned(self):
        self.assertEqual(self.client.get("/api/admin/dashboard").status_code, 401)

    def test_a_customer_never_sees_the_dashboard(self):
        """En bolagsägare, hur hög roll hen än har, är inte plattformens personal."""
        owner = self.full_setup()["owner"]
        response = self.get(str(owner.user_id))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["reason"], "not_staff")
        self.assertNotIn("ledning", response.json())

    # --- fälten -----------------------------------------------------------

    def test_every_section_and_its_headline_fields(self):
        data = self.full_setup()
        body = self.body()
        for section in SECTIONS:
            self.assertIn(section, body)
            self.assertNotIn("unavailable", body[section], section)

        ledning = body["ledning"]
        for key in ("mrrOre", "payingCompanies", "carsPaid", "carsTrial", "activeDrivers",
                    "driversOnDuty", "phonesApproved", "weeks"):
            self.assertIn(key, ledning)
        self.assertEqual(len(ledning["weeks"]), 12)
        self.assertEqual(
            set(ledning["weeks"][0]), {"weekStart", "newCompanies", "newPaying", "mrrOre"},
        )
        # Samma prismotor som Hem: en licens på grundpriset.
        self.assertEqual(ledning["mrrOre"], 79900)
        self.assertEqual(ledning["payingCompanies"], 1)
        self.assertEqual(ledning["carsPaid"], 1)

        self.assertEqual(
            set(body["salj"]), {"funnel", "trialsEnding", "missingSetup", "crmOverdue"},
        )
        for key in ("threadsOpen", "threadsWaiting", "waitBuckets", "tipReportsOpen",
                    "errors", "swapLimit"):
            self.assertIn(key, body["support"])
        for key in ("pastDue", "pendingCancel", "churned", "inactiveTrials", "atRisk"):
            self.assertIn(key, body["uppfoljning"])
        for key in ("sources", "outbox", "push"):
            self.assertIn(key, body["drift"])
        self.assertEqual(len(body["drift"]["push"]["perDay"]), 7)
        self.assertEqual(len(body["anvandning"]["tipsPerDay"]), 7)
        self.assertIn("d30", body["anvandning"]["feedback"])

        # Inga hemligheter: varken telefonens hemlighet eller dess installations-id.
        raw = self.get(self.admin_id).content.decode()
        self.assertNotIn(data["secret"], raw)
        self.assertNotIn(data["device"].token, raw)

    # --- tratten ----------------------------------------------------------

    def test_funnel_counts_a_small_cohort(self):
        """
        A registrerad, B prov, C prov + betalt, D betalt utan prov, E för gammal.
        Varje steg är en delmängd av det förra: D har passerat provsteget.
        """
        a = self.make_company(name="A Taxi", org_number="5560000001")
        b = self.make_company(name="B Taxi", org_number="5560000002")
        self.trial(b)
        c = self.make_company(name="C Taxi", org_number="5560000003")
        self.trial(c)
        self.paid_order(c)
        d = self.make_company(name="D Taxi", org_number="5560000004")
        self.make_subscription(d)  # had_successful_payment=True, ingen beställning
        e = self.make_company(name="E Taxi", org_number="5560000005")
        self.trial(e)
        type(e).objects.filter(id=e.id).update(created_at=timezone.now() - timedelta(days=120))
        self.assertTrue(a.id)

        funnel = self.body()["salj"]["funnel"]
        self.assertEqual(funnel["registered"], 4)
        self.assertEqual(funnel["trialStarted"], 3)
        self.assertEqual(funnel["paying"], 2)
        self.assertEqual(funnel["boughtWithoutTrial"], 1)
        self.assertEqual(funnel["rates"], {
            "trialOfRegistered": 75.0, "payingOfTrial": 66.7, "payingOfRegistered": 50.0,
        })

    def test_weekly_trend_counts_new_companies_paying_and_mrr(self):
        c = self.make_company(name="C Taxi", org_number="5560000003")
        self.paid_order(c, monthly=79900)
        old = self.make_company(name="Gammal Taxi", org_number="5560000006")
        self.paid_order(old, monthly=149800, paid_at=timezone.now() - timedelta(weeks=5))
        type(old).objects.filter(id=old.id).update(created_at=timezone.now() - timedelta(weeks=5))

        weeks = self.body()["ledning"]["weeks"]
        self.assertEqual(weeks[-1]["newCompanies"], 1)
        self.assertEqual(weeks[-1]["newPaying"], 1)
        self.assertEqual(sum(w["newPaying"] for w in weeks), 2)
        # Månadsbeloppet ur den senaste betalda beställningen, per bolag.
        self.assertEqual(weeks[-1]["mrrOre"], 79900 + 149800)
        self.assertEqual(weeks[0]["mrrOre"], 0)

    def test_a_canceled_subscription_leaves_the_mrr_line(self):
        c = self.make_company(name="Slutat Taxi", org_number="5560000007")
        self.paid_order(c, paid_at=timezone.now() - timedelta(weeks=6))
        sub = self.make_subscription(c)
        Subscription.objects.filter(id=sub.id).update(
            status=SubscriptionStatus.CANCELED, access_until=timezone.now() - timedelta(weeks=2),
        )
        weeks = self.body()["ledning"]["weeks"]
        self.assertEqual(weeks[-1]["mrrOre"], 0)
        self.assertEqual(weeks[-5]["mrrOre"], 79900)

    # --- sälj, uppföljning, support ---------------------------------------

    def test_trials_ending_and_missing_setup(self):
        soon = self.make_company(name="Snart Slut", org_number="5560000008")
        self.trial(soon, days_left=3)
        later = self.make_company(name="Långt Kvar", org_number="5560000009")
        self.trial(later, days_left=20)
        salj = self.body()["salj"]
        self.assertEqual(salj["trialsEnding"]["count"], 1)
        self.assertEqual(salj["trialsEnding"]["rows"][0]["name"], "Snart Slut")
        # Ingen av dem har en bil.
        self.assertEqual(salj["missingSetup"]["noCar"], 2)

    def test_risk_comes_from_the_follow_up_list(self):
        data = self.full_setup()
        Subscription.objects.filter(id=data["subscription"].id).update(
            status=SubscriptionStatus.PAST_DUE,
        )
        upp = self.body()["uppfoljning"]
        self.assertEqual(upp["pastDue"], 1)
        self.assertEqual(upp["atRisk"][0]["companyId"], str(data["company"].id))
        self.assertEqual(upp["atRisk"][0]["segment"], "past_due")

    def test_waiting_support_and_swap_limit(self):
        now = timezone.now()
        SupportThread.objects.create(
            requester_kind=SupportThread.Requester.MEMBER, user_id=uuid.uuid4(),
            last_message_at=now - timedelta(hours=2),
            last_customer_message_at=now - timedelta(hours=2),
        )
        user = uuid.uuid4()
        for _ in range(device_swaps.MONTHLY_LIMIT):
            DeviceLinkEvent.objects.create(
                user_id=user, device_id=uuid.uuid4(), previous_device_id=uuid.uuid4(),
                is_swap=True, created_at=now,
            )
        body = self.body()["support"]
        self.assertEqual(body["threadsWaiting"], 1)
        self.assertEqual({b["key"]: b["count"] for b in body["waitBuckets"]}["h4"], 1)
        self.assertEqual(body["swapLimit"]["count"], 1)

        # Ett extra tillfälle från supporten: inte längre vid gränsen.
        DeviceSwapGrant.objects.create(
            user_id=user, month_key=device_swaps.month_key(now), created_at=now,
        )
        self.assertEqual(self.body()["support"]["swapLimit"]["count"], 0)
