"""
Prismotorn: belopp, moms, volymgräns, introduktion och proportionering.

Beloppen här är uppdragets egna tal. Testerna är skrivna som räkneexempel --
går de sönder ska det gå att se på siffran vad som ändrats.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.utils import timezone

from fleet import pricing
from fleet.models import Subscription
from fleet.tests.base import FleetTestCase, price_version


class MonthlyAmountTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.price = price_version()

    def test_nine_licenses_use_base_price(self):
        quote = pricing.monthly_quote(self.price, licenses=9, extra_counties=0, intro=False)
        self.assertEqual(quote.amount_ore, 9 * 79900)
        self.assertEqual(quote.vat_ore, 9 * 79900 // 4)
        self.assertEqual(quote.total_ore, 9 * 79900 + 9 * 79900 // 4)

    def test_ten_licenses_reprice_all_of_them(self):
        """Volympriset gäller SAMTLIGA köpta licenser, inte bara de över gränsen."""
        quote = pricing.monthly_quote(self.price, licenses=10, extra_counties=0, intro=False)
        self.assertEqual(quote.amount_ore, 10 * 74900)
        # Tio bilar kostar mindre än nio gör vid gränsen -- avsiktligt.
        nine = pricing.monthly_quote(self.price, licenses=9, extra_counties=0, intro=False)
        self.assertLess(quote.amount_ore - nine.amount_ore, 79900)

    def test_extra_counties_are_never_discounted(self):
        volume = pricing.monthly_quote(self.price, licenses=12, extra_counties=3, intro=False)
        base = pricing.monthly_quote(self.price, licenses=12, extra_counties=0, intro=False)
        self.assertEqual(volume.amount_ore - base.amount_ore, 3 * 19900)

    def test_intro_and_volume_do_not_combine(self):
        """
        Aldrig summan av båda rabatterna. Med dagens tal betyder det
        introduktionspriset, eftersom det redan är lägre än volympriset.
        """
        intro = pricing.monthly_quote(self.price, licenses=12, extra_counties=0, intro=True)
        self.assertEqual(intro.amount_ore, 12 * 69900)
        # Inte 749 - (799-699) = 649.
        self.assertNotEqual(intro.amount_ore, 12 * 64900)

    def test_intro_does_not_discount_extra_counties(self):
        quote = pricing.monthly_quote(self.price, licenses=2, extra_counties=2, intro=True)
        self.assertEqual(quote.amount_ore, 2 * 69900 + 2 * 19900)

    def test_vat_is_twenty_five_percent_of_the_net(self):
        quote = pricing.monthly_quote(self.price, licenses=1, extra_counties=1, intro=False)
        self.assertEqual(quote.amount_ore, 79900 + 19900)
        self.assertEqual(quote.vat_ore, (79900 + 19900) * 2500 // 10000)


class RoundingTests(FleetTestCase):
    def test_halves_round_up_not_to_even(self):
        """
        Pythons round() är bankers rounding och hade gett 0 här. En faktura ska
        gå att räkna efter för hand.
        """
        self.assertEqual(pricing._round_div(1, 2), 1)
        self.assertEqual(pricing._round_div(3, 2), 2)
        self.assertEqual(pricing._round_div(-1, 2), -1)

    def test_proration_clamps_outside_the_period(self):
        now = timezone.now()
        start, end = now - timedelta(days=10), now - timedelta(days=1)
        remaining, total = pricing.proration_factor(now, start, end)
        self.assertEqual(remaining, 0)
        self.assertGreater(total, 0)


class VolumeBoundaryTests(FleetTestCase):
    """9 <-> 10 i båda riktningarna (§11)."""

    def setUp(self):
        super().setUp()
        self.price = price_version()
        self.now = timezone.now()
        self.start = self.now - timedelta(days=15)
        self.end = self.now + timedelta(days=15)

    def test_tenth_license_charges_only_the_difference(self):
        quote = pricing.quote_change(
            self.price, now=self.now, period_start=self.start, period_end=self.end,
            intro_now=False, intro_next_period=False,
            current_licenses=9, current_extra_counties=0,
            new_licenses=10, new_extra_counties=0, immediate=True,
        )
        # 10 x 749 - 9 x 799 = 2990 kr; halva perioden kvar.
        monthly_delta = 10 * 74900 - 9 * 79900
        self.assertEqual(monthly_delta, 29900)
        self.assertAlmostEqual(quote.now.amount_ore, monthly_delta // 2, delta=1500)
        self.assertEqual(quote.next_period.amount_ore, 10 * 74900)

    def test_going_back_to_nine_takes_effect_next_renewal(self):
        quote = pricing.quote_change(
            self.price, now=self.now, period_start=self.start, period_end=self.end,
            intro_now=False, intro_next_period=False,
            current_licenses=10, current_extra_counties=0,
            new_licenses=9, new_extra_counties=0, immediate=False,
        )
        # Inget att betala nu, och ingen kreditering.
        self.assertEqual(quote.now.total_ore, 0)
        # Nästa period tillbaka på grundpriset.
        self.assertEqual(quote.next_period.amount_ore, 9 * 79900)
        self.assertEqual(quote.effective_at, self.end)

    def test_upgrade_never_produces_a_credit(self):
        quote = pricing.quote_change(
            self.price, now=self.now, period_start=self.start, period_end=self.end,
            intro_now=False, intro_next_period=False,
            current_licenses=10, current_extra_counties=2,
            new_licenses=10, new_extra_counties=0, immediate=True,
        )
        self.assertEqual(quote.now.amount_ore, 0)


class IntroCampaignTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.price = price_version()

    def test_campaign_is_off_without_a_launch_date(self):
        """Kampanjen får inte startas från ett gissat lanseringsdatum (§6)."""
        self.assertFalse(self.price.intro_enabled)
        self.assertIsNone(self.price.launch_date)
        self.assertFalse(pricing.intro_available(self.price, timezone.now()))

    def test_enabling_without_a_date_still_gives_nothing(self):
        self.price.intro_enabled = True
        self.price.save(update_fields=["intro_enabled"])
        self.assertFalse(pricing.intro_available(self.price, timezone.now()))

    def test_within_sixty_days_of_launch_qualifies(self):
        now = timezone.now()
        self.price.intro_enabled = True
        self.price.launch_date = (now - timedelta(days=30)).date()
        self.price.save(update_fields=["intro_enabled", "launch_date"])
        self.assertTrue(pricing.intro_available(self.price, now))

    def test_after_the_window_does_not_qualify(self):
        now = timezone.now()
        self.price.intro_enabled = True
        self.price.launch_date = (now - timedelta(days=61)).date()
        self.price.save(update_fields=["intro_enabled", "launch_date"])
        self.assertFalse(pricing.intro_available(self.price, now))

    def test_before_launch_does_not_qualify(self):
        now = timezone.now()
        self.price.intro_enabled = True
        self.price.launch_date = (now + timedelta(days=5)).date()
        self.price.save(update_fields=["intro_enabled", "launch_date"])
        self.assertFalse(pricing.intro_available(self.price, now))

    def test_intro_window_is_three_calendar_months(self):
        from datetime import datetime, timezone as dt_timezone

        start = datetime(2026, 1, 31, 12, 0, tzinfo=dt_timezone.utc)
        end = pricing.intro_window(self.price, start)
        # 31 januari + 3 månader -> 30 april, inte 31 april.
        self.assertEqual(end.date(), date(2026, 4, 30))

    def test_intro_is_read_from_the_saved_window_not_the_campaign(self):
        """
        Fönstret sattes när första betalningen lyckades. Att någon ändrar
        kampanjkonfigurationen efteråt får inte flytta det.
        """
        now = timezone.now()
        company = self.make_company()
        subscription = self.make_subscription(company)
        Subscription.objects.filter(id=subscription.id).update(
            intro_started_at=now - timedelta(days=10),
            intro_ends_at=now + timedelta(days=80),
        )
        subscription.refresh_from_db()
        self.assertTrue(pricing.intro_active(subscription, now))

        self.price.intro_enabled = False
        self.price.save(update_fields=["intro_enabled"])
        self.assertTrue(pricing.intro_active(subscription, now))

    def test_intro_ends_when_the_window_passes(self):
        now = timezone.now()
        company = self.make_company()
        subscription = self.make_subscription(company)
        Subscription.objects.filter(id=subscription.id).update(
            intro_started_at=now - timedelta(days=120),
            intro_ends_at=now - timedelta(days=30),
        )
        subscription.refresh_from_db()
        self.assertFalse(pricing.intro_active(subscription, now))
