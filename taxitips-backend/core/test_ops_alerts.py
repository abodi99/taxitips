"""Driftlarm: mejl bara vid övergång, inte varje cykel."""

from datetime import timedelta

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from core import ops_alerts, pipeline_health, thresholds
from core.models import SourceStatus


@override_settings(
    OPS_ALERT_EMAIL="ops@example.test",
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class OpsAlertTests(TestCase):
    def setUp(self):
        mail.outbox.clear()
        now = timezone.now()
        SourceStatus.objects.update_or_create(
            source=thresholds.HEARTBEAT_SOURCE,
            defaults={
                "ok": True, "message": "", "detail": {}, "checked_at": now,
                "last_success_at": now, "consecutive_failures": 0,
            },
        )
        for source in thresholds.CORE_SOURCES:
            SourceStatus.objects.update_or_create(
                source=source,
                defaults={
                    "ok": True, "message": "", "detail": {}, "checked_at": now,
                    "last_success_at": now, "consecutive_failures": 0,
                },
            )

    def test_ok_pipeline_does_not_email_on_first_run(self):
        result = ops_alerts.maybe_notify()
        self.assertIsNone(result["action"])
        self.assertFalse(result["sent"])
        self.assertEqual(len(mail.outbox), 0)

    def test_ok_to_fail_sends_one_mail_and_debounce_skips_the_rest(self):
        now = timezone.now()
        self.assertTrue(pipeline_health.evaluate(now)["ok"])
        ops_alerts.maybe_notify(now)

        SourceStatus.objects.filter(source=thresholds.HEARTBEAT_SOURCE).delete()
        down = ops_alerts.maybe_notify(now + timedelta(seconds=1))
        self.assertEqual(down["action"], "down")
        self.assertTrue(down["sent"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("nere", mail.outbox[0].subject)

        again = ops_alerts.maybe_notify(now + timedelta(minutes=2))
        self.assertIsNone(again["action"])
        self.assertEqual(len(mail.outbox), 1)

    def test_recovery_sends_an_up_mail(self):
        now = timezone.now()
        ops_alerts.maybe_notify(now)
        SourceStatus.objects.filter(source=thresholds.HEARTBEAT_SOURCE).delete()
        ops_alerts.maybe_notify(now + timedelta(seconds=1))
        self.assertEqual(len(mail.outbox), 1)

        SourceStatus.objects.update_or_create(
            source=thresholds.HEARTBEAT_SOURCE,
            defaults={
                "ok": True, "message": "", "detail": {},
                "checked_at": now + timedelta(seconds=2),
                "last_success_at": now + timedelta(seconds=2),
                "consecutive_failures": 0,
            },
        )
        up = ops_alerts.maybe_notify(now + timedelta(seconds=3))
        self.assertEqual(up["action"], "up")
        self.assertEqual(len(mail.outbox), 2)
        self.assertIn("uppe", mail.outbox[1].subject)

    def test_empty_recipient_skips(self):
        with override_settings(OPS_ALERT_EMAIL=""):
            result = ops_alerts.maybe_notify()
        self.assertEqual(result["skipped"], "no_recipient")
        self.assertEqual(len(mail.outbox), 0)

    def test_decide_debounces_new_problems(self):
        now = timezone.now()
        last = {
            "ok": False,
            "problems": ["heartbeat_stale"],
            "emailed_at": now.isoformat(),
        }
        current = {"ok": False, "problems": ["trafiklab_stale"]}
        self.assertIsNone(ops_alerts.decide(current, last, now=now + timedelta(minutes=5)))
        self.assertEqual(
            ops_alerts.decide(current, last, now=now + timedelta(minutes=31)),
            "down",
        )
