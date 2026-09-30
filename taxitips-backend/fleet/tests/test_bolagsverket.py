"""
Bolagsverket (fleet/bolagsverket.py): tolkningen av registrets svar, och att
registreringen och säljflödet hämtar det användaren annars hade skrivit.

Svaren nedan har samma form som API:t gav 2026-09-27 (AB Volvo, och ett
nummer som inte finns), avkortade till de fält vi läser.
"""

from __future__ import annotations

import copy
import uuid
from unittest import mock

from django.core.cache import cache
from django.test import Client, override_settings

from billing.models import Company
from fleet import bolagsverket, registration, sales
from fleet.models import CompanyProfile
from fleet.tests.base import FleetTestCase

VOLVO = {"organisationer": [{
    "avregistreradOrganisation": None,
    "avregistreringsorsak": None,
    "juridiskForm": {"kod": "49", "klartext": "Övriga aktiebolag", "dataproducent": "SCB", "fel": None},
    "naringsgrenOrganisation": {"sni": [
        {"kod": "70100", "klartext": "Verksamheter som utövas av huvudkontor"},
        {"kod": "     ", "klartext": ""},
    ], "dataproducent": "SCB", "fel": None},
    "organisationsdatum": {"registreringsdatum": "1915-05-05", "dataproducent": "Bolagsverket", "fel": None},
    "organisationsform": {"kod": "AB", "klartext": "Aktiebolag", "dataproducent": "Bolagsverket", "fel": None},
    "organisationsidentitet": {"identitetsbeteckning": "5560125790"},
    "organisationsnamn": {"dataproducent": "Bolagsverket", "fel": None, "organisationsnamnLista": [
        {"namn": "Aktiebolaget Volvo",
         "organisationsnamntyp": {"kod": "FORETAGSNAMN", "klartext": "Företagsnamn"}},
    ]},
    "pagaendeAvvecklingsEllerOmstruktureringsforfarande": None,
    "postadressOrganisation": {"postadress": {
        "postnummer": "40508", "coAdress": None, "land": None, "postort": "GÖTEBORG",
        "utdelningsadress": "VAL 1",
    }, "dataproducent": "Bolagsverket", "fel": None},
    "verksamOrganisation": {"kod": "JA", "dataproducent": "SCB", "fel": None},
}]}

MISSING_ERROR = {"typ": "ORGANISATION_FINNS_EJ", "felBeskrivning": "Begärd organisation finns inte"}
NOT_FOUND = {"organisationer": [{
    "avregistreradOrganisation": {"avregistreringsdatum": None, "fel": MISSING_ERROR},
    "organisationsnamn": {"fel": MISSING_ERROR, "organisationsnamnLista": []},
    "postadressOrganisation": {"fel": MISSING_ERROR, "postadress": None},
}]}


def deregistered() -> dict:
    body = copy.deepcopy(VOLVO)
    row = body["organisationer"][0]
    row["avregistreradOrganisation"] = {"avregistreringsdatum": "2024-03-01", "fel": None}
    row["avregistreringsorsak"] = {"kod": "KK", "klartext": "Konkurs"}
    return body


def in_bankruptcy() -> dict:
    body = copy.deepcopy(VOLVO)
    body["organisationer"][0]["pagaendeAvvecklingsEllerOmstruktureringsforfarande"] = [
        {"kod": "KK", "klartext": "Konkurs", "fromDatum": "2026-08-01"},
    ]
    return body


def registry(body, status=200):
    """Bolagsverket svarar med `body` -- utan nätverk och utan token."""
    return mock.patch("fleet.bolagsverket.fetch_raw", return_value=(status, body))


CONFIGURED = override_settings(BOLAGSVERKET_CLIENT_ID="id", BOLAGSVERKET_CLIENT_SECRET="secret")


