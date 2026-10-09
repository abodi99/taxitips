"""
Genkit läser det reglerna inte fick ut (core/places_ai.py), och insamlingen
bär läsningen vidare (core/ingest.py). Transporten är fejkad: inga nätanrop.
"""

from __future__ import annotations

import importlib
import json
from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.apps import apps
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from core import ai_client, places_ai, thresholds, tip_text
from core.ingest import assess, write
from core.models import AiCall, Opportunity, RegionCompensationRule, SeverityTier, StopArea
from core.repository import upsert_opportunities
from core.tests import opportunity_row
from core.tip_facts import TipFacts, sanitize

# En lördag mitt på dagen: ingen tidsomständighet blandar sig i raderna.
SATURDAY_NOON = datetime(2027, 1, 2, 12, 0, tzinfo=ZoneInfo("Europe/Stockholm"))

# Reglerna läser inte "Ropsten-Larsberg" (inget mellanslag kring strecket).
ROPSTEN = ("Alla LB inställt", "Inställd trafik Ropsten-Larsberg pga signalfel. Vi hänvisar till alternativa färdmedel.")


def alert(external_id: str, header: str, description: str, **overrides) -> dict:
    base = {
        "id": external_id, "header": header, "description": description,
        "cause": None, "effect": None, "areas": [], "routes": [], "stops": [], "url": None,
        "region": "sl", "active_from": SATURDAY_NOON, "active_to": timezone.now() + timedelta(hours=2),
        "mode_hint": "tram",
    }
    base.update(overrides)
    return base


def poll(*alerts):
    write("sl", assess(list(alerts)))


def fake(output: TipFacts | None = None, error: Exception | None = None):
    calls = []

    def transport(model, prompt, schema, timeout):
        calls.append(prompt)
        if error:
            raise error
        return (output or TipFacts()), 700, 120

    transport.calls = calls
    return transport


class SanitizeTests(SimpleTestCase):
    def test_only_what_the_text_says_survives(self):
        text = "Alla LB inställt\nInställd trafik Ropsten-Larsberg pga signalfel kl 16:05."
        clean = sanitize(TipFacts(
            lines=["Lidingöbanan", "LB"], stops=["Ropsten", "Gåshaga brygga", "larsberg"],
            from_station="Ropsten", to_station="Käppala", departure_clock="16:05",
            next_departure_clock="16:20", delay_minutes=12,
        ), text)
        self.assertEqual(clean["lines"], ["LB"])
        self.assertEqual(clean["stops"], ["Ropsten", "larsberg"])
        self.assertEqual((clean["from_station"], clean["to_station"]), ("Ropsten", ""))
        self.assertEqual((clean["departure_clock"], clean["next_departure_clock"]), ("16:05", ""))
        self.assertEqual(clean["delay_minutes"], 0)

    def test_a_dotted_clock_in_the_text_counts(self):
        clean = sanitize(TipFacts(departure_clock="17:42"), "försening registrerades klockan 17.42")
        self.assertEqual(clean["departure_clock"], "17:42")

    def test_garbage_becomes_empty_facts(self):
        clean = sanitize({"event_type": 5, "stops": "inte en lista"}, "text")
        self.assertEqual(clean["stops"], [])


