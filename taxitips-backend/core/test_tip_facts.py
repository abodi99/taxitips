"""
Modellen läser fakta, reglerna sätter poängen (core/tip_facts.py).
"""

from __future__ import annotations

import json
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from core import thresholds
from core.genkit import apply_cached, review
from core.models import Opportunity, RailAssessment, SeverityTier
from core.repository import upsert_opportunities
from core.scoring import gap_score
from core.tests import opportunity_row
from core.tip_facts import PARTIAL_ROUTE_SCORE, SHORT_DELAY_SCORE, TipFacts, classify_from_facts, stated_gap


def facts(**fields) -> TipFacts:
    return TipFacts(**fields)


class ClassifyFromFactsTests(SimpleTestCase):
    def test_noise_is_ignored(self):
        for event in ("facility_or_stop_change", "planned_future", "resolved"):
            verdict = classify_from_facts(facts(event_type=event), "bus", 60)
            self.assertEqual((verdict.tier, verdict.score), (SeverityTier.IGNORE, 0), event)

    def test_delays_follow_the_text_scoring_ladder(self):
        short = classify_from_facts(facts(event_type="delay", delay_minutes=5), "bus")
        self.assertEqual((short.tier, short.score), (SeverityTier.VEHICLE_DELAYED, SHORT_DELAY_SCORE))
        rail = classify_from_facts(facts(event_type="delay", delay_minutes=25, mode="train"))
        self.assertEqual((rail.tier, rail.score), (SeverityTier.LINE_DELAYED, 30))
        serious = classify_from_facts(facts(event_type="delay", delay_minutes=90), "bus")
        self.assertEqual((serious.tier, serious.score), (SeverityTier.LINE_DELAYED, 55))

    def test_a_stated_replacement_means_nobody_is_stranded(self):
        verdict = classify_from_facts(facts(event_type="whole_line_stop", alternative="replacement"), "train")
        self.assertEqual((verdict.tier, verdict.score, verdict.has_alternative),
                         (SeverityTier.VEHICLE_CANCELLED, 25, True))

    def test_the_stated_next_departure_sets_the_gap(self):
        # Västtågen 7239 15:18, nästa 15:53 (2026-10-04).
        verdict = classify_from_facts(facts(
            event_type="single_departure", departure_clock="15:18", next_departure_clock="15:53",
            alternative="next_departure",
        ), "train")
        self.assertEqual((verdict.tier, verdict.score, verdict.condition),
                         (SeverityTier.LINE_PAUSED, gap_score(35), "known_gap"))
        self.assertIsNone(verdict.has_alternative)

    def test_whole_line_single_and_partial(self):
        self.assertEqual(classify_from_facts(facts(event_type="whole_line_stop", alternative="none")).score, 70)
        self.assertEqual(classify_from_facts(facts(event_type="single_departure")).score, 20)
        self.assertEqual(classify_from_facts(facts(event_type="partial_route")).score, PARTIAL_ROUTE_SCORE)

    def test_unclear_never_looks_strong(self):
        verdict = classify_from_facts(facts(event_type="unclear"), "unknown", 85)
        self.assertEqual((verdict.tier, verdict.score), (SeverityTier.DISRUPTION_UNCLASSIFIED, 30))

    def test_unknown_values_fall_back_to_unclear(self):
        verdict = classify_from_facts({"event_type": "kaos", "alternative": "kanske"}, "bus", 40)
        self.assertEqual(verdict.condition, "unclear")

    def test_gap_over_midnight_and_reading_errors(self):
        self.assertEqual(stated_gap(facts(departure_clock="23:50", next_departure_clock="05:10")), 320)
        self.assertIsNone(stated_gap(facts(departure_clock="08:00", next_departure_clock="08:00")))
        self.assertIsNone(stated_gap(facts(departure_clock="kl åtta", next_departure_clock="09:00")))


def make(external_id="sl:fordonsfel", score=38, **kw):
    upsert_opportunities([opportunity_row(
        external_id, demand_score=score, confidence="low", mode="unknown",
        severity_tier="disruption_unclassified", title="Inställd tur",
        summary="Inställd p.g.a. fordonsfel.", region="sl", **kw,
    )])
    return Opportunity.objects.get(external_id=external_id)


def answer(**fields) -> str:
    return json.dumps(TipFacts(**fields).model_dump())


class ReviewWithFactsTests(TestCase):
    def test_the_rules_score_what_the_model_read(self):
        # 2026-10-04 höjde modellen själv detta från 38 till 85.
        o = make()
        review(o, lambda prompt: answer(event_type="single_departure", mode="bus", cause="fordonsfel",
                                        why="En tur är inställd på grund av fordonsfel."), facts=True)
        o.refresh_from_db()
        self.assertEqual(o.demand_score, 20)
        self.assertEqual(o.severity_tier, SeverityTier.VEHICLE_CANCELLED)
        self.assertEqual(o.mode, "bus")
        self.assertEqual(o.rule_id, "bus.vehicle_cancelled.ai_facts.single_departure")
        self.assertIn("AI läste: En tur är inställd på grund av fordonsfel.", o.reasons)
        stored = RailAssessment.objects.get(opportunity=o)
        self.assertEqual(stored.facts["event_type"], "single_departure")

    def test_the_prompt_asks_for_facts_not_a_score(self):
        o = make()
        prompts = []
        review(o, lambda prompt: prompts.append(prompt) or answer(), facts=True)
        self.assertIn("Du sätter ingen poäng", prompts[0])
        self.assertIn("Inställd p.g.a. fordonsfel.", prompts[0])

    def test_a_raise_from_facts_is_still_capped(self):
        o = make(score=30)
        review(o, lambda prompt: answer(event_type="whole_line_stop", alternative="none"), facts=True)
        o.refresh_from_db()
        self.assertEqual(o.demand_score, thresholds.AI_RAISE_CAP)
        self.assertNotEqual(o.level, "high")

    def test_a_cached_reading_is_rescored_by_the_current_rules(self):
        o = make()
        review(o, lambda prompt: answer(event_type="single_departure"), facts=True)
        # Samma text vid nästa poll: regelvärdena tillbaka, cachen läggs på igen.
        o = make()
        with patch("core.text_scoring.SINGLE_DEPARTURE_SCORE", 15):
            apply_cached(o)
        o.refresh_from_db()
        self.assertEqual(o.demand_score, 15)
        self.assertEqual(RailAssessment.objects.count(), 1)

    def test_garbage_keeps_the_rule_score(self):
        o = make()
        self.assertIsNone(review(o, lambda prompt: "inget json här", facts=True))
        o.refresh_from_db()
        self.assertEqual(o.demand_score, 38)