class ParseTests(FleetTestCase):
    def test_a_registered_company(self):
        info = bolagsverket.parse("5560125790", VOLVO)
        self.assertTrue(info.found)
        self.assertEqual(info.name, "Aktiebolaget Volvo")
        self.assertEqual((info.legal_form, info.legal_form_code), ("Aktiebolag", "AB"))
        self.assertEqual(info.status, "active")
        self.assertEqual(info.registered_at, "1915-05-05")
        # Postnumret med mellanslag och orten som den skrivs, inte i versaler.
        self.assertEqual(info.address, {
            "line1": "VAL 1", "postal_code": "405 08", "city": "Göteborg", "country": "SE",
        })
        # Tomma SNI-platser räknas inte som branscher.
        self.assertEqual(info.sni, [{"code": "70100", "text": "Verksamheter som utövas av huvudkontor"}])
        self.assertFalse(info.blocks_signup)

    def test_a_number_that_is_not_registered(self):
        info = bolagsverket.parse("0000000000", NOT_FOUND)
        self.assertFalse(info.found)
        self.assertEqual(info.name, "")

    def test_a_deregistered_company_blocks_signup(self):
        info = bolagsverket.parse("5560125790", deregistered())
        self.assertEqual(info.status, "deregistered")
        self.assertIn("Konkurs", info.status_text)
        self.assertTrue(info.blocks_signup)

    def test_an_ongoing_bankruptcy_is_shown_but_does_not_block(self):
        info = bolagsverket.parse("5560125790", in_bankruptcy())
        self.assertEqual(info.status, "winding_up")
        self.assertIn("Konkurs", info.status_text)
        self.assertFalse(info.blocks_signup)


@CONFIGURED
class LookupTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def test_answers_are_cached(self):
        with registry(VOLVO) as fetch:
            bolagsverket.lookup("5560125790")
            bolagsverket.lookup("5560125790")
        self.assertEqual(fetch.call_count, 1)

    def test_an_outage_is_not_a_not_found(self):
        with registry("Bad Gateway", status=502):
            self.assertIsNone(bolagsverket.try_lookup("5560125790"))

    def test_nothing_is_fetched_without_credentials(self):
        with self.settings(BOLAGSVERKET_CLIENT_ID=""), registry(VOLVO) as fetch:
            self.assertIsNone(bolagsverket.try_lookup("5560125790"))
        fetch.assert_not_called()

    def test_the_client_address_is_the_one_the_proxy_added(self):
        from django.test import RequestFactory

        request = RequestFactory().get("/", headers={"X-Forwarded-For": "6.6.6.6, 10.0.0.9"})
        self.assertEqual(bolagsverket.client_ip(request), "10.0.0.9")


@CONFIGURED
class RegistrationTests(FleetTestCase):
    """Självregistrering i appen: användaren anger så lite som möjligt."""

    def setUp(self):
        super().setUp()
        cache.clear()

    def register(self, **overrides):
        args = {
            "user_id": str(uuid.uuid4()), "email": "agare@volvo.test",
            "org_number": "556012-5790", "company_name": "", "contact_name": "Anna",
            "contact_phone": "070-812 34 91",
        }
        args.update(overrides)
        return registration.register(**args)

    def test_only_the_org_number_is_needed_for_the_company(self):
        with registry(VOLVO):
            result = self.register()
        self.assertEqual(result.company.name, "Aktiebolaget Volvo")
        profile = CompanyProfile.objects.get(company_id=result.company.id)
        self.assertEqual(profile.legal_name, "Aktiebolaget Volvo")
        self.assertEqual(profile.billing_address["city"], "Göteborg")
        self.assertEqual(profile.registry["status"], "active")
        self.assertIsNotNone(profile.registry_checked_at)
        self.assertIn("Bolagsverket", profile.verification_note)

    def test_the_name_the_customer_uses_wins_but_the_legal_name_is_the_registrys(self):
        with registry(VOLVO):
            result = self.register(company_name="Volvo Taxi")
        self.assertEqual(result.company.name, "Volvo Taxi")
        self.assertEqual(CompanyProfile.objects.get(company_id=result.company.id).legal_name, "Aktiebolaget Volvo")

    def test_a_deregistered_company_gets_no_account(self):
        with registry(deregistered()), self.assertRaises(sales.SalesError) as caught:
            self.register()
        self.assertEqual(caught.exception.reason, "company_deregistered")
        self.assertFalse(Company.objects.filter(org_number="5560125790").exists())

    def test_a_sole_trader_the_registry_lacks_needs_a_name(self):
        # Enskild firma: personnumret är organisationsnumret. Ett aktiebolag som
        # registret saknar nekas i stället (test_trial_scope.py).
        with registry(NOT_FOUND), self.assertRaises(sales.SalesError) as caught:
            self.register(org_number="811218-9876")
        self.assertEqual(caught.exception.reason, "name_required")
        with registry(NOT_FOUND):
            result = self.register(org_number="811218-9876", company_name="Anna Taxi")
        self.assertEqual(result.company.name, "Anna Taxi")
        self.assertFalse(CompanyProfile.objects.get(company_id=result.company.id).registry["found"])

    def test_an_outage_never_stops_a_signup(self):
        with registry("Service Unavailable", status=503):
            result = self.register(company_name="Anna Taxi")
        profile = CompanyProfile.objects.get(company_id=result.company.id)
        self.assertEqual(profile.registry, {})
        self.assertIsNone(profile.registry_checked_at)


