"""Provförlängning, valfri provlängd och företagsrabatt."""

from datetime import timedelta

from django.utils import timezone

from fleet import discounts, pricing, trials
from fleet.models import CompanyDiscount, Trial
from fleet.tests.base import price_version
from fleet.tests.test_sales import SalesTestCase


class TrialExtendTests(SalesTestCase):
    def test_a_trial_is_always_seven_days_when_it_starts(self):
        """
        Ägarens beslut 2026-10-03: provet är 7 dagar för alla. Ett säljarprov
        hade fått 14; mer tid är en förlängning med skäl, inte en annan start.
        """
        company = self.new_company()
        refused = self.post(
            f"/api/admin/companies/{company.id}/trial",
            {"vehicles": self.vehicles("LNG01"), "days": 21},
        )
        self.assertEqual(refused.status_code, 400)
        self.assertEqual(refused.json()["reason"], "invalid_trial_days")
        self.assertFalse(Trial.objects.filter(company_id=company.id).exists())

        response = self.post(f"/api/admin/companies/{company.id}/trial", {"vehicles": self.vehicles("LNG01")})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn(Trial.objects.get(company_id=company.id).planned_days, (None, trials.TRIAL_DAYS))

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
        self.post(f"/api/admin/companies/{company.id}/trial", {"vehicles": self.vehicles("E2")})
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


class TrialVehicleLimitTests(SalesTestCase):
    """
    Ägarens beslut 2026-10-04: ny registrering får 1 bil, 7 dagar, ett län och
    tåg & buss. Fler bilar delas ut för hand i admin, med skäl i loggen.
    """

    def start(self, plate):
        company = self.new_company()
        self.post(f"/api/admin/companies/{company.id}/trial", {"vehicles": self.vehicles(plate)})
        return company, Trial.objects.get(company_id=company.id)

    def test_every_new_trial_has_one_car(self):
        _company, trial = self.start("ONE01")
        self.assertEqual(trial.vehicle_limit, 1)
        self.assertEqual(Trial._meta.get_field("vehicle_limit").default, 1)

    def test_admin_gives_more_cars_by_hand_and_it_is_logged(self):
        from fleet.models import AuditEvent

        company, trial = self.start("MAN01")
        refused = self.post(
            f"/api/admin/companies/{company.id}/trial", {"vehicles": self.vehicles("MAN02")},
        )
        self.assertEqual(refused.status_code, 400)

        response = self.post(
            f"/api/admin/companies/{company.id}/trial/vehicles",
            {"vehicleLimit": 3, "reason": "Stort bolag vill prova med tre bilar"},
            user=self.sales_id,
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["vehicleLimit"], 3)
        trial.refresh_from_db()
        self.assertEqual(trial.vehicle_limit, 3)
        added = self.post(
            f"/api/admin/companies/{company.id}/trial", {"vehicles": self.vehicles("MAN02")},
        )
        self.assertEqual(added.status_code, 200, added.content)
        event = AuditEvent.objects.filter(action="trial_vehicle_limit_set").get()
        self.assertEqual((event.detail["before"], event.detail["after"]), (1, 3))

    def test_the_limit_never_drops_below_the_cars_already_in_the_trial(self):
        company, _trial = self.start("LOW01")
        response = self.post(
            f"/api/admin/companies/{company.id}/trial/vehicles",
            {"vehicleLimit": 0, "reason": "Fel"}, user=self.sales_id,
        )
        self.assertEqual(response.json()["reason"], "invalid_vehicle_limit")
        self.post(
            f"/api/admin/companies/{company.id}/trial/vehicles",
            {"vehicleLimit": 2, "reason": "Två bilar"}, user=self.sales_id,
        )
        self.post(f"/api/admin/companies/{company.id}/trial", {"vehicles": self.vehicles("LOW02")})
        lowered = self.post(
            f"/api/admin/companies/{company.id}/trial/vehicles",
            {"vehicleLimit": 1, "reason": "Tillbaka till en"}, user=self.sales_id,
        )
        self.assertEqual(lowered.status_code, 400)
        self.assertEqual(lowered.json()["reason"], "below_current")

    def test_a_reason_is_required(self):
        company, _trial = self.start("WHY01")
        response = self.post(
            f"/api/admin/companies/{company.id}/trial/vehicles",
            {"vehicleLimit": 2, "reason": " "}, user=self.sales_id,
        )
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
