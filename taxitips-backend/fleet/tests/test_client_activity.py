"""
Klientaktivitet, appens felrapporter och adminwebbens vy över dem.

Det som testas är det som går sönder tyst: att metadata faktiskt skrivs (och
inte skrivs på varje anrop), att ingen hemlighet eller kontaktuppgift når
tabellen, att gränserna biter, och att bara personalen kan läsa.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import timedelta
from unittest import mock

from django.db import connection
from django.test import Client, RequestFactory, override_settings
from django.utils import timezone

from core import request_context
from core.log_filters import ContextFormatter
from fleet import access, client_activity, ratelimit
from fleet.client_log_api import MAX_BODY
from fleet.models import ClientActivity, ClientError, KnownAccount, StaffRole
from fleet.tests.base import FleetTestCase

SECRET = "client-activity-test-secret-at-least-32-chars!"

APP_HEADERS = {
    "X-App-Version": "1.0.1",
    "X-App-Build": "2",
    "X-App-Platform": "android",
    "X-OS-Version": "Android 14 (SDK 34)",
    "X-Device-Model": "samsung SM-S911B",
}


def jwt(sub: str, email: str = "", *, login_ts: int | None = None) -> str:
    def seg(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    head = seg({"alg": "HS256", "typ": "JWT"})
    claims = {"sub": sub, "exp": int(time.time()) + 3600, "aal": "aal1"}
    if email:
        claims["email"] = email
    if login_ts is not None:
        claims["amr"] = [{"method": "password", "timestamp": login_ts}]
    body = seg(claims)
    sig = hmac.new(SECRET.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"


class _Base(FleetTestCase):
    def setUp(self):
        super().setUp()
        client_activity.reset_throttle()
        from fleet import accounts

        accounts._seen_cache.clear()
        self.client = Client()

    def resolve(self, headers):
        """Åtkomstkontrollen inne i en begäran, som middlewaren sätter upp den."""
        request = RequestFactory().get("/api/alerts", headers=headers, REMOTE_ADDR="81.2.3.4")
        ctx, token = request_context.begin(request)
        try:
            return access.resolve(request), ctx
        finally:
            request_context.end(token)

    def log(self, body, headers=None, **extra):
        return self.client.post(
            "/api/client-log", data=json.dumps(body), content_type="application/json",
            headers=headers or {}, **extra,
        )


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class ActivityTests(_Base):
    def test_a_phone_gets_its_metadata_written_once_not_on_every_call(self):
        setup = self.full_setup()
        headers = {"X-Device-Token": setup["secret"], **APP_HEADERS}
        with mock.patch.object(
            client_activity, "_write_activity", wraps=client_activity._write_activity,
        ) as write:
            # Svaret spelar ingen roll här (telefonen har inget pass än) --
            # det som prövas är att en giltig token bokförs, och bara en gång.
            for _ in range(5):
                _result, ctx = self.resolve(headers)
            self.assertEqual(write.call_count, 1)
        # Loggraderna under begäran bär telefonens id.
        self.assertEqual(ctx.device_id, str(setup["device"].id))

        row = ClientActivity.objects.get(subject_kind="device", subject_id=setup["device"].id)
        self.assertEqual(row.company_id, setup["company"].id)
        self.assertEqual(row.app_version, "1.0.1")
        self.assertEqual(row.app_build, "2")
        self.assertEqual(row.platform, "android")
        self.assertEqual(row.os_version, "Android 14 (SDK 34)")
        self.assertEqual(row.device_model, "samsung SM-S911B")
        # Nätet, inte adressen.
        self.assertEqual(row.ip_prefix, "81.2.3.0/24")
        self.assertIsNone(row.last_login_at)

    def test_a_new_app_version_is_written_at_once(self):
        setup = self.full_setup()
        self.resolve({"X-Device-Token": setup["secret"], **APP_HEADERS})
        self.resolve({"X-Device-Token": setup["secret"], **APP_HEADERS, "X-App-Version": "1.0.2"})
        row = ClientActivity.objects.get(subject_kind="device", subject_id=setup["device"].id)
        self.assertEqual(row.app_version, "1.0.2")

    def test_a_call_without_app_headers_does_not_erase_what_the_app_sent(self):
        company = self.make_company()
        owner = self.make_owner(company)
        user = str(owner.user_id)
        self.resolve({"Authorization": f"Bearer {jwt(user, 'agare@example.test')}", **APP_HEADERS})
        # Kundportalen i en webbläsare: inga X-App-*-headers.
        self.resolve({"Authorization": f"Bearer {jwt(user, 'agare@example.test')}"})
        row = ClientActivity.objects.get(subject_kind="user", subject_id=user)
        self.assertEqual(row.app_version, "1.0.1")
        self.assertEqual(row.device_model, "samsung SM-S911B")
        self.assertEqual(row.company_id, company.id)

    def test_last_login_comes_from_the_verified_token_and_only_moves_forward(self):
        company = self.make_company()
        user = str(self.make_owner(company).user_id)
        first = int(time.time()) - 7200
        self.resolve({"Authorization": f"Bearer {jwt(user, 'a@example.test', login_ts=first)}"})
        row = ClientActivity.objects.get(subject_kind="user", subject_id=user)
        self.assertEqual(int(row.last_login_at.timestamp()), first)

        later = first + 3600
        self.resolve({"Authorization": f"Bearer {jwt(user, 'a@example.test', login_ts=later)}"})
        row.refresh_from_db()
        self.assertEqual(int(row.last_login_at.timestamp()), later)

        # En gammal session på en annan telefon flyttar inte tillbaka tiden.
        self.resolve({"Authorization": f"Bearer {jwt(user, 'a@example.test', login_ts=first)}"})
        row.refresh_from_db()
        self.assertEqual(int(row.last_login_at.timestamp()), later)

    def test_headers_are_cleaned_and_nonsense_is_dropped(self):
        request = RequestFactory().get("/", headers={
            "X-App-Version": "1.0.1; drop table",
            "X-App-Platform": "PlayStation",
            "X-Device-Model": "Pixelé 8" + "x" * 200,
        })
        meta = client_activity.meta_from_request(request)
        self.assertEqual(meta["app_version"], "")
        self.assertEqual(meta["platform"], "other")
        self.assertTrue(meta["device_model"].startswith("Pixel 8"))
        self.assertLessEqual(len(meta["device_model"]), 64)

    def test_nothing_is_written_outside_a_request(self):
        setup = self.full_setup()
        access.device_for_token(setup["secret"])
        self.assertFalse(ClientActivity.objects.exists())


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class ClientLogTests(_Base):
    def test_a_phone_reports_a_failed_flow(self):
        setup = self.full_setup()
        res = self.log(
            {"kind": "flow", "flow": "feed", "message": "SocketException: Connection reset",
             "errorType": "SocketException", "status": 503, "reason": "internal_error"},
            headers={"X-Device-Token": setup["secret"], **APP_HEADERS},
        )
        self.assertEqual(res.status_code, 202)
        self.assertTrue(res.headers.get("X-Request-Id"))
        row = ClientError.objects.get()
        self.assertEqual(row.source, "app")
        self.assertEqual(row.kind, "flow")
        self.assertEqual(row.flow, "feed")
        self.assertEqual(row.device_id, setup["device"].id)
        self.assertEqual(row.company_id, setup["company"].id)
        self.assertEqual(row.http_status, 503)
        self.assertEqual(row.reason, "internal_error")
        self.assertEqual(row.app_version, "1.0.1")
        self.assertEqual(row.device_model, "samsung SM-S911B")

    def test_a_logged_in_owner_reports_a_crash(self):
        company = self.make_company()
        user = str(self.make_owner(company).user_id)
        res = self.log(
            {"kind": "crash", "flow": "uncaught", "message": "Null check operator", "fatal": True},
            headers={"Authorization": f"Bearer {jwt(user, 'o@example.test')}"},
        )
        self.assertEqual(res.status_code, 202)
        row = ClientError.objects.get()
        self.assertEqual(str(row.user_id), user)
        self.assertEqual(row.company_id, company.id)
        self.assertTrue(row.fatal)

    def test_secrets_contacts_and_positions_are_stripped(self):
        setup = self.full_setup()
        token = jwt(str(uuid.uuid4()), "x@example.test")
        device_secret = "Zk3pQ9vX2mL7nR4tY8wB1cD6fG0hJ5sA-_aE3"
        opportunity = str(uuid.uuid4())
        message = (
            f"login failed for kalle.anka@example.se token={device_secret} "
            f"Authorization: Bearer {token} jwt {token} "
            "ring 070-123 45 67 eller +46701234567, pnr 19800101-1234, "
            "position 55.60512, 13.00123 lat=55.6051 "
            f"password: hunter2 opportunity {opportunity}"
        )
        stack = (
            "#0 RenderFlexOverflowIndicatorPainter.paint (package:flutter/rendering.dart:12:3)\n"
            f"#1 push fcm dGhpc2lzYWZha2VmY21:APA91bHZ0b2tlbjEyMzQ1Njc4OTBhYmNkZWZnaGlqa2xtbm9w\n"
        )
        res = self.log(
            {"kind": "flow", "flow": "login", "message": message, "stack": stack},
            headers={"X-Device-Token": setup["secret"]},
        )
        self.assertEqual(res.status_code, 202)
        row = ClientError.objects.get()
        stored = row.message + "\n" + row.stack
        for leak in (
            "kalle.anka", device_secret, token, "070-123", "701234567", "19800101",
            "55.60512", "13.00123", "55.6051", "hunter2", "APA91b",
        ):
            self.assertNotIn(leak, stored, leak)
        # Det supporten söker på finns kvar: id:n och klassnamn.
        self.assertIn(opportunity, row.message)
        self.assertIn("RenderFlexOverflowIndicatorPainter", row.stack)
        self.assertIn("<e-post>", row.message)

    def test_the_same_error_is_counted_not_repeated(self):
        setup = self.full_setup()
        headers = {"X-Device-Token": setup["secret"]}
        for _ in range(3):
            self.log({"kind": "flow", "flow": "feed", "message": "Timeout"}, headers=headers)
        row = ClientError.objects.get()
        self.assertEqual(row.occurrences, 3)

    def test_a_logged_in_sender_is_rate_limited(self):
        setup = self.full_setup()
        headers = {"X-Device-Token": setup["secret"]}
        statuses = [
            self.log({"kind": "flow", "flow": "feed", "message": f"fel {i}"}, headers=headers).status_code
            for i in range(ratelimit.CLIENT_LOG.limit + 1)
        ]
        self.assertEqual(statuses[:-1], [202] * ratelimit.CLIENT_LOG.limit)
        self.assertEqual(statuses[-1], 429)
        self.assertEqual(ClientError.objects.count(), ratelimit.CLIENT_LOG.limit)

    def test_anonymous_reports_are_accepted_but_limited_harder(self):
        statuses = [
            self.log({"kind": "flow", "flow": "login", "message": f"Auth-fel {i}"},
                     REMOTE_ADDR="90.1.2.3").status_code
            for i in range(ratelimit.CLIENT_LOG_ANON.limit + 1)
        ]
        self.assertEqual(statuses[-1], 429)
        self.assertEqual(statuses.count(202), ratelimit.CLIENT_LOG_ANON.limit)
        row = ClientError.objects.first()
        self.assertIsNone(row.user_id)
        self.assertIsNone(row.device_id)
        self.assertIsNone(row.company_id)

    def test_an_unknown_device_token_counts_as_anonymous(self):
        res = self.log({"kind": "flow", "flow": "feed", "message": "x"},
                       headers={"X-Device-Token": "inte-en-riktig-token"})
        self.assertEqual(res.status_code, 202)
        self.assertIsNone(ClientError.objects.get().device_id)

    def test_too_large_and_malformed_bodies_are_refused(self):
        big = {"kind": "crash", "flow": "uncaught", "message": "x" * (MAX_BODY + 10)}
        self.assertEqual(self.log(big).status_code, 413)
        self.assertEqual(self.log({"kind": "whatever", "message": "x"}).status_code, 400)
        res = self.client.post("/api/client-log", data="[1,2]", content_type="application/json")
        self.assertEqual(res.status_code, 400)
        self.assertFalse(ClientError.objects.exists())

    def test_long_text_is_capped(self):
        self.log({"kind": "crash", "flow": "uncaught", "message": "a " * 3000, "stack": "b " * 5000})
        row = ClientError.objects.get()
        self.assertLessEqual(len(row.message), client_activity.MESSAGE_MAX)
        self.assertLessEqual(len(row.stack), client_activity.STACK_MAX)

    def test_a_flow_name_that_is_not_a_name_becomes_unknown(self):
        self.log({"kind": "flow", "flow": "<script>alert(1)</script>", "message": "x"})
        self.assertEqual(ClientError.objects.get().flow, "unknown")


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class ServerErrorTests(_Base):
    def test_a_500_gets_a_request_id_and_a_row_in_the_error_list(self):
        setup = self.full_setup()
        user = str(setup["owner"].user_id)
        with mock.patch("fleet.api.access.principal_for", side_effect=RuntimeError("boom")):
            res = self.client.get(
                "/api/fleet/company", headers={"Authorization": f"Bearer {jwt(user)}", **APP_HEADERS},
            )
        self.assertEqual(res.status_code, 500)
        request_id = res.headers["X-Request-Id"]
        row = ClientError.objects.get()
        self.assertEqual(row.source, "server")
        self.assertEqual(row.request_id, request_id)
        self.assertEqual(row.path, "/api/fleet/company")
        self.assertEqual(row.http_status, 500)
        self.assertEqual(row.app_version, "1.0.1")
        # Ingen feltext från undantaget -- den står i loggen under samma id.
        self.assertNotIn("boom", row.message)

    def test_log_lines_carry_the_request_id_and_who_asked(self):
        request = RequestFactory().get("/api/alerts")
        ctx, token = request_context.begin(request)
        try:
            request_context.note_device(uuid.UUID(int=7))
            record = logging.LogRecord("fleet.api", logging.ERROR, __file__, 1, "oväntat fel", None, None)
            line = ContextFormatter("%(name)s%(ctx)s: %(message)s").format(record)
        finally:
            request_context.end(token)
        self.assertIn(f"req={ctx.request_id}", line)
        self.assertIn("path=/api/alerts", line)
        self.assertIn(f"device={uuid.UUID(int=7)}", line)
        # Utanför en begäran: ingen kontext, inget fel.
        record = logging.LogRecord("x", logging.INFO, __file__, 1, "hej", None, None)
        self.assertEqual(ContextFormatter("%(name)s%(ctx)s: %(message)s").format(record), "x: hej")

    @override_settings(APP_API_ALLOWED_ORIGINS=["https://app.taxitips.test"])
    def test_web_preflight_allows_the_app_headers_and_exposes_the_request_id(self):
        res = self.client.options(
            "/api/alerts", headers={"Origin": "https://app.taxitips.test"},
        )
        allow = res.headers["Access-Control-Allow-Headers"]
        for header in APP_HEADERS:
            self.assertIn(header, allow)
        self.assertIn("X-Device-Token", allow)
        self.assertIn("X-Request-Id", res.headers["Access-Control-Expose-Headers"])


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class AdminActivityTests(_Base):
    def setUp(self):
        super().setUp()
        self.support_id = str(uuid.uuid4())
        StaffRole.objects.create(user_id=self.support_id, role=StaffRole.Role.SUPPORT)

    def get(self, path, user_id):
        return self.client.get(path, headers={"Authorization": f"Bearer {jwt(user_id)}"})

    def test_support_reads_phones_and_errors_for_one_company(self):
        setup = self.full_setup()
        other = self.full_setup(company=self.make_company(name="Annat AB", org_number="5599887766"))
        for s in (setup, other):
            self.resolve({"X-Device-Token": s["secret"], **APP_HEADERS})
            self.log({"kind": "flow", "flow": "pairing", "message": "fel"},
                     headers={"X-Device-Token": s["secret"], **APP_HEADERS})

        company = setup["company"].id
        clients = self.get(f"/api/admin/activity/clients?company={company}", self.support_id).json()
        self.assertEqual([c["id"] for c in clients["clients"]], [str(setup["device"].id)])
        phone = clients["clients"][0]
        self.assertEqual(phone["label"], setup["device"].label)
        self.assertEqual(phone["appVersion"], "1.0.1")
        self.assertEqual(phone["deviceModel"], "samsung SM-S911B")
        self.assertEqual(clients["versions"], [{"platform": "android", "appVersion": "1.0.1", "count": 1}])

        errors = self.get(f"/api/admin/activity/errors?company={company}", self.support_id).json()
        self.assertEqual(len(errors["errors"]), 1)
        self.assertEqual(errors["errors"][0]["deviceLabel"], setup["device"].label)
        self.assertEqual(errors["flows"], [{"flow": "pairing", "count": 1}])

        filtered = self.get("/api/admin/activity/errors?flow=login", self.support_id).json()
        self.assertEqual(filtered["errors"], [])

    def test_customers_and_strangers_cannot_read(self):
        setup = self.full_setup()
        owner = str(setup["owner"].user_id)
        for path in ("/api/admin/activity/clients", "/api/admin/activity/errors"):
            self.assertEqual(self.get(path, owner).status_code, 403)
            self.assertEqual(self.client.get(path).status_code, 401)
            # En förartoken ger aldrig administrativ behörighet.
            res = self.client.get(path, headers={"X-Device-Token": setup["secret"]})
            self.assertEqual(res.status_code, 401)

    def test_the_account_list_shows_last_login_and_app(self):
        company = self.make_company()
        user = str(self.make_owner(company).user_id)
        login = int(time.time()) - 60
        self.resolve({"Authorization": f"Bearer {jwt(user, 'agare@example.test', login_ts=login)}",
                      **APP_HEADERS})
        self.assertTrue(KnownAccount.objects.filter(user_id=user).exists())
        body = self.get("/api/admin/accounts?q=agare@", self.support_id).json()
        client = body["accounts"][0]["client"]
        self.assertEqual(client["appVersion"], "1.0.1")
        self.assertEqual(client["platform"], "android")
        self.assertIsNotNone(client["lastLoginAt"])


class RetentionTests(_Base):
    def test_old_errors_and_silent_clients_are_purged(self):
        now = timezone.now()
        old = ClientError.objects.create(
            last_at=now - timedelta(days=client_activity.ERROR_RETENTION_DAYS + 1),
            source="app", kind="flow", flow="feed",
        )
        fresh = ClientError.objects.create(last_at=now, source="app", kind="flow", flow="feed")
        ClientActivity.objects.create(
            subject_kind="device", subject_id=uuid.uuid4(),
            last_seen_at=now - timedelta(days=client_activity.ACTIVITY_RETENTION_DAYS + 1),
        )
        kept = ClientActivity.objects.create(subject_kind="device", subject_id=uuid.uuid4(), last_seen_at=now)
        result = client_activity.purge()
        self.assertEqual(result, {"client_errors": 1, "client_activity": 1})
        self.assertFalse(ClientError.objects.filter(id=old.id).exists())
        self.assertTrue(ClientError.objects.filter(id=fresh.id).exists())
        self.assertEqual(list(ClientActivity.objects.values_list("id", flat=True)), [kept.id])


class PostgrestTests(_Base):
    def test_anon_and_authenticated_cannot_touch_the_tables(self):
        with connection.cursor() as cur:
            for role in ("anon", "authenticated"):
                cur.execute("select 1 from pg_roles where rolname = %s", [role])
                if cur.fetchone() is None:
                    continue  # naken Postgres: rollen finns inte, inget att läcka till
                for table in ("fleet_client_activity", "fleet_client_error"):
                    for privilege in ("SELECT", "UPDATE", "INSERT"):
                        cur.execute(
                            "select has_table_privilege(%s, %s, %s)",
                            [role, f"public.{table}", privilege],
                        )
                        self.assertFalse(cur.fetchone()[0], f"{role} {privilege} {table}")
