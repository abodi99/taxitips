"""Kvalitetsgranskningen av tipsen (core/tip_audit.py) och det gemensamma betyget."""

from __future__ import annotations

from datetime import timedelta

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from core import notify, thresholds, tip_audit
from core.models import Opportunity, SourceEvent


class StoredLevelTests(SimpleTestCase):
    def test_reserve_rule_only_lets_a_stranding_tier_be_strong(self):
        cases = [
            ("line_paused", 85, False, "high"), ("vehicle_cancelled", 61, False, "medium"),
            ("vehicle_cancelled", 34, False, "low"), ("vehicle_cancelled", 60, True, "low"),
            ("disruption_unclassified", 85, False, "medium"), ("arrival_wave", 80, False, "medium"),
        ]
        for tier, score, alt, expected in cases:
            self.assertEqual(thresholds.stored_level(tier, score, alt), expected, (tier, score, alt))

    def test_replacement_traffic_is_never_high(self):
        self.assertEqual(thresholds.stored_level("vehicle_cancelled", 90, True), "low")


class AuditTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        self.event = SourceEvent.objects.create(
            source="test", external_id="ev:1", raw={}, active_to=self.now + timedelta(hours=1),
        ) if hasattr(SourceEvent, "active_to") else None

    def tip(self, ext, **kw):
        base = dict(
            external_id=ext, kind="transit", mode="train", severity_tier="line_paused",
            title="Tåg inställt", summary="Avgången 06:02 är inställd. Nästa avgång går 06:13.",
            demand_score=85, confidence="high", reasons=["inställd avgång"], rule_id="train.line_paused",
            source_event_ids=[str(self.event.id)] if self.event else ["x"],
            start_time=self.now - timedelta(minutes=10), end_time=self.now + timedelta(minutes=50),
        )
        base.update(kw)
        base.setdefault(
            "level", thresholds.stored_level(base["severity_tier"], base["demand_score"], base.get("has_alternative", False)),
        )
        return Opportunity.objects.create(**base)

    def counts(self):
        return {c["id"]: c["count"] for c in tip_audit.audit(now=self.now)["checks"]}

    def test_a_clean_tip_passes(self):
        self.tip("ok:1")
        report = tip_audit.audit(now=self.now)
        self.assertTrue(report["ok"], report)
        self.assertEqual(sum(c["count"] for c in report["checks"] if c["severity"] != "info"), 0)

    def test_finds_the_known_problems(self):
        self.tip("road:1", kind="road", mode="road", severity_tier="road_accident_or_closure",
                 demand_score=27, rule_id="road.accident")
        self.tip("frozen:1", summary="Nästa avgång går om 20 min.")
        self.tip("noexp:1", rule_id="", reasons=[])
        self.tip("lvl:1", level="high", severity_tier="vehicle_cancelled", demand_score=60, has_alternative=True)
        self.tip("dep:1", next_departure_at=self.now - timedelta(minutes=10))
        self.tip("alt:1", has_alternative=True, notified_at=self.now - timedelta(minutes=5))
        c = self.counts()
        self.assertEqual(c["road_over_cap"], 1)
        self.assertEqual(c["frozen_relative_time"], 1)
        self.assertEqual(c["missing_explanation"], 1)
        self.assertEqual(c["level_mismatch"], 1)
        self.assertEqual(c["shows_departed"], 1)
        self.assertEqual(c["notified_with_alternative"], 1)
        self.assertFalse(tip_audit.audit(now=self.now)["ok"])

    def test_expired_and_suppressed_tips_are_not_audited(self):
        self.tip("old:1", summary="om 5 min", end_time=self.now - timedelta(minutes=1))
        self.tip("hidden:1", summary="om 5 min", suppressed_at=self.now)
        self.assertEqual(self.counts()["frozen_relative_time"], 0)

    def test_notification_snapshot_uses_the_feed_rule(self):
        o = self.tip("snap:1", level="high", severity_tier="vehicle_cancelled",
                     demand_score=60, has_alternative=True)
        self.assertEqual(notify.snapshot_of(o)["level"], "low")


class ExplainGradeTests(SimpleTestCase):
    def test_the_first_reason_for_is_the_because(self):
        g = thresholds.explain_grade("high", [
            {"text": "Sista avgången härifrån", "sign": "+"},
            {"text": "Natt – nästan inga andra sätt att ta sig hem", "sign": "+"},
        ])
        self.assertEqual((g["level"], g["label"]), ("high", "Stark"))
        self.assertEqual(g["because"], "Sista avgången härifrån")
        self.assertEqual(len(g["steps"]), 2)

    def test_only_reasons_against_still_explains(self):
        g = thresholds.explain_grade("low", [{"text": "Nästa tåg går 5 min senare", "sign": "-"}])
        self.assertEqual(g["label"], "Svag")
        self.assertEqual(g["because"], "Nästa tåg går 5 min senare")
        self.assertFalse(g["steps"][0]["ok"])

    def test_no_reasons_is_not_an_error(self):
        self.assertEqual(thresholds.explain_grade("medium", None)["because"], "")
