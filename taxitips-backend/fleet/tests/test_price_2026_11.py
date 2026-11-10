"""
Prislista 2026-11: 399 kr per plats, samma pris oavsett antal, inga nya extra län.

Den gamla listan (2026-09-v1) ligger kvar i varje test via `price_version()`;
den nya skapas av `seed_pricing` -- samma kommando som körs i produktion, så att
kommandot och prislistan prövas tillsammans.
"""

from __future__ import annotations

from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.utils import timezone

from fleet import licensing, orders, price_moves, pricing, trials
from fleet.models import License, PriceVersion, Subscription, SubscriptionStatus, Trial
from fleet.tests.base import FleetTestCase, price_version

NEW_ID = "2026-11-v1"


def seed_new(*extra, **kw):
    out = StringIO()
    call_command(
        "seed_pricing", "--id", NEW_ID, "--label", "Prislista 2026-11",
        "--base", "399", "--volume", "399", "--terms-version", "2026-11",
        "--disable-intro", "--default", *extra, stdout=out, **kw,
    )
    return out.getvalue()


class SeedPricingTests(FleetTestCase):
    def test_creates_the_list_and_flips_the_default(self):
        seed_new()
        new = PriceVersion.objects.get(id=NEW_ID)
        self.assertEqual((new.base_price_ore, new.volume_price_ore), (39900, 39900))
        self.assertEqual(new.vat_rate_bp, 2500)
        self.assertEqual(new.currency, "SEK")
        self.assertFalse(new.intro_enabled)
        self.assertEqual(new.terms_version, "2026-11")
        # Länsavgiften ärvs, bara för att befintliga extra län ska kunna prissättas.
        self.assertEqual(new.extra_county_price_ore, 19900)
        self.assertTrue(new.is_default)
        self.assertEqual(list(PriceVersion.objects.filter(is_default=True)), [new])

    def test_old_list_is_untouched_except_default(self):
        before = PriceVersion.objects.values().get(id="2026-09-v1")
        seed_new()
        after = PriceVersion.objects.values().get(id="2026-09-v1")
        self.assertTrue(before.pop("is_default"))
        self.assertFalse(after.pop("is_default"))
        self.assertEqual(before, after)

    def test_is_idempotent(self):
        seed_new()
        first = PriceVersion.objects.values().get(id=NEW_ID)
        seed_new()
        self.assertEqual(PriceVersion.objects.values().get(id=NEW_ID), first)
        self.assertEqual(PriceVersion.objects.filter(is_default=True).count(), 1)

    def test_dry_run_changes_nothing(self):
        out = seed_new("--dry-run")
        self.assertIn("DRY RUN", out)
        self.assertFalse(PriceVersion.objects.filter(id=NEW_ID).exists())
        self.assertTrue(PriceVersion.objects.get(id="2026-09-v1").is_default)
        seed_new()
        out = seed_new("--dry-run")
        self.assertIn("inga fältändringar", out)

    def test_new_subscriptions_get_the_default_list(self):
        seed_new()
        company = self.make_company()
        self.assertEqual(orders.get_or_create_subscription(company.id).price_version_id, NEW_ID)


class NewListQuoteTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        seed_new()
        self.new = PriceVersion.objects.get(id=NEW_ID)

    def test_one_seat(self):
        q = pricing.monthly_quote(self.new, licenses=1, extra_counties=0, intro=False)
        self.assertEqual((q.amount_ore, q.total_ore), (39900, 49875))

    def test_twelve_seats_have_no_volume_step(self):
        q = pricing.monthly_quote(self.new, licenses=12, extra_counties=0, intro=False)
        self.assertEqual(q.amount_ore, 478800)
        self.assertEqual(q.total_ore, 598500)

    def _company_on_new_list(self):
        data = self.full_setup(county="12")
        Subscription.objects.filter(company_id=data["company"].id).update(price_version=self.new)
        return data

    def test_adding_an_extra_county_is_refused(self):
        data = self._company_on_new_list()
        with self.assertRaises(orders.OrderError) as caught:
            orders.plan_change(
                data["company"].id,
                add_counties=[{"licenseId": str(data["license"].id), "county": "01"}],
            )
        self.assertEqual(caught.exception.reason, "extra_counties_not_sold")
        self.assertEqual(
            caught.exception.message, "Fler län säljs inte längre. Varje plats gäller ett län."
        )

    def test_an_existing_extra_county_is_still_priced_and_can_be_removed(self):
        data = self._company_on_new_list()
        company_id = data["company"].id
        licensing.activate_extra_county(license=data["license"], county_code="01")
        # Behålls: prissätts med listans länsavgift.
        q = pricing.monthly_quote(
            self.new, licenses=1,
            extra_counties=licensing.extra_county_count(company_id, timezone.now()), intro=False,
        )
        self.assertEqual(q.amount_ore, 39900 + 19900)
        # Tas bort: nekas inte, och nästa period är bara platsen.
        plan = orders.plan_change(
            company_id, remove_counties=[{"licenseId": str(data["license"].id), "county": "01"}],
        )
        self.assertEqual(plan.quote.next_period.amount_ore, 39900)

    def test_the_old_list_still_sells_extra_counties(self):
        data = self.full_setup(county="12")
        plan = orders.plan_change(
            data["company"].id,
            add_counties=[{"licenseId": str(data["license"].id), "county": "01"}],
        )
        self.assertGreater(plan.quote.now.total_ore, 0)