@override_settings(TAXITIPS_AI="on")
class ReadPlacesTests(TestCase):
    def setUp(self):
        patcher = patch.object(ai_client, "api_key", return_value="test-key")
        patcher.start()
        self.addCleanup(patcher.stop)
        tip_text.reset_registry()
        self.addCleanup(tip_text.reset_registry)

    def three_rows_of_the_same_message(self):
        poll(*(alert(f"sl:{i}", *ROPSTEN) for i in range(3)))
        return list(Opportunity.objects.filter(external_id__startswith="sl:").order_by("external_id"))

    def test_one_call_per_text_not_per_row(self):
        rows = self.three_rows_of_the_same_message()
        self.assertEqual(len({o.rule_key for o in rows}), 1)
        self.assertEqual({o.station for o in rows}, {""})
        transport = fake(TipFacts(
            event_type="whole_line_stop", lines=["Lidingöbanan"], stops=["Ropsten", "Larsberg", "Gåshaga brygga"],
            from_station="Ropsten", to_station="Larsberg",
        ))
        with patch.object(ai_client, "transport", transport):
            stats = places_ai.run()
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual((stats["texts"], stats["tips"]), (1, 3))
        for o in Opportunity.objects.filter(external_id__startswith="sl:"):
            self.assertEqual(o.station, "Ropsten")
            self.assertEqual(o.places, ["Ropsten", "Larsberg"])
            # Gåshaga brygga och Lidingöbanan står inte i texten: bort.
            self.assertEqual(o.ai_facts["stops"], ["Ropsten", "Larsberg"])
            self.assertEqual(o.ai_facts["lines"], [])
            self.assertEqual(o.ai_rule_key, o.rule_key)
        self.assertEqual(AiCall.objects.filter(purpose="places", ok=True).count(), 1)

    def test_the_reading_survives_the_next_poll_without_a_new_call(self):
        self.three_rows_of_the_same_message()
        with patch.object(ai_client, "transport", fake(TipFacts(stops=["Ropsten"]))):
            places_ai.run()
        # Nästa pollrunda skriver om raderna från reglerna ...
        self.three_rows_of_the_same_message()
        for o in Opportunity.objects.filter(external_id__startswith="sl:"):
            self.assertEqual(o.station, "Ropsten")
            self.assertEqual(o.places, ["Ropsten"])
        # ... och en ny rad med samma text får läsningen utan anrop.
        poll(alert("sl:ny", *ROPSTEN))
        self.assertEqual(Opportunity.objects.get(external_id="sl:ny").station, "Ropsten")
        transport = fake(TipFacts(stops=["Ropsten"]))
        with patch.object(ai_client, "transport", transport):
            self.assertEqual(places_ai.run()["texts"], 0)
        self.assertEqual(transport.calls, [])

    def test_the_reading_gives_a_registry_coordinate_never_a_model_one(self):
        StopArea.objects.create(gid="sl:ropsten", operator="sl", name="Ropsten", lat=59.357, lon=18.102)
        self.three_rows_of_the_same_message()
        before = Opportunity.objects.get(external_id="sl:0")
        self.assertNotEqual((before.lat, before.lon), (59.357, 18.102))
        with patch.object(ai_client, "transport", fake(TipFacts(stops=["Ropsten"]))):
            places_ai.run()
        self.three_rows_of_the_same_message()
        after = Opportunity.objects.get(external_id="sl:0")
        self.assertEqual((after.lat, after.lon), (59.357, 18.102))

    def test_a_changed_text_is_read_again(self):
        self.three_rows_of_the_same_message()
        with patch.object(ai_client, "transport", fake(TipFacts(stops=["Ropsten"]))):
            places_ai.run()
        poll(*(alert(f"sl:{i}", ROPSTEN[0], "Inställd trafik Ropsten-Baggeby pga signalfel.") for i in range(3)))
        transport = fake(TipFacts(stops=["Baggeby"]))
        with patch.object(ai_client, "transport", transport):
            places_ai.run()
        self.assertEqual(len(transport.calls), 1)

    def test_tips_the_rules_read_fully_are_never_sent(self):
        poll(alert("sl:tumba", "Förseningar",
                   "Förseningar upp till 10 minuter för buss linje 725 från Tumba station 16:58 mot Söderby park "
                   "på grund av framkomlighetsproblem.", mode_hint="bus"))
        o = Opportunity.objects.get(external_id="sl:tumba")
        self.assertEqual((o.line, o.station), ("Buss 725", "Tumba station"))
        self.assertEqual(places_ai.pick(), [])

    def test_stronger_tips_first(self):
        now = timezone.now()
        upsert_opportunities([
            opportunity_row("a", region="sl", rule_key="a" * 40, level="low", confidence="medium",
                            severity_tier="vehicle_delayed", computed_at=now),
            opportunity_row("b", region="sl", rule_key="b" * 40, level="medium", confidence="medium",
                            severity_tier="vehicle_cancelled", computed_at=now - timedelta(hours=1)),
        ])
        self.assertEqual([key for key, _o in places_ai.pick(limit=1)], ["b" * 40])

    def test_a_failed_text_waits_out_its_backoff(self):
        self.three_rows_of_the_same_message()
        with patch.object(ai_client, "transport", fake(error=RuntimeError("429 RESOURCE_EXHAUSTED"))):
            stats = places_ai.run()
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(places_ai.pick(), [])

    def test_the_minute_cap_stops_the_run(self):
        # En pollrunda: en rad som saknas i nästa runda avslutas av write().
        poll(alert("sl:0", *ROPSTEN), alert("sl:x", ROPSTEN[0], "Inställd trafik Ropsten-Baggeby pga signalfel."))
        transport = fake(TipFacts(stops=["Ropsten"]))
        cap = thresholds.AI_GATE_RESERVED_PER_MINUTE + 1
        with patch.object(thresholds, "AI_MAX_CALLS_PER_MINUTE", cap), patch.object(ai_client, "transport", transport):
            stats = places_ai.run()
        self.assertEqual(len(transport.calls), 1)
        self.assertIn("minuttaket", stats["skipped"])

    @override_settings(TAXITIPS_AI="off")
    def test_switched_off_means_rules_only(self):
        self.three_rows_of_the_same_message()
        transport = fake()
        with patch.object(ai_client, "transport", transport):
            stats = places_ai.run()
        self.assertEqual(transport.calls, [])
        self.assertIn("avstängd", stats["skipped"])

    def test_an_uncertain_tip_is_scored_by_the_rules_and_capped(self):
        upsert_opportunities([opportunity_row(
            "sl:oklar", region="sl", mode="unknown", rule_key="c" * 40, confidence="low", level="low",
            severity_tier="disruption_unclassified", demand_score=30, title=ROPSTEN[0], summary=ROPSTEN[1],
        )])
        with patch.object(ai_client, "transport", fake(TipFacts(event_type="whole_line_stop", alternative="none",
                                                                 stops=["Ropsten"]))):
            places_ai.run()
        o = Opportunity.objects.get(external_id="sl:oklar")
        self.assertEqual(o.demand_score, thresholds.AI_RAISE_CAP)
        self.assertNotEqual(o.level, "high")
        self.assertIsNotNone(o.ai_adjusted_at)  # en AI-höjning väcker aldrig ensam en telefon
        self.assertEqual(o.station, "Ropsten")

    def test_review_reuses_a_reading_of_the_same_text(self):
        from core.genkit import review

        self.three_rows_of_the_same_message()
        with patch.object(ai_client, "transport", fake(TipFacts(event_type="whole_line_stop", stops=["Ropsten"]))):
            places_ai.run()
        o = Opportunity.objects.get(external_id="sl:0")
        called = []
        review(o, lambda prompt: called.append(prompt) or "{}", facts=True)
        self.assertEqual(called, [])


