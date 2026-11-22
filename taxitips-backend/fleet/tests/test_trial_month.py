"""
Provmånaden (ägarens beslut 2026-11-22): engångskommandot som förlänger
pågående prov, och att påminnelserna före provslut kommer igen efter en
förlängning -- men aldrig två gånger för samma slut.
"""

from __future__ import annotations

from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.utils import timezone

from fleet import commerce, notifications, trials
from fleet.models import AuditEvent, OutboxMessage, Trial
from fleet.tests.base import FleetTestCase


class ExtendRunningTrialsTests(FleetTestCase):
    def trial(self, *, started_days_ago=None, length=7, status=Trial.Status.ACTIVE, planned=None):
        company = self.make_company(name="Prov AB", org_number="", status="inactive")
        trial = Trial.objects.create(
            company_id=company.id, org_key=f"t:{company.id.hex}", source=Trial.Source.SELF_SIGNUP,
            requires_payment_method=False, vehicle_limit=1, planned_days=planned, status=status,
        )
        if started_days_ago is not None:
            started = timezone.now() - timedelta(days=started_days_ago)
            Trial.objects.filter(id=trial.id).update(
                started_at=started, ends_at=started + timedelta(days=length),
            )
        trial.refresh_from_db()
        return trial

    def run_command(self, *args):
        out = StringIO()
        call_command("extend_running_trials", *args, stdout=out)
        return out.getvalue()

    def test_without_apply_nothing_changes(self):
        trial = self.trial(started_days_ago=2)
        before = trial.ends_at
        out = self.run_command()
        trial.refresh_from_db()
        self.assertEqual(trial.ends_at, before)
        self.assertIn("extend", out)
        self.assertIn("inget ändrat", out)

    def test_a_running_week_trial_ends_a_month_after_its_start(self):
        trial = self.trial(started_days_ago=2)
        self.run_command("--apply")
        trial.refresh_from_db()
        self.assertGreaterEqual(trial.ends_at, trial.started_at + timedelta(days=30))
        self.assertLess(trial.ends_at, trial.started_at + timedelta(days=31))
        event = AuditEvent.objects.get(action="trial_extended", company_id=trial.company_id)
        self.assertEqual(event.actor_kind, "system")

    def test_running_twice_extends_once(self):
        trial = self.trial(started_days_ago=2)
        self.run_command("--apply")
        trial.refresh_from_db()
        first = trial.ends_at
        out = self.run_command("--apply")
        trial.refresh_from_db()
        self.assertEqual(trial.ends_at, first)
        self.assertIn("skip_long_enough", out)

    def test_a_trial_a_seller_already_extended_is_left_alone(self):
        trial = self.trial(started_days_ago=2, length=40)
        before = trial.ends_at
        self.run_command("--apply")
        trial.refresh_from_db()
        self.assertEqual(trial.ends_at, before)

    def test_a_pending_trial_gets_the_month(self):
        trial = self.trial(status=Trial.Status.PENDING, planned=7)
        self.run_command("--apply")
        trial.refresh_from_db()
        self.assertEqual(trial.planned_days, 30)

    def test_a_pending_trial_without_length_already_has_the_month(self):
        trial = self.trial(status=Trial.Status.PENDING)
        self.run_command("--apply")
        trial.refresh_from_db()
        self.assertIsNone(trial.planned_days)
        self.assertEqual(trials.TRIAL_DAYS, 30)

    def test_a_trial_committed_in_stripe_is_listed_not_moved(self):
        trial = self.trial(started_days_ago=2)
        before = trial.ends_at
        with mock.patch.object(commerce, "has_active_trial_commit", return_value=True):
            out = self.run_command("--apply")
        trial.refresh_from_db()
        self.assertEqual(trial.ends_at, before)
        self.assertIn("skip_committed", out)


class RemindersAfterExtensionTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.company = self.make_company(name="Påminn AB", org_number="", status="inactive")
        now = timezone.now()
        self.trial = Trial.objects.create(
            company_id=self.company.id, org_key=f"t:{self.company.id.hex}",
            source=Trial.Source.SELF_SIGNUP, requires_payment_method=False, vehicle_limit=1,
            status=Trial.Status.ACTIVE, started_at=now - timedelta(days=5), ends_at=now + timedelta(days=2),
        )

    def remind(self):
        return notifications.trial_ending(
            self.company.id, "kund@example.test", self.trial, stage="card_missing_3d",
        )

    def count(self):
        return OutboxMessage.objects.filter(category="trial_ending", company_id=self.company.id).count()

    def test_the_same_end_is_reminded_once(self):
        self.remind()
        self.remind()
        self.assertEqual(self.count(), 1)

    def test_a_reminder_queued_with_the_old_key_is_not_sent_again(self):
        # Före 2026-11-22 saknade nyckeln slutdatumet.
        OutboxMessage.objects.create(
            company_id=self.company.id, category="trial_ending", to_address="kund@example.test",
            subject="Provet slutar", body="...", payload={},
            dedupe_key=notifications.dedupe_key("trial_ending", self.company.id, self.trial.id, "card_missing_3d"),
        )
        self.remind()
        self.assertEqual(self.count(), 1)

    def test_an_extended_trial_is_reminded_again_before_its_new_end(self):
        OutboxMessage.objects.create(
            company_id=self.company.id, category="trial_ending", to_address="kund@example.test",
            subject="Provet slutar", body="...", payload={},
            dedupe_key=notifications.dedupe_key("trial_ending", self.company.id, self.trial.id, "card_missing_3d"),
        )
        Trial.objects.filter(id=self.trial.id).update(ends_at=self.trial.ends_at + timedelta(days=23))
        self.trial.refresh_from_db()
        self.remind()
        self.assertEqual(self.count(), 2)
