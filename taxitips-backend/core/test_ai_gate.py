"""
Andra bedömningen före en notis (core/ai_gate.py): får stoppa, aldrig tysta
en störning för att AI:n inte svarar. Transporten är utbytt -- inget nät.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from django.test import TestCase, override_settings

from core import ai_client, notify, thresholds
from core.models import AiCall, Opportunity, RailAssessment, SeverityTier
from core.test_notify import FakeDevice, SupabaseCompanyMixin, opportunity
from core.tip_facts import TipFacts


def facts(**fields):
    return TipFacts(**fields)


def bankeryd(**overrides):
    """Västtågen 7239, 2026-10-04: 85 poäng och en notis, fast nästa tåg gick 35 min senare."""
    fields = dict(
        external_id="vt:7239",
        title="Västtågen 7239 klockan 15:18 är inställt från Bankeryd station",
        summary="Nästa avgång är Västtågen 7241klockan 15:53 från Bankeryd station mot Jönköping.",
        severity_tier=SeverityTier.LINE_PAUSED, demand_score=85, confidence="low",
        rule_id="train.line_paused.ambiguous",
    )
    fields.update(overrides)
    return opportunity(**fields)


@override_settings(TAXITIPS_AI="on")
class AiGateTests(SupabaseCompanyMixin, TestCase):
    def setUp(self):
        self.sent = []
        self.calls = []
        patcher = patch.object(ai_client, "api_key", return_value="test-key")
        patcher.start()
        self.addCleanup(patcher.stop)

    def answer(self, reading: TipFacts | Exception):
        def transport(model, prompt, schema, timeout):
            self.calls.append({"model": model, "timeout": timeout})
            if isinstance(reading, Exception):
                raise reading
            return reading, 1200, 80

        return patch.object(ai_client, "transport", transport)

    def cycle(self):
        def sender(*, token, title, body, data, **_):
            self.sent.append(title)
            return {"ok": True}

        with patch.object(notify, "_devices", return_value=[FakeDevice()]):
            return notify.run_push_cycle(sender=sender)

    def test_a_stated_next_departure_stops_the_push(self):
        tip = bankeryd()
        reading = facts(event_type="single_departure", departure_clock="15:18",
                        next_departure_clock="15:53", alternative="next_departure",
                        why="Ett tåg är inställt; nästa går 35 minuter senare.")
        with self.answer(reading):
            result = self.cycle()
        self.assertEqual(self.sent, [])
        self.assertEqual(result["aiGate"]["blocked"], 1)
        tip.refresh_from_db()
        self.assertIsNotNone(tip.notified_at)
        self.assertLess(tip.demand_score, thresholds.NOTIFY_SCORE_FLOOR)
        self.assertTrue(any(r.startswith("AI stoppade notisen") for r in tip.reasons))
        # Den bättre modellen, med grindens korta tidsgräns.
        self.assertEqual(self.calls[0], {"model": thresholds.AI_MODEL_GATE, "timeout": thresholds.AI_GATE_TIMEOUT_S})
        self.assertEqual(AiCall.objects.get().purpose, "gate")

    def test_a_confirmed_stop_still_wakes_the_driver(self):
        bankeryd()
        with self.answer(facts(event_type="whole_line_stop", alternative="none")):
            result = self.cycle()
        self.assertEqual(result["sent"], 1)

    def test_the_gate_never_raises_a_score(self):
        tip = bankeryd(demand_score=65)
        with self.answer(facts(event_type="whole_line_stop", alternative="none")):  # reglerna: 70
            self.cycle()
        tip.refresh_from_db()
        self.assertEqual(tip.demand_score, 65)

    @override_settings(TAXITIPS_AI="off")
    def test_ai_switched_off_lets_the_push_through(self):
        bankeryd()
        with self.answer(facts(event_type="resolved")):
            result = self.cycle()
        self.assertEqual(result["sent"], 1)
        self.assertEqual(self.calls, [])

    def test_a_failing_model_lets_the_push_through(self):
        bankeryd()
        with self.answer(TimeoutError("långsam")):
            result = self.cycle()
        self.assertEqual(result["sent"], 1)
        self.assertEqual(result["aiGate"]["failOpen"], 1)
        self.assertFalse(AiCall.objects.get().ok)

    def test_certain_rules_are_never_gated(self):
        opportunity(rule_id="train.line_paused.whole_line_stop", demand_score=85)
        with self.answer(facts(event_type="resolved")):
            result = self.cycle()
        self.assertEqual(result["sent"], 1)
        self.assertEqual(self.calls, [])

    def test_a_cached_reading_needs_no_new_call(self):
        tip = bankeryd()
        from core.genkit import normalize_key

        RailAssessment.objects.create(
            opportunity=tip, cache_key=normalize_key(tip), rule_score=85, model_score=0, final_score=0,
            verdict="redan över", model_name="x", facts=facts(event_type="resolved").model_dump(),
        )
        with self.answer(facts(event_type="whole_line_stop")):
            result = self.cycle()
        self.assertEqual(self.calls, [])
        self.assertEqual(result["aiGate"]["cached"], 1)
        self.assertEqual(self.sent, [])

    def test_at_most_a_few_calls_per_cycle(self):
        stations = ["Alingsås", "Borås", "Herrljunga", "Lerum", "Floda", "Vårgårda", "Skövde", "Falköping"]
        for i, station in enumerate(stations[: thresholds.AI_GATE_MAX_PER_CYCLE + 2]):
            # Olika text: samma text hade delat cachen och bara kostat ett anrop.
            bankeryd(external_id=f"vt:{i}", title=f"Västtåg är inställt från {station}", summary="")
        with self.answer(facts(event_type="whole_line_stop", alternative="none")):
            result = self.cycle()
        self.assertEqual(len(self.calls), thresholds.AI_GATE_MAX_PER_CYCLE)
        self.assertEqual(result["aiGate"]["deferred"], 2)
        # De som väntade är fortfarande kandidater nästa cykel.
        self.assertEqual(Opportunity.objects.filter(notified_at__isnull=True).count(), 2)