@CONFIGURED
class PublicLookupTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.client = Client()

    def get(self, org, ip="1.2.3.4"):
        return self.client.get("/api/fleet/registry", {"orgNumber": org}, REMOTE_ADDR=ip)

    def test_shows_the_public_facts_and_nothing_about_being_a_customer(self):
        self.make_company(name="Volvo hos oss", org_number="5560125790")
        with registry(VOLVO):
            body = self.get("556012-5790").json()
        self.assertEqual(body["registry"]["name"], "Aktiebolaget Volvo")
        self.assertEqual(body["registry"]["city"], "Göteborg")
        self.assertEqual(body["registry"]["line1"], "VAL 1")
        self.assertEqual(body["registry"]["postalCode"], "405 08")
        self.assertNotIn("Volvo hos oss", str(body))
        self.assertNotIn("existing", str(body).lower())

    def test_an_invalid_number_never_reaches_the_registry(self):
        with registry(VOLVO) as fetch:
            body = self.get("556012-5791").json()
        self.assertFalse(body["valid"])
        fetch.assert_not_called()

    def test_one_address_cannot_use_us_as_a_free_proxy(self):
        with registry(VOLVO):
            for _ in range(30):
                self.get("556012-5790")
            refused = self.get("556012-5790")
            other = self.get("556012-5790", ip="5.6.7.8")
        self.assertEqual(refused.json()["reason"], "rate_limited")
        self.assertTrue(other.json()["ok"])


@CONFIGURED
class SalesTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def test_the_sellers_lookup_includes_the_registry(self):
        with registry(VOLVO):
            result = sales.lookup("556012-5790")
        self.assertEqual(result["registry"]["name"], "Aktiebolaget Volvo")
        self.assertEqual(result["registryError"], "")

    def test_a_new_company_gets_name_and_address_from_the_registry(self):
        with registry(VOLVO):
            company = sales.create_company(
                name="", org_number="556012-5790", contact_name="Anna",
                contact_email="anna@volvo.test", verification_note="Ringde växeln.",
                actor_user_id=None,
            )
        profile = CompanyProfile.objects.get(company_id=company.id)
        self.assertEqual(company.name, "Aktiebolaget Volvo")
        self.assertEqual(profile.billing_address["postal_code"], "405 08")

    def test_an_address_the_seller_entered_is_kept(self):
        with registry(VOLVO):
            company = sales.create_company(
                name="Volvo", org_number="556012-5790", contact_name="Anna",
                contact_email="anna@volvo.test", verification_note="Ringde växeln.",
                billing_address={"line1": "Fakturavägen 1", "postalCode": "111 22", "city": "Stockholm"},
                actor_user_id=None,
            )
        profile = CompanyProfile.objects.get(company_id=company.id)
        self.assertEqual(profile.billing_address["city"], "Stockholm")
        self.assertEqual(profile.legal_name, "Aktiebolaget Volvo")
