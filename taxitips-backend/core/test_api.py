"""
Tester för förar-API:t (core/api.py).

Tyngdpunkten ligger på gränserna, inte på serialiseringen: vem som får se
data, vad marknadshorisonten släpper igenom, och att feedback faktiskt
landar i en rad. Det sista är inte en formalitet -- den gamla vägen
(alert_feedback mot alerts) misslyckades tyst på främmande nyckel för varje
tips appen visade, och ingen tabell och ingen logg sa något om det.

De tre domäntabellerna (companies, devices, company_members) är
managed=False -- Django skapar dem inte i testdatabasen. Här skapas de
explicit i setUpClass, vilket är avsiktligt synligt: gränsen mellan "Django
äger pipeline-tabellerna" och "Supabase äger domäntabellerna" ska kosta en
rad att korsa, så att den märks.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import timedelta

from django.core.cache import cache
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from billing.models import Company, CompanyMember, Device
from core.models import Opportunity, OpportunityFeedback, SeverityTier

JWT_SECRET = "test-secret-at-least-32-characters-long!"
DEVICE_TOKEN = "device-token-abc"
MALMO = {"lat": 55.604981, "lon": 13.003822}


def make_jwt(sub: str, secret: str = JWT_SECRET, alg: str = "HS256", exp_offset: int = 3600) -> str:
    def seg(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    head = seg({"alg": alg, "typ": "JWT"})
    body = seg({"sub": sub, "exp": int(time.time()) + exp_offset})
    if alg == "none":
        return f"{head}.{body}."
    sig = hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"


def opportunity(**overrides) -> Opportunity:
    now = timezone.now()
    fields = {
        "external_id": f"test:{uuid.uuid4()}",
        "kind": "transit",
        "mode": "train",
        "severity_tier": SeverityTier.LINE_PAUSED,
        "title": "Linjen är stoppad",
        "summary": "Ingen trafik.",
        "lat": 55.6092,
        "lon": 13.0007,
        "region": "skane",
        "start_time": now - timedelta(minutes=10),
        "end_time": now + timedelta(hours=1),
        "demand_score": 85,
        "reasons": ["stoppad linje"],
        "rule_id": "train.line_paused",
    }
    fields.update(overrides)
    return Opportunity.objects.create(**fields)


class ApiTestCase(TestCase):
    """Bas: skapar de omanagerade domäntabellerna och ett aktivt bolag."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.schema_editor() as editor:
            for model in (Company, Device, CompanyMember):
                editor.create_model(model)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as editor:
            for model in (CompanyMember, Device, Company):
                editor.delete_model(model)
        super().tearDownClass()

    def setUp(self):
        # Flödescachen lever i processen; ett test får inte se förra testets svar.
        cache.clear()
        self.client = Client()
        self.company = Company.objects.create(
            id=uuid.uuid4(), name="Taxi Demo AB", join_code=str(uuid.uuid4())[:8],
            seats=5, status="trial", created_at=timezone.now(),
            subscription_status="inactive",
        )
        self.device = Device.objects.create(
            id=uuid.uuid4(), company_id=self.company.id, token=DEVICE_TOKEN,
            label="Anna", kind="driver", notify_prefs={},
        )

    def get_alerts(self, token=DEVICE_TOKEN, **params):
        return self.client.get(
            "/api/alerts", {**MALMO, **params},
            headers={"x-device-token": token} if token else {},
        ).json()