class FactorTests(TestCase):
    """Varje tips bär minst en rad "Därför", med trafikbolagets egna siffror."""

    def written(self, header, description, **overrides):
        poll(alert("sl:f", header, description, **overrides))
        return Opportunity.objects.get(external_id="sl:f")

    def test_departure_and_delay_from_the_text(self):
        o = self.written("Förseningar", "Förseningar upp till 10 minuter för buss linje 725 från Tumba station 16:58 "
                                        "mot Söderby park på grund av framkomlighetsproblem.", mode_hint="bus")
        texts = [f["text"] for f in o.factors]
        self.assertEqual(texts[:2], ["Avgång 16:58 från Tumba station", "Bussen är upp till 10 min försenad"])
        self.assertNotIn("Bussen är försenad", texts)
        self.assertEqual((o.line, o.station, o.destination), ("Buss 725", "Tumba station", "Söderby park"))
        self.assertEqual(o.places, ["Tumba station", "Söderby park"])

    def test_a_cancelled_departure_says_so(self):
        o = self.written("Inställd avgång", "Pågatåg 1612 från Malmö C kl 07:12 mot Helsingborg C är inställt.",
                         region="skane", mode_hint="train")
        self.assertIn("Avgång 07:12 från Malmö C är inställd", [f["text"] for f in o.factors])

    def test_other_tips_say_why_they_are_other(self):
        o = self.written("Avstängd hiss vid Råcksta", "Hissen vid Råcksta är avstängd på grund av tekniskt fel.")
        self.assertEqual(o.severity_tier, SeverityTier.IGNORE)
        self.assertEqual(len(o.factors), 1)
        self.assertEqual(o.factors[0]["sign"], "-")

    def test_no_text_tip_is_left_without_a_reason(self):
        from pathlib import Path

        fixtures = Path(__file__).resolve().parent / "fixtures"
        cases = []
        for name in ("golden_tips.jsonl", "golden_extraction.jsonl"):
            for line in (fixtures / name).read_text(encoding="utf-8").splitlines():
                cases.append(json.loads(line))
        alerts = [
            alert(f"g:{c['id']}", c["title"], c["summary"], region=c["region"], mode_hint=None,
                  route_label=c.get("route_label"))
            for c in cases
        ]
        write("golden", assess(alerts))
        empty = Opportunity.objects.filter(external_id__startswith="g:", factors=[])
        self.assertEqual(list(empty.values_list("title", flat=True)), [])

    def test_every_number_in_a_reason_is_in_the_text(self):
        import re

        o = self.written("Ny avgångstid", "Avgången från Karolinska sjukhuset norra kl 16:01 till Sollentuna station "
                                          "är cirka 9 minuter försenad pga framkomlighetsproblem.", mode_hint="bus")
        source = f"{o.title} {o.summary}"
        for factor in o.factors:
            for number in re.findall(r"\d+", factor["text"]):
                self.assertIn(number, source, factor["text"])


