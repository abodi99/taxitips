"""
Automatisk onboarding: mejlen som för en provkund till betalningen, och att
de faktiskt skickas (fleet/mailer.py, fleet/notifications.py).
"""

from __future__ import annotations

import smtplib
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core import mail
from django.core.management import call_command
from django.test import override_settings
from django.utils import timezone

from fleet import mailer, notifications, trials
from fleet.models import License, OutboxMessage, Trial
from fleet.tests.base import FleetTestCase

SMTP = override_settings(
    FLEET_SMTP_USER="hej@taxitips.se", FLEET_SMTP_PASSWORD="hemligt", FLEET_OUTBOX_SENDER="",
    FLEET_PORTAL_URL="https://taxitips.se/portal",
)


def locmem():
    """Djangos testbrevlåda i stället för Hostinger."""
    from django.core.mail import get_connection

    return mock.patch(
        "fleet.mailer._connection",
        side_effect=lambda: get_connection("django.core.mail.backends.locmem.EmailBackend"),
    )


class TrialFixture(FleetTestCase):
    def trial_company(self, *, plates=("ABC123", "DEF456"), ends_in=timedelta(days=2)):
        company = self.make_company(name="Provtaxi AB", org_number="5569999005", status="inactive")
        self.make_owner(company)
        trial = trials.create_trial(
            company_id=company.id, country="SE", org_number="5569999005",
            source=Trial.Source.SELF_SIGNUP, requires_payment_method=False,
        )
        for plate in plates:
            vehicle, license = self.make_license(company, plate=plate, county="01")
            License.objects.filter(id=license.id).update(status=License.Status.TRIAL, trial=trial)
        now = timezone.now()
        Trial.objects.filter(id=trial.id).update(
            status=Trial.Status.ACTIVE, started_at=now - timedelta(days=12), ends_at=now + ends_in,
        )
        trial.refresh_from_db()
        return company, trial


@SMTP
class SenderTests(TrialFixture):
    def test_the_outbox_goes_out_through_smtp_with_reply_to_support(self):
        notifications.queue(
            category="trial_started", to_address="agare@provtaxi.test",
            subject="Hej", body="Text", key_parts=("x",),
        )
        with locmem():
            result = notifications.send_pending()
        self.assertEqual(result["sent"], 1)
        sent = mail.outbox[0]
        self.assertEqual(sent.to, ["agare@provtaxi.test"])
        self.assertEqual(sent.from_email, "TaxiTips <hej@taxitips.se>")
        self.assertEqual(sent.reply_to, ["hej@taxitips.se"])

    def test_a_temporary_failure_is_retried_and_a_permanent_one_is_not(self):
        temporary = notifications.queue(
            category="trial_started", to_address="a@provtaxi.test", subject="s", body="b",
            key_parts=("tmp",),
        )
        permanent = notifications.queue(
            category="trial_started", to_address="", subject="s", body="b", key_parts=("perm",),
        )
        with mock.patch("fleet.mailer._connection", side_effect=smtplib.SMTPServerDisconnected("borta")):
            result = notifications.send_pending()
        self.assertEqual((result["retry"], result["failed"]), (1, 1))
        temporary.refresh_from_db()
        permanent.refresh_from_db()
        self.assertEqual(temporary.status, OutboxMessage.Status.PENDING)
        self.assertIn("borta", temporary.error)
        self.assertEqual(permanent.status, OutboxMessage.Status.FAILED)

    def test_retries_stop_after_two_days(self):
        row = notifications.queue(
            category="trial_started", to_address="a@provtaxi.test", subject="s", body="b",
            key_parts=("old",),
        )
        OutboxMessage.objects.filter(id=row.id).update(created_at=timezone.now() - timedelta(days=3))
        with mock.patch("fleet.mailer._connection", side_effect=smtplib.SMTPServerDisconnected("borta")):
            notifications.send_pending()
        row.refresh_from_db()
        self.assertEqual(row.status, OutboxMessage.Status.FAILED)

    def test_a_backlog_from_before_the_sender_existed_is_never_sent(self):
        old = notifications.queue(
            category="trial_started", to_address="a@provtaxi.test", subject="s", body="b",
            key_parts=("backlog",),
        )
        OutboxMessage.objects.filter(id=old.id).update(created_at=timezone.now() - timedelta(days=20))
        with locmem():
            result = notifications.send_pending()
        self.assertEqual((result["sent"], result["stale"]), (0, 1))
        self.assertEqual(len(mail.outbox), 0)
        old.refresh_from_db()
        self.assertEqual(old.status, OutboxMessage.Status.FAILED)

    def test_nothing_is_sent_without_credentials(self):
        with self.settings(FLEET_SMTP_PASSWORD=""):
            self.assertIsNone(notifications._configured_sender())
        self.assertIs(notifications._configured_sender(), mailer.send)


@SMTP
class TrialMailTests(TrialFixture):
    def test_the_reminder_has_the_price_the_portal_will_show_and_a_link(self):
        company, trial = self.trial_company()
        row = notifications.trial_ending(company.id, "agare@provtaxi.test", trial)
        self.assertIn("https://taxitips.se/portal#fortsatt", row.body)
        self.assertIn("ABC123, DEF456", row.body)
        # Två bilar à 799 kr, exklusive moms -- samma motor som portalens offert.
        self.assertIn("1\xa0598,00 kr i månaden exkl. moms", row.body)
        self.assertEqual(row.payload["offer"]["count"], 2)

    def test_three_days_before_and_the_last_day_are_two_mails(self):
        company, trial = self.trial_company(ends_in=timedelta(days=2, hours=12))
        with locmem():
            call_command("fleet_tick", stdout=StringIO())
            call_command("fleet_tick", stdout=StringIO())
        self.assertEqual(OutboxMessage.objects.filter(category="trial_ending").count(), 1)
        Trial.objects.filter(id=trial.id).update(ends_at=timezone.now() + timedelta(hours=10))
        with locmem():
            call_command("fleet_tick", stdout=StringIO())
        stages = sorted(
            OutboxMessage.objects.filter(category="trial_ending").values_list("payload__stage", flat=True)
        )
        self.assertEqual(stages, ["1d", "3d"])

    def test_an_expired_trial_gets_a_way_back(self):
        company, trial = self.trial_company(ends_in=timedelta(hours=-1))
        with locmem():
            call_command("fleet_tick", stdout=StringIO())
        row = OutboxMessage.objects.get(category="trial_ended")
        self.assertIn("#fortsatt", row.body)
        self.assertEqual(row.to_address, company.email)


class ContinueVehiclesTests(TrialFixture):
    def test_the_active_trials_cars(self):
        company, _ = self.trial_company()
        plates = [v["plate"] for v in trials.continue_vehicles(company.id)]
        self.assertEqual(plates, ["ABC123", "DEF456"])

    def test_the_cars_of_a_trial_that_ended_without_an_order(self):
        company, trial = self.trial_company()
        trials.end_trial(trial, reason="trial_period_over")
        cars = trials.continue_vehicles(company.id)
        self.assertEqual([c["plate"] for c in cars], ["ABC123", "DEF456"])
        self.assertEqual({c["baseCounty"] for c in cars}, {"01"})

    def test_nothing_to_continue_for_a_paying_company(self):
        data = self.full_setup()
        self.assertEqual(trials.continue_vehicles(data["company"].id), [])
