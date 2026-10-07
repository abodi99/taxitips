"""
Förarbeskedet (core/briefs.py): en rad ur tipsets egna fält, och aldrig en
siffra som inte finns i underlaget. Transporten är utbytt -- inget nät.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone as dt_tz
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from core import ai_client, briefs, notify
from core.models import AiCall, Opportunity
from core.test_notify import opportunity


def herrljunga(**overrides):
    fields = dict(
        title="Västtågen 13871 11:33 är inställt från Herrljunga C",
        summary="Tåget är inställt.",
        places=["Herrljunga C"], level="high", demand_score=81,
        departure_at=datetime(2026, 10, 4, 9, 33, tzinfo=dt_tz.utc),  # 11:33 svensk tid
        next_departure_at=datetime(2026, 10, 4, 11, 33, tzinfo=dt_tz.utc),  # 13:33
        start_time=timezone.now() - timedelta(minutes=5),
    )
    fields.update(overrides)
    return opportunity(**fields)


class ValidTests(TestCase):
    def test_numbers_must_exist_in_the_source(self):
        o = herrljunga()
        source = briefs.source_text(o)
        self.assertIn("Nästa avgång: 13:33", source)
        self.assertEqual(
            briefs.valid("Västtåg inställt Herrljunga C 11:33 – nästa tåg 13:33", source),
            "Västtåg inställt Herrljunga C 11:33 – nästa tåg 13:33",
        )
        # 13:45 står ingenstans: hellre inget besked än en påhittad avgång.
        self.assertIsNone(briefs.valid("Inställt 11:33, nästa 13:45", source))

    def test_too_long_or_empty_is_dropped(self):
        source = briefs.source_text(herrljunga())
        self.assertIsNone(briefs.valid("x" * (briefs.BRIEF_MAX_CHARS + 1), source))
        self.assertIsNone(briefs.valid("  ", source))
        self.assertEqual(briefs.valid('"Inställt i Herrljunga"\n', source), "Inställt i Herrljunga")

    def test_a_brief_is_shown_only_for_the_tip_it_was_written_for(self):
        o = herrljunga()
        Opportunity.objects.filter(pk=o.pk).update(brief="Inställt i Herrljunga", brief_key=briefs.key_for(o))
        o.refresh_from_db()
        self.assertEqual(briefs.current_brief(o), "Inställt i Herrljunga")
        o.next_departure_at = o.next_departure_at + timedelta(minutes=30)
        self.assertIsNone(briefs.current_brief(o))


@override_settings(TAXITIPS_AI="on")
class RunTests(TestCase):
    def setUp(self):
        patcher = patch.object(ai_client, "api_key", return_value="test-key")
        patcher.start()
        self.addCleanup(patcher.stop)

    def answer(self, text):
        self.prompts = []

        def transport(model, prompt, schema, timeout):
            self.prompts.append(prompt)
            return schema(text=text), 400, 30

        return patch.object(ai_client, "transport", transport)

    def test_writes_a_valid_brief_once(self):
        o = herrljunga()
        with self.answer("Västtåg inställt Herrljunga C 11:33 – nästa tåg 13:33"):
            self.assertEqual(briefs.run()["written"], 1)
            # Samma tips igen: redan skrivet, inget nytt anrop.
            self.assertEqual(dict(briefs.run()), {})
        o.refresh_from_db()
        self.assertEqual(briefs.current_brief(o), "Västtåg inställt Herrljunga C 11:33 – nästa tåg 13:33")
        self.assertEqual(AiCall.objects.get().purpose, "brief")
        self.assertIn("Nästa avgång: 13:33", self.prompts[0])

    def test_a_rejected_brief_is_not_retried_until_the_tip_changes(self):
        o = herrljunga()
        with self.answer("Nästa tåg 14:10"):
            self.assertEqual(briefs.run()["rejected"], 1)
            self.assertEqual(dict(briefs.run()), {})
        o.refresh_from_db()
        self.assertIsNone(o.brief)

    def test_weak_ignored_and_road_tips_get_no_brief(self):
        herrljunga(level="low", external_id="test:low")
        herrljunga(severity_tier="ignore", external_id="test:ignore")
        herrljunga(kind="road", external_id="test:road")
        with self.answer("Något"):
            self.assertEqual(dict(briefs.run()), {})

    def test_only_tips_that_can_wake_a_phone_get_a_brief(self):
        """
        7 854 anrop på fyra dygn (2026-10-07) för medel-tips som ingen notis
        någonsin bar. Beskedet finns för notisen; listan klarar sig utan.
        """
        herrljunga(level="medium", demand_score=55, external_id="test:medium")
        herrljunga(has_alternative=True, alternative_note="Buss ersätter", external_id="test:alt")
        herrljunga(severity_tier="line_delayed", external_id="test:delayed")
        herrljunga(notified_at=timezone.now(), external_id="test:already")
        with self.answer("Något"):
            self.assertEqual(dict(briefs.run()), {})
        wanted = herrljunga(external_id="test:wanted")
        with self.answer("Västtåg inställt Herrljunga C 11:33 – nästa tåg 13:33"):
            self.assertEqual(briefs.run()["written"], 1)
        wanted.refresh_from_db()
        self.assertIsNotNone(wanted.brief)

    def test_a_failed_call_backs_off_instead_of_retrying_every_run(self):
        """6,34 försök per tips, som mest 133: ett fel lämnade inget spår på tipset."""
        o = herrljunga()

        def failing(model, prompt, schema, timeout):
            raise RuntimeError("429")

        with patch.object(ai_client, "transport", failing):
            self.assertEqual(briefs.run()["failed"], 1)
            # Direkt igen: tipset väntar ut sin backoff, inget nytt anrop.
            self.assertEqual(dict(briefs.run()), {})
        self.assertEqual(AiCall.objects.filter(subject=o.external_id).count(), 1)
        # Backoffen har gått ut: ett nytt försök, och det lyckas.
        AiCall.objects.update(created_at=timezone.now() - timedelta(minutes=11))
        with self.answer("Västtåg inställt Herrljunga C 11:33 – nästa tåg 13:33"):
            self.assertEqual(briefs.run()["written"], 1)

    def test_after_repeated_failures_the_tip_is_given_up(self):
        o = herrljunga()
        for i in range(4):
            AiCall.objects.create(
                purpose="brief", model="x", ok=False, subject=o.external_id, error="x",
            )
        AiCall.objects.update(created_at=timezone.now() - timedelta(hours=3))
        with self.answer("Något"):
            self.assertEqual(dict(briefs.run()), {})

    def test_facts_from_the_review_feed_the_brief_but_only_verified_numbers(self):
        o = herrljunga(summary="Tåget är inställt på grund av signalfel. Nästa tåg går 13:33.")
        Opportunity.objects.filter(pk=o.pk).update(ai_facts={
            "cause": "signalfel", "next_departure_clock": "13:33",
            "departure_clock": "11:45",  # står inte i texten: läsfel, ska inte med
            "why": "Tåget är inställt.",
        })
        o.refresh_from_db()
        source = briefs.source_text(o)
        self.assertIn("Orsak: signalfel", source)
        self.assertIn("Nästa avgång enligt texten: 13:33", source)
        self.assertNotIn("11:45", source)


@override_settings(TAXITIPS_AI="on")
class EnsureTests(TestCase):
    """Beskedet i pushcykeln: skrivs för tipsen på väg ut, väntar aldrig på modellen."""

    def setUp(self):
        patcher = patch.object(ai_client, "api_key", return_value="test-key")
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_writes_for_the_rows_about_to_go_out_and_updates_them_in_place(self):
        o = herrljunga()

        def transport(model, prompt, schema, timeout):
            self.assertEqual(timeout, briefs.thresholds.AI_BRIEF_TIMEOUT_S)
            return schema(text="Västtåg inställt Herrljunga C 11:33 – nästa tåg 13:33"), 400, 30

        with patch.object(ai_client, "transport", transport):
            counts = briefs.ensure([o])
        self.assertEqual(dict(counts), {"written": 1})
        # Objektet i minnet bär raden: köandet läser det utan ny databasrunda.
        self.assertEqual(briefs.current_brief(o), "Västtåg inställt Herrljunga C 11:33 – nästa tåg 13:33")

    def test_the_cycle_cap_defers_the_rest(self):
        rows = [herrljunga(external_id=f"test:{i}") for i in range(3)]
        with patch.object(ai_client, "transport", lambda m, p, s, t: (s(text="Inställt i Herrljunga"), 1, 1)):
            counts = briefs.ensure(rows, max_calls=2)
        self.assertEqual(dict(counts), {"written": 2, "deferred": 1})

    def test_a_failure_is_fail_open_and_counted(self):
        o = herrljunga()

        def failing(model, prompt, schema, timeout):
            raise RuntimeError("nätet")

        with patch.object(ai_client, "transport", failing):
            self.assertEqual(dict(briefs.ensure([o])), {"failed": 1})
            self.assertEqual(dict(briefs.ensure([o])), {"backoff": 1})

    @override_settings(TAXITIPS_AI="off")
    def test_off_switch_means_no_call_and_no_wait(self):
        self.assertEqual(dict(briefs.ensure([herrljunga()])), {"unavailable": 1})

    @override_settings(TAXITIPS_AI="off")
    def test_nothing_happens_when_ai_is_off(self):
        herrljunga()
        self.assertEqual(briefs.run()["skipped"], 1)

    def test_the_push_reads_the_brief_when_it_exists(self):
        o = herrljunga()
        with self.answer("Västtåg inställt Herrljunga C 11:33 – nästa tåg 13:33"):
            briefs.run()
        o.refresh_from_db()
        body = notify.push_body(o)
        self.assertTrue(body.startswith("Västtåg inställt Herrljunga C 11:33"))
        # Nästa avgång står redan i beskedet: inte två gånger på låsskärmen.
        self.assertEqual(body.count("13:33"), 1)