class CompensationSourceTests(TestCase):
    def test_the_migration_fills_names_and_missing_links_from_the_doc(self):
        RegionCompensationRule.objects.create(region="sl", taxi_cap_kr=1480, source_url="")
        RegionCompensationRule.objects.create(region="skane", taxi_cap_kr=2960, source_url="https://egen.example/")
        RegionCompensationRule.objects.create(region="halland", taxi_cap_kr=1500, source_url="")
        migration = importlib.import_module("core.migrations.0034_text_facts_and_compensation_source")
        migration.fill_sources(apps, None)
        sl = RegionCompensationRule.objects.get(region="sl")
        self.assertEqual((sl.source_name, sl.source_url), ("SL", "https://sl.se/kundservice/forseningsersattning"))
        # En länk som redan finns skrivs inte över; en region utan källa i doc:en lämnas.
        self.assertEqual(RegionCompensationRule.objects.get(region="skane").source_url, "https://egen.example/")
        self.assertEqual(RegionCompensationRule.objects.get(region="halland").source_name, "")

    def test_the_rail_product_decides_whose_rules(self):
        from core.compensation import rule_region_for

        self.assertEqual(rule_region_for(Opportunity(region="rail", line="Pågatågen 1612")), "skane")
        self.assertEqual(rule_region_for(Opportunity(region="rail", line="Öresundståg 1039", county_code="14")), "vt")
        self.assertIsNone(rule_region_for(Opportunity(region="rail", line="SJ 537")))
        self.assertEqual(rule_region_for(Opportunity(region="otraf")), "otraf")
        self.assertIsNone(rule_region_for(Opportunity(region=None)))


class ThresholdEnvTests(SimpleTestCase):
    def test_caps_can_be_raised_from_the_environment(self):
        with patch.dict("os.environ", {"AI_MAX_CALLS_PER_MINUTE": "300"}):
            self.assertEqual(thresholds._env_int("AI_MAX_CALLS_PER_MINUTE", 12), 300)
        with patch.dict("os.environ", {"AI_MAX_CALLS_PER_MINUTE": "inte ett tal"}):
            self.assertEqual(thresholds._env_int("AI_MAX_CALLS_PER_MINUTE", 12), 12)
        with patch.dict("os.environ", {"AI_MAX_CALLS_PER_MINUTE": "0"}):
            self.assertEqual(thresholds._env_int("AI_MAX_CALLS_PER_MINUTE", 12), 12)
        self.assertLess(thresholds.AI_MONTHLY_BUDGET_KR, 500)


class MeasureCommandTests(TestCase):
    def test_it_prints_a_table_per_source(self):
        from io import StringIO

        from django.core.management import call_command

        poll(alert("sl:m", "Förseningar", "Förseningar upp till 10 minuter för buss linje 725 från Tumba station "
                                          "16:58 mot Söderby park.", mode_hint="bus"))
        out = StringIO()
        call_command("measure_places", "--hours", "24", "--replay", stdout=out)
        text = out.getvalue()
        self.assertIn("I databasen", text)
        self.assertIn("Dagens regler", text)
        self.assertRegex(text, r"\n  sl\s+1\s")


class RailLineTests(SimpleTestCase):
    def test_product_and_train_number_as_on_the_board(self):
        from types import SimpleNamespace

        from core.management.commands.poll_rail import rail_line

        def a(**kw):
            return SimpleNamespace(**{"product": "", "information_owner": "", "operator": "", "train": "", **kw})

        self.assertEqual(rail_line(a(product="Pågatågen", train="1612")), "Pågatågen 1612")
        self.assertEqual(rail_line(a(operator="SJ", train="537")), "SJ 537")
        self.assertEqual(rail_line(a(train="8780")), "Tåg 8780")


class ReadPlacesCommandTests(TestCase):
    def test_dry_run_calls_nothing(self):
        from io import StringIO

        from django.core.management import call_command

        poll(*(alert(f"sl:{i}", *ROPSTEN) for i in range(3)))
        out = StringIO()
        transport = fake()
        with patch.object(ai_client, "transport", transport):
            call_command("read_places", "--dry-run", stdout=out)
        self.assertIn("1 texter skulle läsas", out.getvalue())
        self.assertEqual(transport.calls, [])

    def test_beat_runs_it(self):
        from django.conf import settings

        self.assertEqual(settings.CELERY_BEAT_SCHEDULE["read-places"]["task"], "core.tasks.read_places_task")