class EntitlementTests(ApiTestCase):
    def test_active_company_sees_alerts(self):
        opportunity()
        body = self.get_alerts()
        self.assertTrue(body["entitled"])
        self.assertEqual(len(body["alerts"]), 1)

    def test_unknown_token_gets_empty_feed_with_a_reason(self):
        opportunity()
        body = self.get_alerts(token="not-a-token")
        # Tomt flöde, inte 403 -- samma svar som RPC:ns '[]'. Men skälet
        # ska finnas, annars är "inga tips" och "du är utelåst" samma sak
        # på skärmen.
        self.assertEqual(body["alerts"], [])
        self.assertEqual(body["reason"], "unknown_device_token")

    def test_cancelled_company_is_locked_out(self):
        opportunity()
        Company.objects.filter(id=self.company.id).update(
            status="canceled", subscription_status="canceled"
        )
        self.assertEqual(self.get_alerts()["alerts"], [])

    def test_paying_company_with_lapsed_status_still_entitled(self):
        # subscription_status är den avgörande, precis som i SQL-versionen:
        # ett bolag vars trial gått ut men som betalar ska inte låsas ute.
        opportunity()
        Company.objects.filter(id=self.company.id).update(
            status="expired", subscription_status="active"
        )
        self.assertEqual(len(self.get_alerts()["alerts"]), 1)

    @override_settings(SUPABASE_JWT_SECRET=JWT_SECRET)
    def test_logged_in_owner_without_device_is_entitled(self):
        # Buggen 20260902000005 rättade: en ägare utan parad enhet såg
        # tomt, vilket inte gick att skilja från "inga störningar".
        opportunity()
        user_id = uuid.uuid4()
        CompanyMember.objects.create(
            id=uuid.uuid4(), company_id=self.company.id, user_id=user_id,
            role="owner", status="active", created_at=timezone.now(),
        )
        body = self.client.get(
            "/api/alerts", MALMO,
            headers={"Authorization": f"Bearer {make_jwt(str(user_id))}"},
        ).json()
        self.assertTrue(body["entitled"])
        self.assertEqual(len(body["alerts"]), 1)

    @override_settings(SUPABASE_JWT_SECRET=JWT_SECRET)
    def test_forged_and_expired_tokens_are_rejected(self):
        opportunity()
        user_id = uuid.uuid4()
        CompanyMember.objects.create(
            id=uuid.uuid4(), company_id=self.company.id, user_id=user_id,
            role="owner", status="active", created_at=timezone.now(),
        )
        for label, token in [
            ("fel hemlighet", make_jwt(str(user_id), secret="wrong-secret-wrong-secret-wrong!")),
            ("alg: none", make_jwt(str(user_id), alg="none")),
            ("utgången", make_jwt(str(user_id), exp_offset=-60)),
        ]:
            with self.subTest(label):
                body = self.client.get(
                    "/api/alerts", MALMO,
                    headers={"Authorization": f"Bearer {token}"},
                ).json()
                self.assertFalse(body["entitled"], label)


