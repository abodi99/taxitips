"""
Position och tokens: aldrig i URL:en från appen, aldrig i en loggrad.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.test import RequestFactory, SimpleTestCase

from core.api import position_from
from core.log_filters import RedactFilter, redact
from core.test_api import DEVICE_TOKEN, ApiTestCase, opportunity


class PositionTests(SimpleTestCase):
    def test_the_header_is_read_and_rounded_to_about_a_kilometre(self):
        request = RequestFactory().get("/api/alerts", headers={"X-TT-Position": "55.604981,13.003822"})
        self.assertEqual(position_from(request), (55.6, 13.0))

    def test_query_parameters_still_work_for_older_apps(self):
        request = RequestFactory().get("/api/alerts", {"lat": "59.3293", "lon": "18.0686"})
        self.assertEqual(position_from(request), (59.33, 18.07))

    def test_nonsense_is_no_position(self):
        for value in ("abc", "91,10", "55.6", ""):
            with self.subTest(value=value):
                request = RequestFactory().get("/api/alerts", headers={"X-TT-Position": value})
                self.assertEqual(position_from(request), (None, None))


class RedactTests(SimpleTestCase):
    def test_positions_tokens_and_keys_are_hidden(self):
        line = (
            "GET /api/alerts?lat=55.6049&lon=13.0038&regions=sl HTTP/1.1 key=abc123&token=xyz "
            "X-Device-Token: dev-tok Authorization: Bearer eyJ.abc X-TT-Position: 55.60,13.00 "
            '<LOGIN authenticationkey="hemlig" />'
        )
        cleaned = redact(line)
        for secret in ("55.6049", "13.0038", "abc123", "xyz", "dev-tok", "eyJ.abc", "55.60,13.00", "hemlig"):
            self.assertNotIn(secret, cleaned)
        self.assertIn("regions=sl", cleaned)

    def test_the_filter_rewrites_the_record_and_its_traceback(self):
        record = logging.LogRecord(
            "core.sources", logging.WARNING, __file__, 1, "hämtning misslyckades: %s",
            ("https://api.example.invalid/x?key=hemlig&lat=59.33",), None,
        )
        try:
            raise RuntimeError("GET https://api.example.invalid/y?token=ocksa-hemlig")
        except RuntimeError:
            import sys

            record.exc_info = sys.exc_info()
        RedactFilter().filter(record)
        self.assertNotIn("hemlig", record.getMessage())
        self.assertNotIn("59.33", record.getMessage())
        self.assertNotIn("ocksa-hemlig", record.exc_text)

    def test_every_handler_is_filtered_including_the_workers(self):
        self.assertIn("redact", settings.LOGGING["handlers"]["console"]["filters"])
        self.assertFalse(settings.CELERY_WORKER_HIJACK_ROOT_LOGGER)


class HeaderPositionFeedTests(ApiTestCase):
    def test_the_feed_uses_the_position_header(self):
        opportunity(title="Nära", lat=55.6092, lon=13.0007)
        opportunity(title="Långt bort", lat=57.7089, lon=11.9746)
        body = self.client.get(
            "/api/alerts", headers={"x-device-token": DEVICE_TOKEN, "X-TT-Position": "55.60,13.00"},
        ).json()
        self.assertEqual([a["title"] for a in body["alerts"]], ["Nära"])
