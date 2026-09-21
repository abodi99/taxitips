"""
FCM-meddelandet och vad ett svar betyder. Inget nätverk: requests.post ersätts.
"""

from __future__ import annotations

import json
from unittest import mock

from django.test import SimpleTestCase

from billing import fcm


def fcm_error(status: str, code: str | None = None, message: str = "") -> str:
    details = [{"@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError", "errorCode": code}] if code else []
    return json.dumps({"error": {"status": status, "message": message, "details": details}}, indent=2)


class OutcomeTests(SimpleTestCase):
    def test_what_each_answer_means(self):
        cases = [
            ({"ok": True}, "sent"),
            ({"ok": False, "status": 404, "body": fcm_error("NOT_FOUND", "UNREGISTERED")}, "dead_token"),
            ({"ok": False, "status": 403, "body": fcm_error("PERMISSION_DENIED", "SENDER_ID_MISMATCH")}, "dead_token"),
            ({"ok": False, "status": 400, "body": fcm_error(
                "INVALID_ARGUMENT", "INVALID_ARGUMENT", "The registration token is not a valid FCM registration token",
            )}, "dead_token"),
            ({"ok": False, "status": 400, "body": fcm_error("INVALID_ARGUMENT", "INVALID_ARGUMENT", "Invalid JSON payload")}, "failed"),
            ({"ok": False, "status": 429, "body": fcm_error("RESOURCE_EXHAUSTED", "QUOTA_EXCEEDED")}, "retry"),
            ({"ok": False, "status": 503, "body": "Service Unavailable"}, "retry"),
            ({"ok": False, "status": None, "body": "Connection reset"}, "retry"),
            ({"ok": False, "status": 404, "body": fcm_error("NOT_FOUND")}, "failed"),
        ]
        for result, expected in cases:
            with self.subTest(expected=expected, status=result.get("status")):
                self.assertEqual(fcm.outcome(result), expected)

    def test_the_error_code_survives_a_long_body(self):
        """errorCode ligger djupt i svaret; de 200 tecken som tidigare sparades kapade bort det."""
        body = fcm_error("NOT_FOUND", "UNREGISTERED", "Requested entity was not found." * 3)
        self.assertGreater(body.index("UNREGISTERED"), 200)
        response = mock.Mock(ok=False, status_code=404, text=body)
        with mock.patch("billing.fcm.requests.post", return_value=response):
            result = fcm.send_push({"project_id": "p"}, "at", token="t", title="T", body="B")
        self.assertEqual(fcm.outcome(result), "dead_token")


class MessageTests(SimpleTestCase):
    def test_collapse_key_and_ttl_reach_both_platforms(self):
        response = mock.Mock(ok=True, status_code=200, text="{}")
        with mock.patch("billing.fcm.requests.post", return_value=response) as post:
            fcm.send_push(
                {"project_id": "p"}, "at", token="t", title="T", body="B", data={"a": 1},
                collapse_key="abc123", ttl_seconds=600,
            )
        message = post.call_args.kwargs["json"]["message"]
        self.assertEqual(message["android"]["collapse_key"], "abc123")
        self.assertEqual(message["android"]["ttl"], "600s")
        self.assertEqual(message["apns"]["headers"]["apns-collapse-id"], "abc123")
        self.assertIn("apns-expiration", message["apns"]["headers"])
        self.assertEqual(message["data"], {"a": "1"})

    def test_every_message_is_high_priority_on_its_own_channel(self):
        """
        Utan hög prioritet fördröjer Doze leveransen i minuter, och utan egen
        kanal visar Samsung notisen tyst i panelen. Mätt på en S22+
        2026-09-21: notisen levererades men syntes aldrig. Gäller även ett
        meddelande utan collapse_key och ttl -- de var tidigare det enda som
        gav meddelandet en android-del över huvud taget.
        """
        response = mock.Mock(ok=True, status_code=200, text="{}")
        with mock.patch("billing.fcm.requests.post", return_value=response) as post:
            fcm.send_push({"project_id": "p"}, "at", token="t", title="T", body="B")
        message = post.call_args.kwargs["json"]["message"]
        self.assertEqual(message["android"]["priority"], "high")
        self.assertEqual(
            message["android"]["notification"]["channel_id"], fcm.ANDROID_CHANNEL_ID
        )
        self.assertEqual(message["apns"]["headers"]["apns-priority"], "10")
