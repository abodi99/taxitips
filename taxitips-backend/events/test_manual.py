"""
Egna evenemang: inlagda för hand eller importerade från fil i adminwebben.
"""

from __future__ import annotations

import datetime as dt
import json
import uuid

from django.test import Client, override_settings

from events import manual
from events.models import Event
from events.rights import app_sources
from fleet.models import StaffRole
from fleet.tests.base import FleetTestCase
from fleet.tests.test_accounts import SECRET, jwt

TODAY = dt.date(2026, 10, 1)
CSV = (
    "namn;datum;tid;arena;stad;lat;lon;kategori;besökare\n"
    "Malmö FF - AIK;2026-10-03;19:00;Eleda Stadion;Malmö;55.5838;12.9884;sport;20000\n"
    "Julmarknad;2026-10-04;;Stortorget;Malmö;55.6059;13.0007;festival;\n"
)


class ManualEventTests(FleetTestCase):
    def test_a_csv_with_semicolons_is_read_with_swedish_headers(self):
        rows = manual.validate(manual.parse_file(CSV, "x.csv"), today=TODAY)
        self.assertEqual([r["name"] for r in rows], ["Malmö FF - AIK", "Julmarknad"])
        match = rows[0]
        self.assertEqual(match["category"], "sport")
        self.assertEqual(match["attendance"], 20000)
        self.assertEqual(match["end_basis"], "estimated")
        # Utan tid: ingen påhittad start- eller sluttid.
        self.assertIsNone(rows[1]["start_at"])
        self.assertIsNone(rows[1]["end_at"])

    def test_one_bad_row_saves_nothing_and_names_the_row(self):
        bad = CSV + "Utan plats;2026-10-05;18:00;;;;;konsert;\n"
        with self.assertRaises(manual.ImportError_) as caught:
            manual.validate(manual.parse_file(bad, "x.csv"), today=TODAY)
        self.assertEqual(caught.exception.errors[0][0], 3)
        self.assertIn("koordinat saknas", caught.exception.errors[0][1])
        self.assertEqual(Event.objects.count(), 0)

    def test_swapped_coordinates_are_refused_not_guessed(self):
        row = {"name": "X", "date": "2026-10-03", "lat": "12.9884", "lon": "55.5838"}
        with self.assertRaises(manual.ImportError_):
            manual.validate([row], today=TODAY)

    def test_importing_the_same_file_twice_updates_instead_of_duplicating(self):
        rows = manual.validate(manual.parse_file(CSV, "x.csv"), today=TODAY)
        first = manual.save(rows)
        again = manual.save(manual.validate(manual.parse_file(CSV, "x.csv"), today=TODAY))
        self.assertEqual(first["created"], 2)
        self.assertEqual(again["updated"], 2)
        self.assertEqual(Event.objects.filter(source="manual").count(), 2)

    def test_an_ending_after_midnight_lands_on_the_next_day(self):
        row = {"name": "Klubb", "date": "2026-10-03", "time": "22:00", "sluttid": "02:00",
               "lat": "55.6", "lon": "13.0"}
        event = manual.validate([row], today=TODAY)[0]
        self.assertEqual(event["end_at"].date(), dt.date(2026, 10, 4))
        self.assertEqual(event["end_basis"], "source")

    def test_manual_events_may_be_shown_in_the_app(self):
        self.assertIn("manual", app_sources())


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class ManualEventAdminTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.admin_id = str(uuid.uuid4())
        StaffRole.objects.create(user_id=self.admin_id, role=StaffRole.Role.PLATFORM_ADMIN)
        self.client = Client()
        self.auth = {"authorization": f"Bearer {jwt(self.admin_id)}"}

    def post(self, path, body):
        return self.client.post(
            path, data=json.dumps(body), content_type="application/json", headers=self.auth,
        )

    def future_csv(self):
        day = (dt.date.today() + dt.timedelta(days=3)).isoformat()
        return CSV.replace("2026-10-03", day).replace("2026-10-04", day)

    def test_a_dry_run_previews_without_saving(self):
        response = self.post("/api/admin/events/import", {
            "filename": "x.csv", "content": self.future_csv(), "dryRun": True,
        })
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["count"], 2)
        self.assertEqual(Event.objects.count(), 0)

    def test_import_then_delete_only_own_events(self):
        response = self.post("/api/admin/events/import", {"filename": "x.csv", "content": self.future_csv()})
        self.assertEqual(response.json()["created"], 2)
        own = Event.objects.filter(source="manual").first()
        self.assertEqual(self.post(f"/api/admin/events/{own.id}/delete", {}).status_code, 200)

        fetched = Event.objects.create(
            source="ticketmaster", external_id="tm1", name="Hämtat", category="konsert",
            start_date=dt.date.today(), end_basis="unknown", last_seen_at=own.last_seen_at,
        )
        refused = self.post(f"/api/admin/events/{fetched.id}/delete", {})
        self.assertEqual(refused.status_code, 400)
        self.assertTrue(Event.objects.filter(id=fetched.id).exists())

    def test_errors_come_back_per_row(self):
        response = self.post("/api/admin/events/import", {
            "filename": "x.csv", "content": "namn;datum\nX;igår\n",
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["errors"][0]["row"], 1)
