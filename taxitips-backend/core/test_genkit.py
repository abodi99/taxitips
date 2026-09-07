"""
Tester för språkmodellsgranskningen.

Tyngdpunkten är skyddsräcket. En modell som kan höja poäng skickar förare
på bomresor -- det är den enda felmodet som kostar riktiga pengar.
"""

from django.test import TestCase

from core.genkit import normalize_key, review
from core.models import Opportunity, RailAssessment
from core.repository import upsert_opportunities
from core.tests import opportunity_row


def make(score=85, title="Hållplats Elektravägen inställd pga vägarbete", **kw):
    upsert_opportunities([opportunity_row(
        "sl:test", demand_score=score, title=title, confidence="low", **kw
    )])
    return Opportunity.objects.get(external_id="sl:test")


class GuardrailTests(TestCase):
    def test_model_can_lower(self):
        o = make(score=85)
        review(o, lambda p: '{"score": 20, "stranded": false, "why": "vägarbete"}')
        o.refresh_from_db()
        self.assertEqual(o.demand_score, 20)

    def test_model_cannot_raise(self):
        # Det enda felet som kostar pengar: en modell som skickar förare
        # på bomresor genom att höja en poäng.
        o = make(score=40)
        review(o, lambda p: '{"score": 99, "stranded": true, "why": "allvarligt"}')
        o.refresh_from_db()
        self.assertEqual(o.demand_score, 40, "poängen får aldrig höjas")

    def test_guardrail_lives_in_the_model_too(self):
        # Även om någon anropar RailAssessment direkt ska taket gälla.
        o = make(score=30)
        a = RailAssessment.objects.create(
            opportunity=o, cache_key="x", rule_score=30, model_score=95,
            final_score=95,  # medvetet fel -- save() ska rätta det
        )
        self.assertEqual(a.final_score, 30)


class FailureTests(TestCase):
    """En trasig modell får aldrig ändra ett tips eller stoppa pipelinen."""

    def test_exception_keeps_rule_score(self):
        o = make(score=85)
        def boom(prompt):
            raise RuntimeError("timeout")
        self.assertIsNone(review(o, boom))
        o.refresh_from_db()
        self.assertEqual(o.demand_score, 85)

    def test_garbage_response_keeps_rule_score(self):
        o = make(score=85)
        self.assertIsNone(review(o, lambda p: "jag vet inte riktigt"))
        o.refresh_from_db()
        self.assertEqual(o.demand_score, 85)

    def test_json_embedded_in_prose_is_still_read(self):
        o = make(score=85)
        review(o, lambda p: 'Här kommer svaret:\n{"score": 10, "why": "över"}\nTack!')
        o.refresh_from_db()
        self.assertEqual(o.demand_score, 10)


class CacheKeyTests(TestCase):
    """
    Cache på titel ger noll träffar -- tågtitlar bär tågnummer och
    klockslag och är därför nästan unika (28 av 28 i en mätning).
    """

    def test_same_shape_different_numbers_share_key(self):
        a = make(score=85, title="Tåg 12111 08:29 är inställt från Motala")
        key_a = normalize_key(a)
        Opportunity.objects.all().delete()
        b = make(score=85, title="Tåg 99887 21:04 är inställt från Motala")
        self.assertEqual(key_a, normalize_key(b))

    def test_different_tier_does_not_share_key(self):
        a = make(score=85)
        key_a = normalize_key(a)
        Opportunity.objects.all().delete()
        b = make(score=85, severity_tier="vehicle_delayed")
        self.assertNotEqual(key_a, normalize_key(b))


class CacheTests(TestCase):
    def test_second_call_uses_cache_not_the_model(self):
        o = make(score=85)
        review(o, lambda p: '{"score": 15, "why": "vägarbete"}')

        calls = []
        def should_not_run(prompt):
            calls.append(prompt)
            return '{"score": 99}'

        o2 = make(score=85, title="Hållplats Elektravägen inställd pga vägarbete")
        review(o2, should_not_run)
        self.assertEqual(calls, [], "cachen ska ha svarat, ingen modell anropad")
