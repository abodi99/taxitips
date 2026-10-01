"""Provförlängning, valfri provlängd och företagsrabatt."""

from datetime import timedelta

from django.utils import timezone

from fleet import discounts, pricing, trials
from fleet.models import CompanyDiscount, Trial
from fleet.tests.base import price_version
from fleet.tests.test_sales import SalesTestCase


class TrialExtendTests(SalesTestCase):
    def test_sales_can_start_a_trial_with_custom_length(self):
        company = self.new_company()
        response = self.post(
            f"/api/admin/companies/{company.id}/trial",
            {"vehicles": self.vehicles("LNG01"), "days": 21},
        )
        self.assertEqual(response.status_code, 200, response.content)
        trial = Trial.objects.get(company_id=company.id)
        self.assertEqual(trial.planned_days, 21)

    def test_extend_pending_trial_increases_planned_days(self):
        company = self.new_company()
        self.post(f"/api/admin/companies/{company.id}/trial", {"vehicles": self.vehicles("E1")})
        trial = Trial.objects.get(company_id=company.id)
        self.assertEqual(trial.status, Trial.Status.PENDING)
        response = self.post(
            f"/api/admin/companies/{company.id}/trial/extend",
            {"days": 5, "reason": "Telefonerna kom sent"},
            user=self.sales_id,
        )
        self.assertEqual(response.status_code, 200, response.content)
        trial.refresh_from_db()
        self.assertEqual(trial.planned_days, trials.TRIAL_DAYS + 5)

    def test_extend_active_trial_moves_end_date(self):
        company = self.new_company()
        self.post(f"/api/admin/companies/{company.id}/trial", {"vehicles": self.vehicles("E2"), "days": 10})
        trial = Trial.objects.get(company_id=company.id)
        started = timezone.now() - timedelta(days=2)
        Trial.objects.filter(id=trial.id).update(
            status=Trial.Status.ACTIVE, started_at=started, ends_at=started + timedelta(days=10)
        )
        trial.refresh_from_db()
        before = trial.ends_at
        response = self.post(
            f"/api/admin/companies/{company.id}/trial/extend",
            {"days": 3, "reason": "Säljaren lovade förlängning"},
            user=self.sales_id,
        )
        self.assertEqual(response.status_code, 200, response.content)
        trial.refresh_from_db()
        self.assertEqual(trial.ends_at, before + timedelta(days=3))

    def test_extend_requires_a_reason(self):
        company = self.new_company()
        self.post(f"/api/admin/companies/{company.id}/trial", {"vehicles": self.vehicles("E3")})
        response = self.post(
            f"/api/admin/companies/{company.id}/trial/extend",
            {"days": 1, "reason": "  "},
            user=self.sales_id,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["reason"], "reason_required")


class CompanyDiscountTests(SalesTestCase):
    def test_admin_sets_percent_discount_and_quote_reflects_it(self):
        company = self.new_company()
        response = self.post(
            f"/api/admin/companies/{company.id}/discount",
            {"kind": "percent_bp", "value": 1000, "description": "Pilot"},
            user=self.admin_id,
        )
        self.assertEqual(response.status_code, 200, response.content)
        price = price_version()
        spec = discounts.active_spec(company.id)
        self.assertIsNotNone(spec)
        quote = pricing.monthly_quote(
            price, licenses=2, extra_counties=0, intro=False, discount=spec
        )
        self.assertTrue(any(line.key == "company_discount" for line in quote.lines))
        base = pricing.monthly_quote(price, licenses=2, extra_counties=0, intro=False)
        self.assertLess(quote.amount_ore, base.amount_ore)

    def test_sales_cannot_set_discount(self):
        company = self.new_company()
        response = self.post(
            f"/api/admin/companies/{company.id}/discount",
            {"kind": "percent_bp", "value": 500},
            user=self.sales_id,
        )
        self.assertEqual(response.status_code, 403)

    def test_clear_discount_deactivates_row(self):
        company = self.new_company()
        discounts.set_discount(
            company.id, kind=CompanyDiscount.Kind.FIXED_ORE, value=10_000,
            actor_user_id=self.admin_id,
        )
        response = self.post(
            f"/api/admin/companies/{company.id}/discount/clear",
            {"reason": "Avtalet löpte ut"},
            user=self.admin_id,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(discounts.active_spec(company.id))
