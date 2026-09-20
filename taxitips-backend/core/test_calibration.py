"""
Kalibreringsrapporten räknar rätt och säger "för lite underlag" hellre än att gissa.
"""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from core import calibration
from core.models import OpportunityFeedback, PushDelivery
from core.test_notify import opportunity

T0 = dt.datetime(2026, 9, 14, 8, 0, tzinfo=dt.timezone.utc)


def call(terminal="visby", *, lead=60, first_error=6, last_error=2, arrived=True, basis="distance"):
    arrived_at = T0 + dt.timedelta(minutes=lead) if arrived else None
    return SimpleNamespace(
        terminal=terminal, eta_basis=basis, arrived_at=arrived_at, first_estimate_at=T0,
        first_berth_eta=arrived_at - dt.timedelta(minutes=first_error) if arrived else None,
        berth_eta=arrived_at - dt.timedelta(minutes=last_error) if arrived else None,
    )


class PureTests(SimpleTestCase):
    def test_ferry_lead_and_errors_per_terminal(self):
        rows = calibration.ferry_report([call(lead=60), call(lead=80, first_error=-4), call(arrived=False)])
        (visby,) = rows
        self.assertEqual((visby["calls"], visby["arrived"]), (3, 2))
        self.assertEqual(visby["leadMedianMinutes"], 70.0)
        self.assertEqual(visby["firstErrorMedianMinutes"], 1.0)
        self.assertEqual(visby["firstErrorP90AbsMinutes"], 6.0)
        self.assertFalse(visby["enough"])

    def test_fare_rate_ignores_heading_and_flags_thin_data(self):
        rows = [("fare", "train.line_paused")] * 3 + [("empty", "train.line_paused")] + [("heading", "train.line_paused")] * 5
        (row,) = calibration.feedback_report(rows)
        self.assertEqual((row["fare"], row["empty"], row["heading"], row["fareRate"]), (3, 1, 5, 0.75))
        self.assertFalse(row["enough"])

    def test_score_bands_split_on_the_notify_floor(self):
        bands = {b["band"]: b for b in calibration.score_band_report([("fare", 49), ("empty", 50), ("fare", 90)])}
        self.assertEqual((bands["0-49"]["fare"], bands["50-69"]["empty"], bands["85-100"]["fare"]), (1, 1, 1))

    def test_thin_data_is_said_out_loud(self):
        notes = calibration.conclusions([], calibration.score_band_report([]), calibration.push_report([]), [], 50)
        self.assertTrue(any("För lite feedback" in n for n in notes))
        self.assertTrue(any("Inga AIS-anlöp" in n for n in notes))


class BuildTests(TestCase):
    def test_report_reads_feedback_and_the_outbox(self):
        now = timezone.now()
        tip = opportunity(rule_id="train.line_paused", demand_score=80)
        OpportunityFeedback.objects.create(opportunity=tip, device_token="a", verdict="fare")
        OpportunityFeedback.objects.create(opportunity=tip, device_token="b", verdict="empty")
        PushDelivery.objects.create(
            device_id="00000000-0000-0000-0000-000000000001", opportunity_external_id=tip.external_id,
            status=PushDelivery.Status.SENT, attempts=1, sent_at=now,
        )
        report = calibration.build(now=now + dt.timedelta(seconds=5))
        self.assertEqual(report["feedback"][0]["rule"], "train.line_paused")
        self.assertEqual(report["feedback"][0]["fareRate"], 0.5)
        self.assertEqual(report["push"]["byStatus"], {"sent": 1})
        self.assertTrue(any("För lite feedback" in n for n in report["notes"]))
