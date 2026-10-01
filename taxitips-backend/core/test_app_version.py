"""
Minsta appversion: jämförelsen, den öppna vägen och tabellens rättigheter.

Det som går sönder tyst här är värre än det som går sönder högt: en jämförelse
som läser "1.0.10" som lägre än "1.0.9" låser ute alla som uppdaterat, och en
tabell som `authenticated` kan skriva i låter en kund göra detsamma.
"""

from __future__ import annotations

from django.db import connection
from django.test import Client, TestCase, override_settings

from core import app_version
from core.models import AppVersionPolicy


class CompareTests(TestCase):
    def test_parts_are_numbers_not_text(self):
        self.assertEqual(app_version.compare("1.0.10", "1.0.9"), 1)
        self.assertEqual(app_version.compare("1.0.9", "1.0.10"), -1)
        self.assertEqual(app_version.compare("2.0", "1.99.99"), 1)

    def test_missing_parts_are_zero(self):
        self.assertEqual(app_version.compare("1.2", "1.2.0"), 0)
        self.assertEqual(app_version.compare("1", "1.0.1"), -1)

    def test_build_number_only_counts_when_both_have_one(self):
        self.assertEqual(app_version.compare("1.0.1+3", "1.0.1+5"), -1)
        self.assertEqual(app_version.compare("1.0.1+5", "1.0.1+5"), 0)
        # En gräns utan byggnummer uppfylls av varje byggning av versionen.
        self.assertEqual(app_version.compare("1.0.1+1", "1.0.1"), 0)
        self.assertEqual(app_version.compare("1.0.2+1", "1.0.1+99"), 1)

    def test_garbage_is_not_a_version(self):
        for value in ("", "v1.0", "1.0.0-beta", "1..2", "99999999999", "1.2.3.4.5"):
            self.assertIsNone(app_version.parse(value), value)


class PublicConfigTests(TestCase):
    def setUp(self):
        self.client = Client()

    def get(self):
        response = self.client.get("/api/config")
        self.assertEqual(response.status_code, 200)
        return response.json()["appVersion"]

    def test_open_without_login_and_empty_by_default(self):
        body = self.get()
        self.assertIsNone(body["android"]["min"])
        self.assertIsNone(body["android"]["recommended"])
        self.assertIsNone(body["ios"]["min"])
        self.assertIsNone(body["ios"]["storeUrl"])
        self.assertIn("se.taxitips.app", body["android"]["storeUrl"])
        self.assertIsNone(body["message"])

    def test_the_stored_row_is_served_per_platform(self):
        AppVersionPolicy.objects.create(
            id=1, android_min_version="1.0.2", android_recommended_version="1.1.0",
            ios_min_version="1.0.0", ios_store_url="https://apps.apple.com/app/id123",
            message="Ny karta.",
        )
        body = self.get()
        self.assertEqual(body["android"], {
            "min": "1.0.2", "recommended": "1.1.0",
            "storeUrl": "https://play.google.com/store/apps/details?id=se.taxitips.app",
        })
        self.assertEqual(body["ios"]["min"], "1.0.0")
        self.assertIsNone(body["ios"]["recommended"])
        self.assertEqual(body["ios"]["storeUrl"], "https://apps.apple.com/app/id123")
        self.assertEqual(body["message"], "Ny karta.")

    @override_settings(APP_ANDROID_MIN_VERSION="1.0.1", APP_IOS_MIN_VERSION="nonsens")
    def test_env_fills_in_an_empty_row_and_a_typo_is_ignored(self):
        body = self.get()
        self.assertEqual(body["android"]["min"], "1.0.1")
        # Ett skrivfel i en miljövariabel får inte stänga ute någon.
        self.assertIsNone(body["ios"]["min"])
        AppVersionPolicy.objects.create(id=1, android_min_version="1.0.3")
        self.assertEqual(self.get()["android"]["min"], "1.0.3")


class PostgrestTests(TestCase):
    def test_anon_and_authenticated_cannot_touch_the_table(self):
        with connection.cursor() as cur:
            for role in ("anon", "authenticated"):
                cur.execute("select 1 from pg_roles where rolname = %s", [role])
                if cur.fetchone() is None:
                    continue  # naken Postgres: rollen finns inte, inget att läcka till
                for privilege in ("SELECT", "UPDATE", "INSERT"):
                    cur.execute(
                        "select has_table_privilege(%s, 'public.app_version_policy', %s)",
                        [role, privilege],
                    )
                    self.assertFalse(cur.fetchone()[0], f"{role} {privilege}")
