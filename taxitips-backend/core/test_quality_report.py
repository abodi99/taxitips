"""
Nattrapporten (core/quality_report.py): koden räknar, AI:n sammanfattar, och
rapporten byggs en gång per dygn. Transporten är utbytt -- inget nät.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase, override_settings

from core import ai_client, quality_report, thresholds
from core.models import AiCall, Opportunity, OpportunityFeedback, QualityReport, RailAssessment
from core.test_notify import opportunity

TZ = ZoneInfo("Europe/Stockholm")
DAY = date(2026, 10, 3)
NOON = datetime(2026, 10, 3, 12, 0, tzinfo=TZ)
NEXT_MORNING = datetime(2026, 10, 4, 6, 0, tzinfo=TZ)


def at(model_qs, when):
    model_qs.update(created_at=when)


class StatsTests(TestCase):
    def setUp(self):
        self.tip = opportunity(title="Inställd tur", rule_id="unknown.unclassified", county_code="01")
        Opportunity.objects.filter(pk=self.tip.pk).update(
            notified_at=NOON, reasons=["AI stoppade notisen: nästa tur går strax"],
        )
        AiCall.objects.create(purpose="extract", model="m", ok=True, cost_micro_usd=500_000)
        AiCall.objects.create(purpose="gate", model="m", ok=False)
        at(AiCall.objects.all(), NOON)
        a = RailAssessment.objects.create(
            opportunity=self.tip, cache_key="k", rule_score=85, model_score=20, final_score=20,
            verdict="en tur inställd", model_name="m", facts={"event_type": "single_departure"},
        )
        at(RailAssessment.objects.filter(pk=a.pk), NOON)
        OpportunityFeedback.objects.create(opportunity=self.tip, device_token="d", verdict="fare")
        at(OpportunityFeedback.objects.all(), NOON)

    def test_the_numbers_come_from_the_code(self):
        start, end = quality_report.window_for(DAY)
        s = quality_report.stats(start, end)
        self.assertEqual(s["ai"]["perSyfte"]["extract"], {"anrop": 1, "lyckade": 1, "kostnadKr": 5.0})
        self.assertEqual(s["ai"]["perSyfte"]["gate"]["lyckade"], 0)
        self.assertEqual(s["granskning"]["oeniga"], 1)
        self.assertEqual(s["granskning"]["handelser"], {"single_departure": 1})
        self.assertEqual(s["granskning"]["exempel"][0]["regel"], 85)
        self.assertEqual(s["notiser"]["stoppadeAvAi"], 1)
        self.assertEqual(s["notiser"]["perLan"], {"01": 1})
        self.assertEqual(s["forare"], {"fare": 1})

    def test_other_days_are_not_counted(self):
        start, end = quality_report.window_for(DAY + timedelta(days=1))
        s = quality_report.stats(start, end)
        self.assertEqual(s["granskning"]["bedomningar"], 0)
        self.assertEqual(s["notiser"]["tips"], 0)


@override_settings(TAXITIPS_AI="on")
class RunTests(TestCase):
    def setUp(self):
        patcher = patch.object(ai_client, "api_key", return_value="test-key")
        patcher.start()
        self.addCleanup(patcher.stop)

    def summarizing(self):
        def transport(model, prompt, schema, timeout):
            self.prompt = prompt
            return schema(summary="Lugnt dygn.", suggestions=["Sänk X", " ", "Höj Y"]), 2000, 150

        return patch.object(ai_client, "transport", transport)

    def test_built_once_per_day_after_five(self):
        with self.summarizing():
            self.assertIsNone(quality_report.run(datetime(2026, 10, 4, 4, 0, tzinfo=TZ)))
            report = quality_report.run(NEXT_MORNING)
            self.assertIsNone(quality_report.run(NEXT_MORNING + timedelta(hours=1)))
        self.assertEqual(report.day, DAY)
        self.assertEqual(report.summary, "Lugnt dygn.")
        self.assertEqual(report.suggestions, ["Sänk X", "Höj Y"])
        self.assertEqual(report.model, thresholds.AI_MODEL_GATE)
        self.assertIn('"dygn": "2026-10-03"', self.prompt)
        self.assertEqual(AiCall.objects.get().purpose, "report")

    @override_settings(TAXITIPS_AI="off")
    def test_without_ai_the_numbers_are_still_saved(self):
        report = quality_report.run(NEXT_MORNING)
        self.assertEqual((report.summary, report.suggestions, report.model), ("", [], ""))
        self.assertIn("granskning", report.stats)

    def test_the_dashboard_shows_spend_gate_and_latest_report(self):
        from fleet.admin_dashboard import _kvalitet

        with self.summarizing():
            quality_report.run(NEXT_MORNING)
        section = _kvalitet(NEXT_MORNING)
        self.assertTrue(section["aiEnabled"])
        self.assertEqual(section["report"]["day"], "2026-10-03")
        self.assertEqual(section["report"]["summary"], "Lugnt dygn.")
        self.assertEqual(section["spend"]["budgetKr"], thresholds.AI_MONTHLY_BUDGET_KR)
        self.assertEqual(QualityReport.objects.count(), 1)
