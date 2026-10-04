"""
AI-klienten: varje anrop loggas med kostnad, och avstängning, dagstak och
månadsbudget stoppar anropet innan det görs. Inget test når nätverket:
transporten byts ut.
"""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from pydantic import BaseModel

from core import ai_client, thresholds
from core.models import AiCall


class Verdict(BaseModel):
    ok: bool = True


def fake(output=None, tokens_in=1000, tokens_out=100, error=None):
    calls = []

    def transport(model, prompt, schema, timeout):
        calls.append({"model": model, "prompt": prompt, "timeout": timeout})
        if error:
            raise error
        return (output if output is not None else schema()), tokens_in, tokens_out

    transport.calls = calls
    return transport


class AiClientTests(TestCase):
    def setUp(self):
        patcher = patch.object(ai_client, "api_key", return_value="test-key")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_call_is_logged_with_tokens_and_cost(self):
        with patch.object(ai_client, "transport", fake()):
            out = ai_client.generate("extract", "prompt", Verdict, subject="sl:1")
        self.assertTrue(out.ok)
        call = AiCall.objects.get()
        self.assertEqual((call.purpose, call.model, call.ok), ("extract", thresholds.AI_MODEL_EXTRACT, True))
        self.assertEqual((call.tokens_in, call.tokens_out, call.subject), (1000, 100, "sl:1"))
        # Flash-Lite: 1000 × 0,30 + 100 × 2,50 miljondels dollar.
        self.assertEqual(call.cost_micro_usd, 550)

    def test_the_model_is_pinned_not_an_alias(self):
        transport = fake()
        with patch.object(ai_client, "transport", transport):
            ai_client.generate("gate", "p", Verdict, model=thresholds.AI_MODEL_GATE)
        self.assertEqual(transport.calls[0]["model"], "gemini-3.8-flash")
        self.assertNotIn("latest", thresholds.AI_MODEL_EXTRACT)

    def test_a_failure_is_logged_and_raised(self):
        with patch.object(ai_client, "transport", fake(error=TimeoutError("för långsam"))):
            with self.assertRaises(TimeoutError):
                ai_client.generate("extract", "p", Verdict)
        call = AiCall.objects.get()
        self.assertFalse(call.ok)
        self.assertIn("TimeoutError", call.error)

    @override_settings(TAXITIPS_AI="off")
    def test_the_off_switch_stops_every_call(self):
        transport = fake()
        with patch.object(ai_client, "transport", transport):
            with self.assertRaises(ai_client.AiUnavailable):
                ai_client.generate("extract", "p", Verdict)
        self.assertEqual(transport.calls, [])
        self.assertFalse(AiCall.objects.exists())

    def test_no_key_means_no_call(self):
        with patch.object(ai_client, "api_key", return_value=None):
            self.assertEqual(ai_client.unavailable_reason(), "GEMINI_API_KEY saknas")

    def test_the_daily_cap_stops_a_runaway_loop(self):
        with patch.object(thresholds, "AI_DAILY_CALL_CAP", 2), patch.object(ai_client, "transport", fake()):
            ai_client.generate("extract", "p", Verdict)
            ai_client.generate("extract", "p", Verdict)
            with self.assertRaises(ai_client.AiUnavailable):
                ai_client.generate("extract", "p", Verdict)
        self.assertEqual(AiCall.objects.count(), 2)

    def test_the_monthly_budget_stops_calls_before_the_bill_grows(self):
        AiCall.objects.create(purpose="extract", model="x", ok=True, cost_micro_usd=200_000)  # 2 kr
        with patch.object(thresholds, "AI_MONTHLY_BUDGET_KR", 1):
            self.assertIn("månadsbudgeten", ai_client.unavailable_reason())
        self.assertEqual(ai_client.spend()["costMonthKr"], 2.0)

    def test_json_caller_feeds_the_review(self):
        from core.genkit import review
        from core.management.commands.review_uncertain import ReviewVerdict
        from core.repository import upsert_opportunities
        from core.models import Opportunity
        from core.tests import opportunity_row

        upsert_opportunities([opportunity_row("sl:ai", demand_score=40, confidence="low")])
        o = Opportunity.objects.get(external_id="sl:ai")
        verdict = ReviewVerdict(score=10, severity_tier="vehicle_delayed", why="liten försening")
        with patch.object(ai_client, "transport", fake(output=verdict)):
            review(o, ai_client.json_caller("review", ReviewVerdict, subject=o.external_id))
        o.refresh_from_db()
        self.assertEqual(o.demand_score, 10)
        self.assertEqual(AiCall.objects.get().subject, "sl:ai")


class ReviewCommandTests(TestCase):
    @override_settings(TAXITIPS_AI="off")
    def test_the_review_says_why_it_did_nothing(self):
        from core.repository import upsert_opportunities
        from core.tests import opportunity_row

        upsert_opportunities([opportunity_row("sl:off", demand_score=40, confidence="low")])
        out = StringIO()
        call_command("review_uncertain", stdout=out)
        self.assertIn("AI används inte just nu", out.getvalue())
        self.assertFalse(AiCall.objects.exists())
