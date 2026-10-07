"""
Urvalet av telefoner i pushcykeln (core/notify._devices) vilar på samma
fråga som listan och sändgrinden: fleet.access.company_window.

Mätt i produktion 2026-10-07: `push_delivery` hade noll rader i hela sitt liv.
Urvalet läste `companies.status`, och det enda bolaget med en telefon stod
som `canceled` där -- trots ett giltigt prov i `fleet_trial`. Telefonen föll
bort innan grinden tillfrågades, och svaret blev `no_devices`.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from core import notify
from fleet.models import Subscription, SubscriptionStatus, Trial
from fleet.tests.base import FleetTestCase, price_version
from fleet import orders


class PushDeviceSelectionTests(FleetTestCase):
    def _trial(self, company, *, days_left=5):
        now = timezone.now()
        orders.get_or_create_subscription(company.id, price_version=price_version())
        return Trial.objects.create(
            company_id=company.id, org_key=f"SE{company.org_number}",
            source=Trial.Source.SELF_SIGNUP, status=Trial.Status.ACTIVE,
            started_at=now - timedelta(days=2), ends_at=now + timedelta(days=days_left),
        )

    def test_a_valid_trial_counts_even_when_the_legacy_status_says_canceled(self):
        company = self.make_company(status="canceled")
        self._trial(company)
        device = self.make_device(company, push_token="fcm-token")

        chosen = notify._devices()

        self.assertEqual([d.id for d in chosen], [device.id])

    def test_an_ended_trial_without_payment_is_left_out(self):
        company = self.make_company(status="canceled")
        self._trial(company, days_left=-1)
        Trial.objects.filter(company_id=company.id).update(status=Trial.Status.ENDED)
        self.make_device(company, push_token="fcm-token")

        self.assertEqual(notify._devices(), [])

    def test_a_canceled_subscription_past_its_paid_period_is_left_out(self):
        company = self.make_company(status="active")
        subscription = self.make_subscription(company, days_left=-3, status=SubscriptionStatus.CANCELED)
        Subscription.objects.filter(id=subscription.id).update(access_until=None)
        self.make_device(company, push_token="fcm-token")

        self.assertEqual(notify._devices(), [])

    def test_a_legacy_company_without_the_new_model_still_counts(self):
        """Omigrerat bolag: bolagets status i Supabase gäller, som förut."""
        company = self.make_company(status="active")
        device = self.make_device(company, push_token="fcm-token")

        self.assertEqual([d.id for d in notify._devices()], [device.id])

    def test_token_requirement_and_weak_filter_are_kept(self):
        company = self.make_company(status="active")
        self.make_device(company, push_token=None)
        weak = self.make_device(company, push_token="t")
        type(weak).objects.filter(id=weak.id).update(notify_prefs={"weak": True})

        self.assertEqual(len(notify._devices()), 1)
        self.assertEqual([d.id for d in notify._devices(weak_only=True)], [weak.id])
        self.assertEqual(len(notify._devices(require_token=False)), 2)
