"""
Statussidan i adminwebben: bara personal, inga hemligheter ut, och en källa
som slutat hämta syns som röd -- inte som lugn trafik.

Nätverkskontrollerna (Stripe, Bolagsverket, Firebase, SMTP, Supabase Auth,
Redis) byts ut: testerna får aldrig anropa en riktig tjänst.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import Client, override_settings
from django.utils import timezone

from core import thresholds
from core.models import SourceStatus
from fleet import admin_status
from fleet.models import StaffRole
from fleet.tests.base import FleetTestCase
from fleet.tests.test_admin import SECRET, jwt


def _fake(key):
    return lambda: admin_status._check(key, key, admin_status.OK, "fejkad")


FAKE_PROBES = {key: _fake(key) for key in admin_status.PROBES}


@override_settings(SUPABASE_JWT_SECRET=SECRET, CELERY_TASK_ALWAYS_EAGER=False)
@mock.patch.dict(admin_status.PROBES, FAKE_PROBES)
class AdminStatusTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        cache.delete(admin_status.CACHE_KEY)
        self.client = Client()
        self.data = self.full_setup()
        self.admin_id = str(uuid.uuid4())
        StaffRole.objects.create(user_id=self.admin_id, role=StaffRole.Role.SUPPORT)

    def get(self, user_id, fresh=True):
        return self.client.get(
            "/api/admin/status" + ("?fresh=1" if fresh else ""),
            headers={"authorization": f"Bearer {jwt(user_id)}"},
        )

    def checks(self, body):
        return {c["key"]: c for g in body["groups"] for c in g["checks"]}

    def test_only_staff_see_the_status(self):
        self.assertEqual(self.client.get("/api/admin/status").status_code, 401)
        response = self.get(str(self.data["owner"].user_id))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["reason"], "not_staff")

    def test_support_can_read_the_status(self):
        response = self.get(self.admin_id)
        self.assertEqual(response.status_code, 200, response.content)
        checks = self.checks(response.json())
        self.assertEqual(checks["database"]["status"], "ok")
        self.assertIn("stripe", checks)
        self.assertIn("trafiklab", checks)

    @override_settings(TRAFIKLAB_API_KEY="k")
    def test_a_core_source_that_stopped_fetching_is_red(self):
        SourceStatus.objects.create(
            source="trafiklab", ok=True, checked_at=timezone.now(),
            last_success_at=timezone.now() - timedelta(hours=2),
        )
        body = self.get(self.admin_id).json()
        self.assertEqual(self.checks(body)["trafiklab"]["status"], "down")
        self.assertEqual(body["overall"], "down")

    @override_settings(SWEDAVIA_API_KEY="")
    def test_a_source_without_a_key_is_off_not_broken(self):
        self.assertEqual(self.checks(self.get(self.admin_id).json())["swedavia"]["status"], "off")

    @override_settings(TRAFIKLAB_API_KEY="k")
    def test_keys_in_error_messages_never_leave_the_server(self):
        now = timezone.now()
        SourceStatus.objects.create(
            source="trafiklab", ok=False, checked_at=now, last_success_at=now,
            message="HTTPError: 429 for url https://x.se/rt?key=HEMLIG123&x=1",
            detail={"skane": {"ok": False, "error": "401 https://x.se?key=HEMLIG456"}},
        )
        response = self.get(self.admin_id)
        self.assertNotIn(b"HEMLIG", response.content)
        self.assertEqual(self.checks(response.json())["trafiklab"]["status"], "warn")

    def test_a_stale_heartbeat_means_the_scheduler_is_down(self):
        SourceStatus.objects.create(
            source=thresholds.HEARTBEAT_SOURCE, ok=True,
            checked_at=timezone.now() - timedelta(minutes=10),
        )
        self.assertEqual(self.checks(self.get(self.admin_id).json())["beat"]["status"], "down")

    def test_a_hanging_service_only_turns_its_own_row_red(self):
        def boom():
            raise RuntimeError("kraschade")

        with mock.patch.dict(admin_status.PROBES, {"bolagsverket": boom}):
            body = self.get(self.admin_id).json()
        checks = self.checks(body)
        self.assertEqual(checks["bolagsverket"]["status"], "down")
        self.assertEqual(checks["firebase"]["status"], "ok")

    def test_redaction_keeps_ordinary_words(self):
        self.assertEqual(
            admin_status._redact("Ishockey: konto avstängt, url?key=abc&apikey=def"),
            "Ishockey: konto avstängt, url?key=***&apikey=***",
        )

    @override_settings(FLEET_OUTBOX_SENDER="fleet.mailer.send", FLEET_SMTP_USER="", FLEET_SMTP_PASSWORD="")
    def test_the_explicit_smtp_sender_is_checked_as_smtp(self):
        """Prod pekar ut fleet.mailer.send uttryckligen -- det är SMTP, inte 'en annan avsändare'."""
        check = admin_status._smtp()
        self.assertIn("FLEET_SMTP_USER", check["summary"])
