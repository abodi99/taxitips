"""
Tester för datalagret.

Tyngdpunkten ligger på push-invarianten. Den är inte en detalj: bryts den
får varje förare samma notis varje minut, och felet syns inte i någon logg
-- bara i telefonerna.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from core.models import Confidence, Opportunity, ScoringRule, SeverityTier
from core.repository import purge_old, upsert_opportunities, upsert_source_events


def opportunity_row(external_id="tvr:Mot:8780:x", **overrides):
    """En minimal men komplett rad, som pipelinen skulle producera den."""
    now = timezone.now()
    row = {
        "external_id": external_id,
        "kind": "transit",
        "mode": "train",
        "severity_tier": SeverityTier.LINE_PAUSED,
        "level": "high",
        "title": "Tåg 8780 00:04 är inställt från Motala C",
        "summary": "Avgången är inställd.",
        "lat": 58.5371,
        "lon": 15.0364,
        "h3_index": "",
        "places": '["Motala C"]',
        "region": "rail",
        "start_time": now,
        "end_time": now + timedelta(hours=1),
        "demand_score": 85,
        "confidence": Confidence.LOW,
        "reasons": '["allvarlig störning"]',
        "rule_id": "train.line_paused",
        "source_event_ids": "[]",
    }
    row.update(overrides)
    return row


class UpsertInvariantTests(TestCase):
    """
    notified_at skrivs bara av push-steget och måste överleva varje
    efterföljande skrivning av raden.
    """

    def test_notified_at_survives_upsert(self):
        upsert_opportunities([opportunity_row()])

        # Push-steget markerar tipset som notifierat.
        marked = timezone.now()
        Opportunity.objects.filter(external_id="tvr:Mot:8780:x").update(
            notified_at=marked
        )

        # Nästa pollcykel skriver samma tips igen, med ny poäng.
        upsert_opportunities([opportunity_row(demand_score=55)])

        row = Opportunity.objects.get(external_id="tvr:Mot:8780:x")
        self.assertEqual(row.demand_score, 55, "poängen ska uppdateras")
        self.assertIsNotNone(
            row.notified_at,
            "notified_at nollades -- varje förare skulle få samma notis igen",
        )

    def test_upsert_updates_instead_of_duplicating(self):
        upsert_opportunities([opportunity_row()])
        upsert_opportunities([opportunity_row(title="Ändrad titel")])
        self.assertEqual(Opportunity.objects.count(), 1)
        self.assertEqual(Opportunity.objects.first().title, "Ändrad titel")

    def test_computed_at_is_when_the_tip_first_appeared(self):
        upsert_opportunities([opportunity_row()])
        first = Opportunity.objects.get(external_id="tvr:Mot:8780:x")
        upsert_opportunities([opportunity_row(demand_score=40)])
        again = Opportunity.objects.get(external_id="tvr:Mot:8780:x")
        self.assertEqual(first.computed_at, again.computed_at)
        self.assertGreater(again.updated_at, first.updated_at)

    def test_empty_input_touches_nothing(self):
        self.assertEqual(upsert_opportunities([]), 0)
        self.assertEqual(upsert_source_events([]), {})


class SourceEventTests(TestCase):
    def test_returns_ids_so_tips_can_cite_their_source(self):
        ids = upsert_source_events(
            [
                {
                    "source": "trafikverket_rail",
                    "external_id": "tvr:Mot:8780:x",
                    "mode": "train",
                    "active_from": timezone.now(),
                    "active_to": None,
                    "raw": '{"header": "Inställt"}',
                    "lat": 58.5,
                    "lon": 15.0,
                }
            ]
        )
        self.assertIn("tvr:Mot:8780:x", ids)
        self.assertTrue(ids["tvr:Mot:8780:x"])


class PurgeTests(TestCase):
    """
    Retention utan Firestore: en delete på schema räcker.
    """

    def test_purge_removes_old_keeps_recent(self):
        now = timezone.now()
        upsert_opportunities(
            [
                opportunity_row("old", end_time=now - timedelta(days=10)),
                opportunity_row("recent", end_time=now - timedelta(days=1)),
            ]
        )
        result = purge_old(days=7)
        self.assertEqual(result["opportunities"], 1)
        remaining = list(Opportunity.objects.values_list("external_id", flat=True))
        self.assertEqual(remaining, ["recent"])


class ScoringRuleTests(TestCase):
    """
    Taken och golven som data. Att blanda ihop dem är precis det fel som
    ger alla 27 tågtips identiska 97 poäng idag.
    """

    def test_floor_raises_cap_limits(self):
        floor_rule = ScoringRule(tier=SeverityTier.LINE_PAUSED, floor=85)
        self.assertEqual(floor_rule.apply(70), 85, "golv ska höja")
        self.assertEqual(floor_rule.apply(97), 97, "golv ska inte sänka")

        cap_rule = ScoringRule(tier=SeverityTier.VEHICLE_CANCELLED, cap=55)
        self.assertEqual(cap_rule.apply(85), 55, "tak ska sänka")
        self.assertEqual(cap_rule.apply(40), 40, "tak ska inte höja")

    def test_score_stays_within_bounds(self):
        rule = ScoringRule(tier=SeverityTier.LINE_PAUSED, floor=120)
        self.assertEqual(rule.apply(50), 100, "aldrig över 100")
        rule = ScoringRule(tier=SeverityTier.IGNORE, cap=-5)
        self.assertEqual(rule.apply(50), 0, "aldrig under 0")
