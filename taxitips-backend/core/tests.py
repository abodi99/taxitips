"""
Tester för datalagret.

Tyngdpunkten ligger på push-invarianten. Den är inte en detalj: bryts den
får varje förare samma notis varje minut, och felet syns inte i någon logg
-- bara i telefonerna.
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from core.models import Confidence, Opportunity, ScoringRule, SeverityTier, SourceEvent
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
        "compensation_eligible": False,
        "compensation_amount_kr": None,
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


class UnchangedRowTests(TestCase):
    """En pollrunda utan ändringar skriver ingenting: updated_at står still och antalet är noll."""

    def test_unchanged_opportunity_is_not_rewritten(self):
        row = opportunity_row()
        self.assertEqual(upsert_opportunities([dict(row)]), 1)
        first = Opportunity.objects.get(external_id=row["external_id"])
        self.assertEqual(upsert_opportunities([dict(row)]), 0)
        again = Opportunity.objects.get(external_id=row["external_id"])
        self.assertEqual(again.updated_at, first.updated_at)

    def test_only_changed_rows_are_counted(self):
        row, other = opportunity_row(), opportunity_row("tvr:Mot:8781:x")
        upsert_opportunities([dict(row), dict(other)])
        self.assertEqual(upsert_opportunities([dict(row, demand_score=40), dict(other)]), 1)
        self.assertEqual(Opportunity.objects.get(external_id=row["external_id"]).demand_score, 40)

    def test_unchanged_source_event_still_returns_its_id(self):
        row = {
            "source": "sl", "external_id": "sl:1", "mode": "metro", "active_from": None,
            "active_to": None, "raw": '{"header": "Tunnelbanan stoppad"}', "lat": None, "lon": None,
        }
        first = upsert_source_events([dict(row)])
        self.assertEqual(upsert_source_events([dict(row)]), first)

    def test_changed_source_event_moves_fetched_at_and_unchanged_does_not(self):
        row = {
            "source": "smhi", "external_id": "smhi:Göteborg", "mode": "", "active_from": None,
            "active_to": None, "raw": '{"wind_gust_ms": 9.0}', "lat": None, "lon": None,
        }
        upsert_source_events([dict(row)])
        old = timezone.now() - timedelta(days=11)
        SourceEvent.objects.filter(external_id="smhi:Göteborg").update(fetched_at=old)
        upsert_source_events([dict(row)])
        self.assertEqual(SourceEvent.objects.get(external_id="smhi:Göteborg").fetched_at, old)
        upsert_source_events([dict(row, raw='{"wind_gust_ms": 16.3}')])
        self.assertGreater(SourceEvent.objects.get(external_id="smhi:Göteborg").fetched_at, old)


class PurgeBatchTests(TestCase):
    """Gallringen går i batchar och tar ändå allt som är äldre än gränsen."""

    def test_deletes_everything_older_across_several_batches(self):
        old = timezone.now() - timedelta(days=10)
        upsert_opportunities([
            opportunity_row(f"old:{i}", start_time=old, end_time=old) for i in range(7)
        ])
        upsert_opportunities([opportunity_row("new:1")])
        result = purge_old(days=7, batch_size=3)
        self.assertEqual(result["opportunities"], 7)
        self.assertEqual(list(Opportunity.objects.values_list("external_id", flat=True)), ["new:1"])

    def test_keeps_source_events_a_remaining_tip_cites(self):
        import json

        from core.models import SourceEvent

        old = timezone.now() - timedelta(days=10)
        ids = upsert_source_events([
            {
                "source": "sl", "external_id": f"sl:{i}", "mode": "bus", "active_from": old,
                "active_to": old, "raw": "{}", "lat": None, "lon": None,
            }
            for i in range(4)
        ])
        upsert_opportunities([opportunity_row("new:1", source_event_ids=json.dumps([ids["sl:0"]]))])
        result = purge_old(days=7, batch_size=2)
        self.assertEqual(result["source_events"], 3)
        self.assertEqual(list(SourceEvent.objects.values_list("external_id", flat=True)), ["sl:0"])


class AreaOnWriteTests(TestCase):
    """Varje tips får sitt län och sitt körområde när det skrivs, oavsett källa."""

    def test_coordinates_decide_the_county(self):
        upsert_opportunities([opportunity_row()])  # Motala
        tip = Opportunity.objects.get(external_id="tvr:Mot:8780:x")
        self.assertEqual(tip.county_code, "05")
        self.assertIn("05", tip.area_codes)

    def test_without_coordinates_the_market_decides(self):
        upsert_opportunities([opportunity_row("vt:1", lat=None, lon=None, region="vt")])
        tip = Opportunity.objects.get(external_id="vt:1")
        self.assertEqual((tip.county_code, tip.area_codes), ("14", ["14"]))

    def test_an_unplaceable_tip_has_no_area(self):
        upsert_opportunities([opportunity_row("rail:1", lat=None, lon=None, region="rail")])
        tip = Opportunity.objects.get(external_id="rail:1")
        self.assertEqual((tip.county_code, tip.area_codes), (None, []))


class CountyCatalogTests(TestCase):
    def test_every_county_is_selectable_and_says_what_is_missing(self):
        from core.coverage import county_catalog

        catalog = {c["code"]: c for c in county_catalog()}
        self.assertEqual(len(catalog), 21)
        self.assertIsNone(catalog["25"]["transit"])  # Norrbotten
        self.assertEqual(catalog["14"]["transit"], "Västtrafik")
