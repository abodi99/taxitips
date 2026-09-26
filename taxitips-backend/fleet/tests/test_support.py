"""
Supportchatten (fleet/support.py): vem som får skriva, vem som ser vad, och
att räknarna "oläst" och "väntar på svar" stämmer.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from unittest import mock

from django.core.cache import cache
from django.test import Client, override_settings

from billing.models import Device
from fleet import accounts, support
from fleet.models import StaffRole, SupportMessage, SupportThread
from fleet.tests.base import FleetTestCase

SECRET = "support-test-secret-at-least-32-characters!"


def jwt(sub: str, email: str = "") -> str:
    def seg(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    head = seg({"alg": "HS256", "typ": "JWT"})
    claims = {"sub": sub, "exp": int(time.time()) + 3600, "aal": "aal1"}
    if email:
        claims["email"] = email
    body = seg(claims)
    sig = hmac.new(SECRET.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class SupportTestCase(FleetTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.client = Client()
        self.data = self.full_setup(county="01")
        self.owner_id = str(self.data["owner"].user_id)
        self.staff_id = str(uuid.uuid4())
        StaffRole.objects.create(user_id=self.staff_id, role=StaffRole.Role.SUPPORT)
        # Svaret köar en notis efter commit. Testerna kör i en transaktion som
        # aldrig committas; notisens mottagare testas för sig.
        patcher = mock.patch("fleet.support._enqueue_reply_push")
        self.enqueued = patcher.start()
        self.addCleanup(patcher.stop)

    # --- användaren ---
    def as_owner(self, method, path, body=None, user=None, email="agare@taxi.test"):
        headers = {"authorization": f"Bearer {jwt(user or self.owner_id, email)}"}
        return self._call(method, path, body, headers)

    def as_driver(self, method, path, body=None, secret=None):
        headers = {"X-Device-Token": secret or self.data["secret"]}
        return self._call(method, path, body, headers)

    def as_staff(self, method, path, body=None, user=None):
        headers = {"authorization": f"Bearer {jwt(user or self.staff_id)}"}
        return self._call(method, path, body, headers)

    def _call(self, method, path, body, headers):
        if method == "get":
            return self.client.get(path, body or {}, headers=headers)
        return self.client.post(
            path, data=json.dumps(body or {}), content_type="application/json", headers=headers,
        )


class CustomerSideTests(SupportTestCase):
    def test_nothing_exists_until_the_user_writes(self):
        body = self.as_driver("get", "/api/support").json()
        self.assertIsNone(body["thread"])
        self.assertEqual(body["messages"], [])
        self.assertFalse(SupportThread.objects.exists())

    def test_a_driver_writes_and_sees_the_conversation(self):
        response = self.as_driver("post", "/api/support/messages", {"body": "  Hur byter jag bil?  "})
        self.assertEqual(response.status_code, 200, response.content)
        body = self.as_driver("get", "/api/support").json()
        self.assertEqual([m["body"] for m in body["messages"]], ["Hur byter jag bil?"])
        thread = SupportThread.objects.get()
        self.assertEqual(thread.requester_kind, "device")
        self.assertEqual(str(thread.device_id), str(self.data["device"].id))
        self.assertEqual(str(thread.company_id), str(self.data["company"].id))

    def test_the_account_wins_over_the_phone(self):
        """En ägare som också kör med telefonen: en konversation, kontots."""
        headers = {
            "authorization": f"Bearer {jwt(self.owner_id, 'agare@taxi.test')}",
            "X-Device-Token": self.data["secret"],
        }
        self._call("post", "/api/support/messages", {"body": "Hej"}, headers)
        thread = SupportThread.objects.get()
        self.assertEqual(thread.requester_kind, "member")
        self.assertEqual(str(thread.user_id), self.owner_id)
        self.assertEqual(thread.requester_label, "agare@taxi.test")

    def test_an_account_without_a_company_can_still_ask(self):
        stranger = str(uuid.uuid4())
        response = self.as_owner("post", "/api/support/messages", {"body": "Registreringen hänger"}, user=stranger)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIsNone(SupportThread.objects.get(user_id=stranger).company_id)

    def test_users_never_see_each_others_conversations(self):
        self.as_driver("post", "/api/support/messages", {"body": "Förarens fråga"})
        body = self.as_owner("get", "/api/support").json()
        self.assertIsNone(body["thread"])

    def test_no_credentials_and_unknown_tokens_are_refused(self):
        self.assertEqual(self.client.get("/api/support").status_code, 401)
        response = self.as_driver("post", "/api/support/messages", {"body": "x"}, secret="nope")
        self.assertEqual(response.status_code, 401)

    def test_a_blocked_account_cannot_write(self):
        accounts.block(kind="user", value=self.owner_id, reason="bedrägeri", actor_user_id=None)
        response = self.as_owner("post", "/api/support/messages", {"body": "Släpp mig"})
        self.assertEqual(response.json()["reason"], "account_blocked")

    def test_empty_and_too_long_messages_are_refused(self):
        self.assertEqual(
            self.as_driver("post", "/api/support/messages", {"body": "   "}).json()["reason"],
            "empty_message",
        )
        self.assertEqual(
            self.as_driver("post", "/api/support/messages", {"body": "x" * 2001}).json()["reason"],
            "message_too_long",
        )
        self.assertFalse(SupportMessage.objects.exists())

    def test_a_flood_is_stopped(self):
        for n in range(30):
            self.as_driver("post", "/api/support/messages", {"body": f"rad {n}"})
        response = self.as_driver("post", "/api/support/messages", {"body": "en till"})
        self.assertEqual(response.json()["reason"], "rate_limited")
        self.assertEqual(SupportMessage.objects.count(), 30)

    def test_two_first_messages_make_one_thread(self):
        requester = support.requester_for(_fake_request(self.data["secret"]))
        support.post_customer_message(requester, "ett")
        support.post_customer_message(requester, "två")
        self.assertEqual(SupportThread.objects.count(), 1)
        self.assertEqual(SupportMessage.objects.count(), 2)


def _fake_request(secret):
    from django.test import RequestFactory

    return RequestFactory().get("/api/support", headers={"X-Device-Token": secret})


class StaffSideTests(SupportTestCase):
    def open_thread(self, text="Varför får jag inga notiser?"):
        self.as_driver("post", "/api/support/messages", {"body": text})
        return SupportThread.objects.get()

    def test_a_new_question_waits_and_is_listed_first(self):
        older = self.open_thread("Gammal fråga")
        support.mark_read_by_staff(older)
        other = self.full_setup(county="14", plate="NY1")
        self.as_driver("post", "/api/support/messages", {"body": "Ny fråga"}, secret=other["secret"])

        body = self.as_staff("get", "/api/admin/support/threads").json()
        self.assertEqual(body["waiting"], 1)
        self.assertEqual(body["threads"][0]["preview"], "Ny fråga")
        self.assertTrue(body["threads"][0]["waiting"])
        self.assertFalse(body["threads"][1]["waiting"])
        self.assertEqual(body["threads"][0]["companyName"], other["company"].name)

    def test_reading_clears_waiting_and_a_reply_reaches_the_user(self):
        thread = self.open_thread()
        detail = self.as_staff("get", f"/api/admin/support/threads/{thread.id}", {"markRead": "1"}).json()
        self.assertFalse(detail["thread"]["waiting"])
        self.assertEqual(self.as_staff("get", "/api/admin/support/summary").json()["waiting"], 0)

        response = self.as_staff(
            "post", f"/api/admin/support/threads/{thread.id}/messages", {"body": "Slå på notiser i Inställningar."},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.as_driver("get", "/api/support/unread").json()["unread"], 1)
        body = self.as_driver("get", "/api/support", {"markRead": "1"}).json()
        self.assertEqual(body["messages"][-1]["sender"], "staff")
        self.assertEqual(body["messages"][-1]["author"], "TaxiTips support")
        self.assertEqual(self.as_driver("get", "/api/support/unread").json()["unread"], 0)

    def test_the_reply_queues_a_notification(self):
        thread = self.open_thread()
        with self.captureOnCommitCallbacks(execute=True):
            self.as_staff("post", f"/api/admin/support/threads/{thread.id}/messages", {"body": "Svar"})
        self.enqueued.assert_called_once()

    def test_closing_and_a_new_message_reopens(self):
        thread = self.open_thread()
        self.as_staff("post", f"/api/admin/support/threads/{thread.id}/status", {"status": "closed"})
        thread.refresh_from_db()
        self.assertEqual(thread.status, "closed")
        self.assertEqual(self.as_staff("get", "/api/admin/support/summary").json()["waiting"], 0)

        self.as_driver("post", "/api/support/messages", {"body": "En sak till"})
        thread.refresh_from_db()
        self.assertEqual(thread.status, "open")
        self.assertEqual(self.as_staff("get", "/api/admin/support/summary").json()["waiting"], 1)

    def test_staff_can_start_a_conversation_with_the_owner(self):
        response = self.as_staff("post", f"/api/admin/companies/{self.data['company'].id}/support")
        self.assertEqual(response.status_code, 200, response.content)
        thread_id = response.json()["thread"]["id"]
        self.as_staff("post", f"/api/admin/support/threads/{thread_id}/messages", {"body": "Hej! Hur går provet?"})
        body = self.as_owner("get", "/api/support").json()
        self.assertEqual(body["messages"][0]["body"], "Hej! Hur går provet?")
        self.assertEqual(body["unread"], 1)

    def test_customers_cannot_reach_the_staff_side(self):
        thread = self.open_thread()
        for method, path in (
            ("get", "/api/admin/support/threads"),
            ("get", f"/api/admin/support/threads/{thread.id}"),
            ("post", f"/api/admin/support/threads/{thread.id}/messages"),
        ):
            with self.subTest(path=path):
                self.assertEqual(self.as_owner(method, path, {"body": "x"}).status_code, 403)


class PushTargetTests(SupportTestCase):
    def test_a_driver_thread_notifies_that_phone(self):
        Device.objects.filter(id=self.data["device"].id).update(push_token="fcm-driver")
        self.as_driver("post", "/api/support/messages", {"body": "Hej"})
        targets = support.device_push_targets(SupportThread.objects.get())
        self.assertEqual([d.push_token for d in targets], ["fcm-driver"])

    def test_an_account_thread_notifies_every_phone_it_is_signed_in_on(self):
        Device.objects.filter(id=self.data["device"].id).update(
            push_token="fcm-owner", user_id=self.owner_id,
        )
        self.as_owner("post", "/api/support/messages", {"body": "Hej"})
        targets = support.device_push_targets(SupportThread.objects.get())
        self.assertEqual([d.push_token for d in targets], ["fcm-owner"])

    def test_the_task_sends_a_preview_to_each_target(self):
        from fleet.tasks import send_support_reply_push

        Device.objects.filter(id=self.data["device"].id).update(push_token="fcm-driver")
        self.as_driver("post", "/api/support/messages", {"body": "Hej"})
        thread = SupportThread.objects.get()
        message = support.post_staff_message(thread, staff_user_id=self.staff_id, body="Svar " * 60)
        with mock.patch("billing.fcm.load_service_account", return_value={"x": 1}), \
             mock.patch("billing.fcm.get_access_token", return_value="tok"), \
             mock.patch("billing.fcm.send_push", return_value={"ok": True}) as send:
            result = send_support_reply_push(str(thread.id), str(message.id))
        self.assertEqual(result["sent"], 1)
        kwargs = send.call_args.kwargs
        self.assertEqual(kwargs["token"], "fcm-driver")
        self.assertLessEqual(len(kwargs["body"]), 140)
        self.assertEqual(kwargs["data"]["type"], "support_reply")