class AsymmetricJwtTests(ApiTestCase):
    """
    Supabase signerar numera med ES256 och en roterande nyckel, inte med
    den delade HS256-hemligheten. En verifiering som bara tog HS256 släppte
    igenom exakt NOLL inloggade ägare -- och felet syntes som "inga
    störningar just nu", precis som buggen 20260902000005 rättade en gång.
    """

    def setUp(self):
        super().setUp()
        from cryptography.hazmat.primitives.asymmetric import ec

        import core.entitlement as ent

        self.key = ec.generate_private_key(ec.SECP256R1())
        numbers = self.key.public_key().public_numbers()

        def b64(n):
            return base64.urlsafe_b64encode(n.to_bytes(32, "big")).decode().rstrip("=")

        ent._jwks_cache.clear()
        ent._jwks_cache["test-kid"] = {
            "kty": "EC", "crv": "P-256", "alg": "ES256", "kid": "test-kid",
            "x": b64(numbers.x), "y": b64(numbers.y),
        }
        self.addCleanup(ent._jwks_cache.clear)

        self.user_id = uuid.uuid4()
        CompanyMember.objects.create(
            id=uuid.uuid4(), company_id=self.company.id, user_id=self.user_id,
            role="owner", status="active", created_at=timezone.now(),
        )

    def es256(self, sub=None, exp_offset=3600, kid="test-kid"):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec, utils

        def seg(data):
            return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

        head = seg({"alg": "ES256", "typ": "JWT", "kid": kid})
        body = seg({"sub": str(sub or self.user_id), "exp": int(time.time()) + exp_offset})
        der = self.key.sign(f"{head}.{body}".encode(), ec.ECDSA(hashes.SHA256()))
        r, s_ = utils.decode_dss_signature(der)
        raw = r.to_bytes(32, "big") + s_.to_bytes(32, "big")
        return f"{head}.{body}.{base64.urlsafe_b64encode(raw).decode().rstrip('=')}"

    def get(self, token):
        return self.client.get(
            "/api/alerts", MALMO, headers={"Authorization": f"Bearer {token}"}
        ).json()

    def test_an_es256_token_signed_by_the_published_key_is_accepted(self):
        opportunity()
        body = self.get(self.es256())
        self.assertTrue(body["entitled"])
        self.assertEqual(len(body["alerts"]), 1)

    def test_a_token_signed_by_another_key_is_rejected(self):
        from cryptography.hazmat.primitives.asymmetric import ec

        opportunity()
        self.key = ec.generate_private_key(ec.SECP256R1())  # fel nyckel
        self.assertFalse(self.get(self.es256())["entitled"])

    # SUPABASE_URL tomt: en okänd kid får annars testet att gå ut på
    # nätet efter JWKS. Testet handlar om avvisningen, inte om hämtningen.
    @override_settings(SUPABASE_URL="")
    def test_an_unknown_kid_is_rejected(self):
        opportunity()
        self.assertFalse(self.get(self.es256(kid="fabricerad"))["entitled"])

    def test_an_expired_es256_token_is_rejected(self):
        opportunity()
        self.assertFalse(self.get(self.es256(exp_offset=-60))["entitled"])

    def test_alg_none_is_still_refused(self):
        opportunity()
        self.assertFalse(self.get(make_jwt(str(self.user_id), alg="none"))["entitled"])


class MarketHorizonTests(ApiTestCase):
    def test_distant_opportunity_is_outside_the_market(self):
        opportunity(title="Göteborgståg", lat=57.7089, lon=11.9746)  # ~230 km
        self.assertEqual(self.get_alerts()["alerts"], [])

    def test_national_feed_keeps_distant_opportunity_and_distance(self):
        opportunity(title="Göteborgståg", lat=57.7089, lon=11.9746)
        body = self.get_alerts(all="1")
        self.assertEqual(len(body["alerts"]), 1)
        self.assertGreater(body["alerts"][0]["distance_km"], 200)

    def test_selected_regions_expand_market_past_gps_bubble(self):
        # Malmö-GPS + filter Stockholm/Göteborg måste nå tips där -- annars
        # ser föraren "ingenting" trots att datan finns (listfilter-buggen).
        opportunity(
            title="SL-stopp",
            lat=59.3293,
            lon=18.0686,
            region="sl",
        )
        opportunity(
            title="Västtrafik-stopp",
            lat=57.7089,
            lon=11.9746,
            region="vt",
        )
        opportunity(title="Skånelokalt", lat=55.6092, lon=13.0007, region="skane")
        body = self.get_alerts(regions="sl,vt")
        titles = {a["title"] for a in body["alerts"]}
        self.assertEqual(titles, {"SL-stopp", "Västtrafik-stopp"})
        # Avståndsbadgen räknas fortfarande från telefonens GPS (Malmö).
        by_title = {a["title"]: a for a in body["alerts"]}
        self.assertGreater(by_title["SL-stopp"]["distance_km"], 400)

    def test_selected_regions_include_nearby_rail_not_distant(self):
        opportunity(
            title="Tåg Stockholm",
            lat=59.3300,
            lon=18.0600,
            region="rail",
        )
        opportunity(
            title="Tåg Örnsköldsvik",
            lat=63.2909,
            lon=18.7153,
            region="rail",
        )
        titles = {a["title"] for a in self.get_alerts(regions="sl")["alerts"]}
        self.assertEqual(titles, {"Tåg Stockholm"})

    def test_opportunity_without_coordinates_falls_back_to_region(self):
        opportunity(title="Skånetips utan koordinat", lat=None, lon=None, region="skane")
        opportunity(title="Stockholmstips utan koordinat", lat=None, lon=None, region="sl")
        titles = [a["title"] for a in self.get_alerts()["alerts"]]
        self.assertEqual(titles, ["Skånetips utan koordinat"])

    def test_region_fallback_works_outside_the_three_hardcoded_boxes(self):
        # get_smart_alerts kände bara till Skåne, Stockholm och Göteborg;
        # en förare i Falun såg aldrig ett koordinatlöst tips.
        opportunity(title="Dalatips", lat=None, lon=None, region="dt")
        body = self.get_alerts(lat=60.6065, lon=15.6355)
        self.assertEqual(body["homeRegion"], "dt")
        self.assertEqual([a["title"] for a in body["alerts"]], ["Dalatips"])

    def test_ignored_and_zero_score_rows_never_reach_a_driver(self):
        opportunity(severity_tier=SeverityTier.IGNORE)
        opportunity(demand_score=0)
        self.assertEqual(self.get_alerts()["alerts"], [])

    def test_expired_within_24h_is_shown_but_scored_zero(self):
        now = timezone.now()
        opportunity(end_time=now - timedelta(hours=2))
        alert = self.get_alerts()["alerts"][0]
        self.assertFalse(alert["is_active"])
        self.assertEqual(alert["worth_it_score"], 0)
        self.assertEqual(alert["level"], "low")

    def test_older_than_24h_is_gone(self):
        opportunity(end_time=timezone.now() - timedelta(hours=30))
        self.assertEqual(self.get_alerts()["alerts"], [])


