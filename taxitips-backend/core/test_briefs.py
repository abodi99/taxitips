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