class TrialFollowsDefaultTests(FleetTestCase):
    def _trial_company(self):
        """Ett prov som registrerades FÖRE prisbytet: abonnemangsraden pekar på gamla listan."""
        company = self.make_company()
        self.make_owner(company)
        sub = orders.get_or_create_subscription(company.id, price_version=price_version())
        self.assertEqual(sub.status, SubscriptionStatus.NONE)
        trial = trials.create_trial(
            company_id=company.id, country="SE", org_number="5566778899",
            source=Trial.Source.SELF_SIGNUP, requires_payment_method=False,
        )
        trials.start_trial(trial)
        vehicle = licensing.create_vehicle(company_id=company.id, plate="TRI001")
        licensing.create_license(
            company_id=company.id, vehicle=vehicle, base_county="12",
            status=License.Status.TRIAL, trial=trial,
        )
        return company, trial

    def test_trial_offer_shows_399_after_the_switch(self):
        company, trial = self._trial_company()
        seed_new()
        from fleet import notifications

        offer = notifications.trial_offer(company.id, trial)
        self.assertEqual(offer["monthly_ore"], 39900)
        self.assertEqual(offer["monthly_total_ore"], 49875)
        self.assertEqual(Subscription.objects.get(company_id=company.id).price_version_id, NEW_ID)
        self.assertIn("399,00 kr", notifications._offer_lines(offer))

    def test_a_paying_subscription_keeps_its_list(self):
        data = self.full_setup()
        seed_new()
        sub = orders.get_or_create_subscription(data["company"].id)
        self.assertEqual(sub.price_version_id, "2026-09-v1")

    def test_a_subscription_with_a_stripe_id_keeps_its_list(self):
        company = self.make_company()
        sub = orders.get_or_create_subscription(company.id)
        Subscription.objects.filter(id=sub.id).update(stripe_subscription_id="sub_x")
        seed_new()
        self.assertEqual(orders.get_or_create_subscription(company.id).price_version_id, "2026-09-v1")


class MovePlanTests(FleetTestCase):
    def test_plan_for_a_subscription_with_three_seats(self):
        company = self.make_company(name="Betalande Taxi AB")
        self.make_owner(company)
        subscription = self.make_subscription(company)
        for i in range(3):
            self.make_license(company, plate=f"MOV{i:03d}")
        seed_new()
        subscription.refresh_from_db()
        self.assertEqual(subscription.price_version_id, "2026-09-v1")

        with mock.patch("fleet.stripe_sync._client", side_effect=AssertionError("ingen Stripe")):
            plan = price_moves.plan_move_to_price_version(subscription, NEW_ID)

        self.assertEqual(plan["companyId"], str(company.id))
        self.assertEqual(plan["companyName"], "Betalande Taxi AB")
        self.assertEqual(plan["currentPriceVersion"], "2026-09-v1")
        self.assertEqual(plan["seats"], 3)
        self.assertEqual(plan["currentMonthlyExVatOre"], 3 * 79900)
        self.assertEqual(plan["currentMonthlyInclVatOre"], 299625)
        self.assertEqual(plan["newMonthlyExVatOre"], 3 * 39900)
        self.assertEqual(plan["newMonthlyInclVatOre"], 149625)
        self.assertEqual(plan["effectiveAt"], subscription.current_period_end.isoformat())
        self.assertEqual(plan["stripe"]["chargedNow"], 0)
        self.assertEqual(
            plan["stripe"]["newItems"],
            [{"unitAmountOre": 39900, "quantity": 3, "interval": "month"}],
        )
        # Planen ändrar ingenting.
        subscription.refresh_from_db()
        self.assertEqual(subscription.price_version_id, "2026-09-v1")

    def test_only_active_subscriptions_can_be_planned(self):
        company = self.make_company()
        sub = orders.get_or_create_subscription(company.id)
        seed_new()
        with self.assertRaises(price_moves.PriceMoveError):
            price_moves.plan_move_to_price_version(sub, NEW_ID)

    def test_command_defaults_to_dry_run_and_apply_is_not_implemented(self):
        from django.core.management.base import CommandError

        company = self.make_company()
        self.make_owner(company)
        self.make_subscription(company)
        self.make_license(company)
        seed_new()
        out = StringIO()
        call_command("move_price_version", "--company", str(company.id), "--to", NEW_ID, stdout=out)
        self.assertIn("torrkörning", out.getvalue())
        with self.assertRaises(CommandError):
            call_command(
                "move_price_version", "--company", str(company.id), "--to", NEW_ID, "--apply",
                stdout=StringIO(),
            )
        self.assertEqual(
            Subscription.objects.get(company_id=company.id).price_version_id, "2026-09-v1"
        )