class CorsTests(ApiTestCase):
    """
    Preflight. Appen skickar alltid X-Device-Token eller Authorization,
    vilket gör anropet icke-enkelt: webbläsaren frågar med OPTIONS först.
    Vyerna är @require_GET och svarade 405, så Flutter web fick "Failed to
    fetch" på varje hämtning -- osynligt i loggen, eftersom 405 är ett
    normalt svar, och osynligt för mobilappen, som aldrig gör en preflight.
    """

    ORIGIN = "http://localhost:5180"

    def options(self, path="/api/alerts", origin=None):
        return self.client.options(
            path,
            headers={
                "Origin": origin or self.ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-device-token",
            },
        )

    @override_settings(DEBUG=True)
    def test_preflight_is_answered_not_rejected(self):
        res = self.options()
        self.assertEqual(res.status_code, 204)
        self.assertEqual(res["Access-Control-Allow-Origin"], self.ORIGIN)
        self.assertIn("X-Device-Token", res["Access-Control-Allow-Headers"])

    @override_settings(DEBUG=True)
    def test_the_actual_request_also_carries_the_header(self):
        opportunity()
        res = self.client.get(
            "/api/alerts", MALMO,
            headers={"Origin": self.ORIGIN, "x-device-token": DEVICE_TOKEN},
        )
        self.assertEqual(res["Access-Control-Allow-Origin"], self.ORIGIN)

    @override_settings(DEBUG=False, APP_API_ALLOWED_ORIGINS=["http://localhost:4000"])
    def test_an_unlisted_origin_gets_no_headers_in_production(self):
        res = self.options(origin="https://någon-annan.example")
        self.assertNotIn("Access-Control-Allow-Origin", res)

    @override_settings(DEBUG=False, APP_API_ALLOWED_ORIGINS=["http://localhost:4000"])
    def test_localhost_is_not_waved_through_outside_debug(self):
        # localhost-undantaget i _cors() gäller BARA i DEBUG. I produktion
        # är svaren entitlement-gated data och listan är listan.
        self.assertNotIn("Access-Control-Allow-Origin", self.options())


