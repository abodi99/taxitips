"""
Källhälsa: ett försök skiljs från en lyckad hämtning, och /health/pipeline
blir röd bara för det som faktiskt stoppar produkten.
"""

from __future__ import annotations

import datetime as dt
from io import StringIO

from django.core.management import CommandError, call_command
from django.test import TestCase
from django.utils import timezone

from core import thresholds
from core.health import beat_heartbeat, polling
from core.models import SourceStatus
from core.pipeline_health import evaluate


def _succeeded(source: str, now: dt.datetime, minutes_ago: int = 0) -> None:
    at = now - dt.timedelta(minutes=minutes_ago)
    SourceStatus.objects.update_or_create(
        source=source, defaults={"ok": True, "checked_at": at, "last_success_at": at},
    )


class PollingTests(TestCase):
    def test_success_records_last_success(self):
        with polling("sl"):
            pass
        status = SourceStatus.objects.get(source="sl")
        self.assertTrue(status.ok)
        self.assertEqual(status.last_success_at, status.checked_at)
        self.assertEqual(status.consecutive_failures, 0)

    def test_failure_keeps_last_success_and_counts(self):
        """Ett fel flyttar checked_at. Utan en egen tid ser källan färsk ut medan den felar."""
        with polling("sl"):
            pass
        succeeded_at = SourceStatus.objects.get(source="sl").last_success_at
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                with polling("sl"):
                    raise RuntimeError("429 exceeded its quota")
        status = SourceStatus.objects.get(source="sl")
        self.assertFalse(status.ok)
        self.assertEqual(status.last_success_at, succeeded_at)
        self.assertGreater(status.checked_at, succeeded_at)
        self.assertEqual(status.consecutive_failures, 2)

    def test_success_resets_the_failure_count(self):
        with self.assertRaises(RuntimeError):
            with polling("sl"):
                raise RuntimeError("timeout")
        with polling("sl"):
            pass
        self.assertEqual(SourceStatus.objects.get(source="sl").consecutive_failures, 0)

    def test_run_without_fetch_is_not_a_success(self):
        """En källa utan nyckel är inget fel, men den får inte se färsk ut."""
        with polling("swedavia") as status:
            status.note = "SWEDAVIA_API_KEY saknas"
            status.fetched = False
        status = SourceStatus.objects.get(source="swedavia")
        self.assertTrue(status.ok)
        self.assertIsNone(status.last_success_at)


class PipelineHealthTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        beat_heartbeat(worker="celery@test", now=self.now)
        for source in thresholds.CORE_SOURCES:
            _succeeded(source, self.now)

    def test_fresh_heartbeat_and_core_sources_is_healthy(self):
        report = evaluate(self.now)
        self.assertTrue(report["ok"], report["problems"])

    def test_stopped_beat_is_unhealthy(self):
        later = self.now + dt.timedelta(seconds=thresholds.HEARTBEAT_MAX_AGE_SECONDS + 1)
        self.assertEqual(evaluate(later)["problems"], ["heartbeat_stale"])

    def test_missing_heartbeat_is_unhealthy(self):
        SourceStatus.objects.filter(source=thresholds.HEARTBEAT_SOURCE).delete()
        self.assertEqual(evaluate(self.now)["problems"], ["heartbeat_missing"])

    def test_failing_core_source_is_judged_by_its_last_success(self):
        max_age = thresholds.SOURCE_MAX_AGE_MINUTES["sl"]
        SourceStatus.objects.filter(source="sl").update(
            ok=False, checked_at=self.now,
            last_success_at=self.now - dt.timedelta(minutes=max_age + 1),
        )
        self.assertEqual(evaluate(self.now)["problems"], ["sl_stale"])

    def test_optional_source_never_blocks(self):
        report = evaluate(self.now)
        ticketmaster = next(s for s in report["sources"] if s["source"] == "ticketmaster")
        self.assertTrue(ticketmaster["stale"])
        self.assertFalse(ticketmaster["core"])
        self.assertTrue(report["ok"])

    def test_endpoint_is_503_without_source_messages(self):
        max_age = thresholds.SOURCE_MAX_AGE_MINUTES["sl"]
        SourceStatus.objects.filter(source="sl").update(
            ok=False, message="HTTPError: https://api.example.invalid/?key=hemlig-nyckel",
            last_success_at=self.now - dt.timedelta(minutes=max_age + 5),
        )
        response = self.client.get("/health/pipeline")
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("hemlig-nyckel", response.content.decode())
        self.assertEqual(response["Cache-Control"], "no-store")

    def test_endpoint_is_200_when_healthy(self):
        response = self.client.get("/health/pipeline")
        self.assertEqual(response.status_code, 200, response.json()["problems"])

    def test_check_pipeline_fails_when_unhealthy(self):
        SourceStatus.objects.filter(source=thresholds.HEARTBEAT_SOURCE).delete()
        with self.assertRaises(CommandError):
            call_command("check_pipeline", stdout=StringIO())
