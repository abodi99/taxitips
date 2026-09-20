"""
Tester för språkmodellsgranskningen.

confidence=low → omklassning (får höja/sänka + byta tier).
confidence≠low / reclassify=False → bara sänka.
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


class ReclassifyTests(TestCase):
    def test_model_can_lower(self):
        o = make(score=85)
        review(o, lambda p: '{"score": 20, "severity_tier": "disruption_unclassified", "stranded": false, "why": "vägarbete"}')
        o.refresh_from_db()
        self.assertEqual(o.demand_score, 20)
        self.assertEqual(o.severity_tier, "disruption_unclassified")

    def test_low_confidence_may_raise_and_re_tier(self):
        # Fritexten sa "riskerar försening" men regex satte cancelled/60.
        # Omklassning ska få sänka tier och poäng -- eller höja om tipset
        # var undervärderat.
        o = make(
            score=25,
            title="Linje 4 stoppad helt -- ingen trafik",
            severity_tier="vehicle_delayed",
        )
        review(
            o,
            lambda p: (
                '{"score": 80, "severity_tier": "line_paused", '
                '"stranded": true, "has_alternative": false, '
                '"why": "hela linjen stoppad"}'
            ),
        )
        o.refresh_from_db()
        self.assertEqual(o.demand_score, 80)
        self.assertEqual(o.severity_tier, "line_paused")
        self.assertEqual(o.confidence, "medium")

    def test_dampen_mode_cannot_raise(self):
        o = make(score=40)
        review(
            o,
            lambda p: '{"score": 99, "severity_tier": "line_paused", "stranded": true, "why": "allvarligt"}',
            reclassify=False,
        )
        o.refresh_from_db()
        self.assertEqual(o.demand_score, 40, "dämpning får aldrig höja")

    def test_guardrail_dampen_in_model_save(self):
        o = make(score=30)
        a = RailAssessment(
            opportunity=o, cache_key="x", rule_score=30, model_score=95,
            final_score=95,
        )
        a.save()
        self.assertEqual(a.final_score, 30)

    def test_reclassify_flag_allows_raise_in_model_save(self):
        o = make(score=30)
        a = RailAssessment(
            opportunity=o, cache_key="y", rule_score=30, model_score=80,
            final_score=80,
        )
        a._allow_reclassify = True
        a.save()
        self.assertEqual(a.final_score, 80)


class FailureTests(TestCase):
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
        review(o, lambda p: 'Här kommer svaret:\n{"score": 10, "severity_tier": "road_work", "why": "över"}\nTack!')
        o.refresh_from_db()
        self.assertEqual(o.demand_score, 10)


class CacheKeyTests(TestCase):
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
        review(o, lambda p: '{"score": 15, "severity_tier": "road_work", "why": "vägarbete"}')

        calls = []
        def should_not_run(prompt):
            calls.append(prompt)
            return '{"score": 99}'

        o2 = make(score=85, title="Hållplats Elektravägen inställd pga vägarbete")
        review(o2, should_not_run)
        self.assertEqual(calls, [], "cachen ska ha svarat, ingen modell anropad")

    def test_bypass_cache_calls_model(self):
        o = make(score=85)
        review(o, lambda p: '{"score": 15, "why": "vägarbete"}')
        calls = []
        def track(prompt):
            calls.append(prompt)
            return '{"score": 12, "severity_tier": "road_work", "why": "igen"}'
        review(o, track, bypass_cache=True)
        self.assertEqual(len(calls), 1)


class AiNeverSolePushTests(TestCase):
    """
    Modellen får omklassa ett osäkert tips, men aldrig ensam väcka en telefon.
    Utan spärren kunde en höjning till line_paused skickas inom 30 s, innan nästa
    pollrunda skrev tillbaka regelvärdena.
    """

    RAISE = '{"score": 82, "severity_tier": "line_paused", "stranded": true, "has_alternative": false, "why": "hela linjen"}'

    def test_a_raise_is_marked_and_never_pushed(self):
        from core import notify

        o = make(score=30, severity_tier="disruption_unclassified")
        review(o, lambda prompt: self.RAISE)
        o.refresh_from_db()
        self.assertIsNotNone(o.ai_adjusted_at)
        self.assertEqual(o.severity_tier, "line_paused")
        self.assertEqual(notify.decide({"counties": ["05"]}, o).reason, "ai_only")
        self.assertNotIn(o, notify.candidates())

    def test_lowering_is_not_marked(self):
        o = make(score=85)
        review(o, lambda prompt: '{"score": 20, "severity_tier": "line_paused", "stranded": false, "has_alternative": null, "why": "ersättningsbuss"}')
        o.refresh_from_db()
        self.assertIsNone(o.ai_adjusted_at)

    def test_the_next_pipeline_write_restores_the_rule_and_clears_the_mark(self):
        o = make(score=30, severity_tier="disruption_unclassified")
        review(o, lambda prompt: self.RAISE)
        make(score=30, severity_tier="disruption_unclassified")
        o.refresh_from_db()
        self.assertIsNone(o.ai_adjusted_at)
        self.assertEqual((o.demand_score, o.severity_tier), (30, "disruption_unclassified"))

    def test_the_prompt_carries_no_driver_company_or_position(self):
        from core.genkit import _prompt_for

        prompt = _prompt_for(make(score=30)).lower()
        for word in ("device", "token", "company", "bolag", "notify_prefs", "lat=", "lon="):
            self.assertNotIn(word, prompt)