class RoadContextTests(ApiTestCase):
    def test_road_events_are_context_not_list_items(self):
        # 129 vägrader mot 5 kollektivtrafiktips var det uppmätta
        # förhållandet i Skåne. I samma lista hade de begravt det enda som
        # var värt att köra till.
        opportunity(title="Stoppad linje", severity_tier=SeverityTier.LINE_PAUSED)
        opportunity(title="Vägarbete E22", kind="road",
                    severity_tier=SeverityTier.ROAD_WORK, mode="road", demand_score=5)
        body = self.get_alerts()
        self.assertEqual([a["title"] for a in body["alerts"]], ["Stoppad linje"])
        self.assertEqual([a["title"] for a in body["context"]], ["Vägarbete E22"])


class LevelTests(ApiTestCase):
    def test_level_and_push_gate_come_from_one_threshold(self):
        # `notify_worthy` svarar numera på samma fråga som push-steget
        # faktiskt ställer (thresholds.is_notify_worthy), inte bara på
        # poänggolvet. Två rader ändrade utfall när den kopplades ihop:
        #
        #   LINE_DELAYED/60 -- över golvet, men försening är inte en tier
        #   som får väcka någon. Kortet lovade en notis som aldrig kom.
        #   ROAD_ACCIDENT/90 -- fortfarande True: vägolyckor ÄR notisvärda,
        #   de får bara ligga i `context` i stället för i tipslistan.
        #
        # `level` är oförändrad -- den beskriver hur troligt det är att det
        # står folk där, vilket är en annan fråga än om telefonen ska ringa.
        cases = [
            (SeverityTier.LINE_PAUSED, 85, "high", True),
            (SeverityTier.VEHICLE_CANCELLED, 72, "high", True),
            (SeverityTier.VEHICLE_CANCELLED, 45, "medium", False),
            (SeverityTier.LINE_DELAYED, 60, "medium", False),
            (SeverityTier.ROAD_ACCIDENT_OR_CLOSURE, 90, "low", True),
        ]
        for tier, score, level, notify in cases:
            with self.subTest(f"{tier}/{score}"):
                Opportunity.objects.all().delete()
                cache.clear()  # nytt tips i samma test: flödescachen får inte svara med det förra
                opportunity(severity_tier=tier, demand_score=score)
                alert = self.get_alerts()["alerts"][0]
                self.assertEqual(alert["level"], level)
                self.assertEqual(alert["notify_worthy"], notify)

    def test_replacement_traffic_is_not_high_priority(self):
        # Planerad ersättningsbuss är fortfarande ett tips i listan, men
        # den får inte vara "high" -- då fyllde "Bara hög prio" skärmen
        # med ombyggnader där bussen redan går.
        opportunity(
            severity_tier=SeverityTier.VEHICLE_CANCELLED,
            demand_score=90,
            has_alternative=True,
        )
        alert = self.get_alerts()["alerts"][0]
        self.assertEqual(alert["level"], "low")
        self.assertFalse(alert["notify_worthy"])
        self.assertTrue(alert["has_alternative"])

    def test_config_endpoint_serves_the_same_numbers(self):
        config = self.client.get("/api/config").json()
        self.assertEqual(config["notifyScoreFloor"], 50)
        self.assertEqual(config["marketRadiusKm"], 150)
        self.assertEqual(config["feedLookbackHours"], 24)


class FeedbackTests(ApiTestCase):
    def post(self, payload, token=DEVICE_TOKEN):
        return self.client.post(
            "/api/feedback", data=json.dumps(payload),
            content_type="application/json",
            headers={"x-device-token": token} if token else {},
        )

    def test_feedback_is_stored_against_the_opportunity(self):
        o = opportunity()
        res = self.post({"opportunity_id": str(o.id), "verdict": "fare"})
        self.assertEqual(res.status_code, 200)
        row = OpportunityFeedback.objects.get()
        self.assertEqual(row.opportunity_id, o.id)
        self.assertEqual(row.device_token, DEVICE_TOKEN)

    def test_legacy_result_boolean_still_works(self):
        o = opportunity()
        self.post({"alert_id": str(o.id), "result": True})
        self.post({"alert_id": str(o.id), "result": False})
        self.assertEqual(
            sorted(OpportunityFeedback.objects.values_list("verdict", flat=True)),
            ["empty", "fare"],
        )

    def test_double_tap_is_idempotent(self):
        o = opportunity()
        self.post({"opportunity_id": str(o.id), "verdict": "heading"})
        res = self.post({"opportunity_id": str(o.id), "verdict": "heading"})
        self.assertTrue(res.json()["duplicate"])
        self.assertEqual(OpportunityFeedback.objects.count(), 1)

    def test_unknown_opportunity_and_bad_verdict_are_refused(self):
        o = opportunity()
        self.assertEqual(self.post({"opportunity_id": str(uuid.uuid4()), "verdict": "fare"}).status_code, 404)
        self.assertEqual(self.post({"opportunity_id": str(o.id), "verdict": "kanske"}).status_code, 400)

    def test_feedback_requires_entitlement(self):
        o = opportunity()
        self.assertEqual(self.post({"opportunity_id": str(o.id), "verdict": "fare"}, token="nope").status_code, 403)


class DetailTests(ApiTestCase):
    def test_detail_returns_the_source_event_behind_the_tip(self):
        from core.models import SourceEvent

        se = SourceEvent.objects.create(
            source="trafikverket_rail", external_id="tvr:test:1",
            raw={"Advertised": True}, active_to=timezone.now() + timedelta(hours=1),
        )
        o = opportunity(source_event_ids=[str(se.id)])
        body = self.client.get(
            f"/api/opportunities/{o.id}", headers={"x-device-token": DEVICE_TOKEN}
        ).json()
        self.assertEqual(body["opportunity"]["id"], str(o.id))
        self.assertEqual(body["source_events"][0]["source"], "trafikverket_rail")
        self.assertEqual(body["source_events"][0]["raw"], {"Advertised": True})

    def test_detail_is_gated(self):
        o = opportunity()
        res = self.client.get(f"/api/opportunities/{o.id}", headers={"x-device-token": "nope"})
        self.assertEqual(res.status_code, 403)


class AreaFeedTests(ApiTestCase):
    """P0-B2: utan position och körområde finns ingen rikstäckande lista."""

    def alerts_without_position(self, **params):
        return self.client.get("/api/alerts", params, headers={"x-device-token": DEVICE_TOKEN}).json()

    def test_no_position_and_no_area_asks_for_an_area(self):
        opportunity(title="Skånetips")
        opportunity(title="Stockholmstips", lat=59.3293, lon=18.0686, region="sl")
        body = self.alerts_without_position()
        self.assertTrue(body["needsArea"])
        self.assertEqual(body["alerts"], [])

    def test_chosen_counties_decide_without_position(self):
        opportunity(title="Skånetips")
        opportunity(title="Stockholmstips", lat=59.3293, lon=18.0686, region="sl")
        body = self.alerts_without_position(counties="01")
        self.assertFalse(body["needsArea"])
        self.assertEqual([a["title"] for a in body["alerts"]], ["Stockholmstips"])

    def test_the_saved_notification_area_is_used_when_the_app_sends_none(self):
        Device.objects.filter(id=self.device.id).update(notify_prefs={"regions": ["skane"]})
        opportunity(title="Skånetips")
        opportunity(title="Stockholmstips", lat=59.3293, lon=18.0686, region="sl")
        body = self.alerts_without_position()
        self.assertEqual([a["title"] for a in body["alerts"]], ["Skånetips"])

    def test_norrbotten_can_be_chosen(self):
        opportunity(title="Kiruna", lat=67.8558, lon=20.2253, region=None)
        body = self.alerts_without_position(counties="25")
        self.assertEqual([a["title"] for a in body["alerts"]], ["Kiruna"])


class EtagTests(ApiTestCase):
    """P0-C1: ett oförändrat flöde svarar 304 utan kropp; en ändring ger ny ETag."""

    def get(self, **headers):
        return self.client.get("/api/alerts", MALMO, headers={"x-device-token": DEVICE_TOKEN, **headers})

    def test_an_unchanged_feed_answers_304(self):
        opportunity(title="Tips")
        etag = self.get()["ETag"]
        again = self.get(**{"If-None-Match": etag})
        self.assertEqual(again.status_code, 304)
        self.assertEqual(again.content, b"")
        self.assertEqual(again["ETag"], etag)

    def test_a_changed_tip_changes_the_etag(self):
        tip = opportunity(title="Tips")
        etag = self.get()["ETag"]
        Opportunity.objects.filter(pk=tip.pk).update(title="Nytt läge")
        cache.clear()  # cachefönstret har gått
        again = self.get(**{"If-None-Match": etag})
        self.assertEqual(again.status_code, 200)
        self.assertNotEqual(again["ETag"], etag)

    def test_the_prefilter_never_drops_what_the_feed_would_show(self):
        opportunity(title="Nära", lat=55.6092, lon=13.0007)
        opportunity(title="Utan koordinat", lat=None, lon=None, region="skane")
        opportunity(title="Långt bort", lat=59.3293, lon=18.0686, region="sl")
        titles = {a["title"] for a in self.get().json()["alerts"]}
        self.assertEqual(titles, {"Nära", "Utan koordinat"})


class ContextLimitTests(ApiTestCase):
    """C1: väghändelserna kapas i svaret; totalen följer med."""

    def test_road_context_is_capped_in_the_response(self):
        from core import thresholds

        for i in range(thresholds.FEED_CONTEXT_LIMIT + 5):
            opportunity(title=f"Väg {i}", kind="road", mode="road", demand_score=10)
        body = self.get_alerts()
        self.assertEqual(len(body["context"]), thresholds.FEED_CONTEXT_LIMIT)
        self.assertEqual(body["contextTotal"], thresholds.FEED_CONTEXT_LIMIT + 5)


class SharedFeedCacheTests(ApiTestCase):
    """P1: flödet räknas en gång per filter inom cachefönstret, och filter blandas aldrig."""

    def test_the_same_filter_is_computed_once(self):
        from unittest import mock

        from core import api

        opportunity(title="Tips")
        with mock.patch.object(api, "feed_for", wraps=api.feed_for) as computed:
            first = self.get_alerts()
            second = self.get_alerts()
        self.assertEqual(computed.call_count, 1)
        self.assertEqual(first["alerts"], second["alerts"])

    def test_different_counties_are_never_mixed(self):
        opportunity(title="Skånetips")
        opportunity(title="Stockholmstips", lat=59.3293, lon=18.0686, region="sl")
        headers = {"x-device-token": DEVICE_TOKEN}
        skane = self.client.get("/api/alerts", {"counties": "12"}, headers=headers).json()
        stockholm = self.client.get("/api/alerts", {"counties": "01"}, headers=headers).json()
        self.assertEqual([a["title"] for a in skane["alerts"]], ["Skånetips"])
        self.assertEqual([a["title"] for a in stockholm["alerts"]], ["Stockholmstips"])


class MunicipalityFeedTests(ApiTestCase):
    """P1: en vald kommun förfinar länet -- Södertälje syns inte för den som valt Stockholms kommun."""

    def test_the_feed_follows_the_chosen_municipality(self):
        opportunity(title="Stockholm", lat=59.3326, lon=18.0649, region="sl")
        opportunity(title="Södertälje", lat=59.1955, lon=17.6253, region="sl")
        headers = {"x-device-token": DEVICE_TOKEN}
        county = self.client.get("/api/alerts", {"counties": "01"}, headers=headers).json()
        municipality = self.client.get("/api/alerts", {"counties": "01", "municipalities": "0180"}, headers=headers).json()
        self.assertEqual({a["title"] for a in county["alerts"]}, {"Stockholm", "Södertälje"})
        self.assertEqual([a["title"] for a in municipality["alerts"]], ["Stockholm"])
