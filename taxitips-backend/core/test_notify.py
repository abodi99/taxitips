"""
Tester för push-steget och favoriterna.

Tyngdpunkten ligger på de fall som går sönder TYST: ett filter som råkar
tysta allt, en notis som skickas två gånger, en favoritlista som tömmer sig
själv. Ingen av dem ger ett felmeddelande någonstans -- de ser ut som "det
var lugnt", vilket är exakt vad AGENTS.md §9 varnar för.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.utils import timezone

from billing.models import Company
from core import notify, thresholds
from core.models import (
    Opportunity,
    OpportunityFavorite,
    PushDelivery,
    SeverityTier,
)


def opportunity(**kwargs) -> Opportunity:
    defaults = {
        "external_id": f"test:{uuid.uuid4()}",
        "kind": "transit",
        "mode": "train",
        "severity_tier": SeverityTier.VEHICLE_CANCELLED,
        "title": "Avgång inställd",
        "summary": "Avgången 08:00 från Lund C är inställd.",
        "demand_score": 70,
        "region": "skane",
        "places": ["Lund C"],
        "end_time": timezone.now() + timedelta(hours=2),
    }
    return Opportunity.objects.create(**{**defaults, **kwargs})


class FakeDevice:
    """
    En enhet utan databas -- matchningen ska gå att prova utan Supabase.

    `company_id` måste ändå peka på ett riktigt bolag: mottagarkontrollen strax
    före sändningen (fleet/push_gate.py) slår upp bolagets period, och en enhet
    utan bolag nekas -- vilket är rätt svar i produktion och fel i ett test av
    filterlogiken. `SupabaseCompanyMixin` skapar bolaget.
    """

    def __init__(self, prefs=None, label="Testbil", company_id=None):
        self.id = uuid.uuid4()
        self.label = label
        self.token = f"tok-{self.id}"
        self.push_token = f"fcm-{self.id}"
        self.company_id = company_id or SupabaseCompanyMixin.company_id
        # Skåne som standard: utan körområde får ingen enhet notiser (no_area),
        # och testernas tips ligger i Skåne om inget annat sägs.
        self.notify_prefs = prefs if prefs is not None else {"counties": ["12"]}


class SupabaseCompanyMixin:
    """
    Skapar den omanagerade `companies`-tabellen och ett aktivt bolag, av samma
    skäl som core/test_api.ApiTestCase: gränsen mellan Djangos tabeller och
    Supabases ska kosta en rad att korsa, så att den märks.
    """

    company_id = None

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.schema_editor() as editor:
            editor.create_model(Company)
        company = Company.objects.create(
            id=uuid.uuid4(), name="Testbolaget AB", join_code=str(uuid.uuid4())[:8],
            seats=5, status="active", created_at=timezone.now(),
            subscription_status="active",
        )
        SupabaseCompanyMixin.company_id = company.id

    @classmethod
    def tearDownClass(cls):
        SupabaseCompanyMixin.company_id = None
        with connection.schema_editor() as editor:
            editor.delete_model(Company)
        super().tearDownClass()


class TypeGateTests(TestCase):
    def test_unset_type_falls_back_to_catalog_default_not_off(self):
        """
        En ny enhet har en tom notify_prefs. Läses en saknad typ som
        "avstängd" börjar varje installation med noll notiser -- inklusive
        för den allvarligaste typen -- utan att föraren rört något.
        """
        self.assertTrue(notify.type_enabled({}, "line_paused"))
        self.assertTrue(notify.type_enabled(None, "vehicle_cancelled"))
        # Och en typ som är AV som standard förblir av.
        self.assertFalse(notify.type_enabled({}, "line_delayed"))

    def test_explicit_choice_beats_the_default(self):
        self.assertFalse(notify.type_enabled({"line_paused": False}, "line_paused"))
        self.assertTrue(notify.type_enabled({"line_delayed": True}, "line_delayed"))


class RegionGateTests(TestCase):
    def test_no_chosen_regions_lets_everything_through(self):
        self.assertTrue(notify.region_matches("sl", []))
        self.assertTrue(notify.region_matches("sl", None))

    def test_chosen_region_filters_other_counties(self):
        self.assertTrue(notify.region_matches("skane", ["skane", "sl"]))
        self.assertFalse(notify.region_matches("vt", ["skane", "sl"]))

    def test_tip_without_region_is_never_suppressed(self):
        """
        Vägtips skrivs utan region. Ett filter tar bort det vi VET ligger
        fel -- aldrig det vi inte kunnat placera.
        """
        self.assertTrue(notify.region_matches(None, ["skane"]))
        self.assertTrue(notify.region_matches("", ["skane"]))

    def test_rail_is_its_own_choice_not_part_of_a_county(self):
        """
        Järnvägen skrivs som region "rail" oavsett var stationen ligger --
        Trafikverkets tågdata har inget länsfält. Hade "rail" släppts igenom
        för alla hade "Skåne" i praktiken betytt "Skåne plus varje tåg i
        Sverige".
        """
        self.assertFalse(notify.region_matches("rail", ["skane"]))
        self.assertTrue(notify.region_matches("rail", ["skane", "rail"]))


class CityGateTests(TestCase):
    def test_loose_match_because_places_are_more_specific_than_cities(self):
        """`cities` bär "Malmö", `places` bär "Malmö C". Exakt likhet hade
        tyst aldrig matchat."""
        self.assertTrue(notify.places_match_cities(["Malmö C"], ["Malmö"]))
        self.assertTrue(notify.places_match_cities(["Lund"], ["Lund C"]))
        self.assertFalse(notify.places_match_cities(["Göteborg C"], ["Malmö"]))

    def test_unknown_place_is_let_through(self):
        """
        Mätt: 61% av aktiva tips saknar `places` helt. Att behandla "vi vet
        inte var" som "matchar inte din ort" hade tystat majoriteten av alla
        riktiga störningar för varje förare som valde en ort -- raka
        motsatsen till vad ortsvalet är till för.
        """
        self.assertTrue(notify.places_match_cities([], ["Malmö"]))
        self.assertTrue(notify.places_match_cities(None, ["Malmö"]))


class NotifyWorthyTests(TestCase):
    def test_weak_tiers_can_never_be_configured_into_a_push(self):
        """Grind 1 går inte att slå på. En förare ska inte kunna ställa in
        sig på att bli väckt av att en buss är fyra minuter sen."""
        o = opportunity(severity_tier=SeverityTier.VEHICLE_DELAYED, demand_score=99)
        match = notify.match_device({"types": {"vehicle_delayed": True}}, o)
        self.assertFalse(match.ok)
        self.assertEqual(match.reason, "not_notify_worthy")

    def test_score_floor_applies_within_a_worthy_tier(self):
        o = opportunity(severity_tier=SeverityTier.VEHICLE_CANCELLED, demand_score=49)
        skane = {"counties": ["12"]}
        self.assertEqual(notify.decide(skane, o).reason, "not_notify_worthy")
        o.demand_score = thresholds.NOTIFY_SCORE_FLOOR
        self.assertTrue(notify.decide(skane, o).ok)

    def test_stated_replacement_traffic_stops_the_push(self):
        """
        Mätt på fjorton kandidater i den lokala databasen: sex bar
        `has_alternative=True` -- återkommande ersättningsbusstrafik som
        källan själv skrivit ut. Ingen står strandsatt där, och en förare som
        kör dit gör en bomresa (invariant 2).
        """
        o = opportunity(demand_score=90, has_alternative=True)
        match = notify.match_device({}, o)
        self.assertFalse(match.ok)
        self.assertEqual(match.reason, "not_notify_worthy")

    def test_alternative_removes_the_push_but_not_the_tip(self):
        """Kortet ska ligga kvar i listan -- det är bara telefonen som tiger."""
        o = opportunity(demand_score=90, has_alternative=True)
        self.assertGreater(o.demand_score, 0)
        self.assertNotEqual(o.severity_tier, SeverityTier.IGNORE)
        self.assertNotIn(o, notify.candidates())


class MatchReasonTests(TestCase):
    def test_every_no_carries_a_reason(self):
        """Ett tyst nej går inte att felsöka -- det var så ägar-buggen kunde
        leva i ett halvår."""
        o = opportunity(region="sl", severity_tier=SeverityTier.LINE_PAUSED, demand_score=80)
        stockholm = {"counties": ["01"]}
        self.assertEqual(notify.decide({"enabled": False}, o).reason, "notifications_off")
        self.assertEqual(
            notify.decide({"types": {"line_paused": False}}, o).reason,
            "type_off:line_paused",
        )
        self.assertEqual(notify.decide({}, o).reason, "no_area")
        self.assertEqual(notify.decide({"regions": ["skane"]}, o).reason, "outside_area")
        elsewhere = opportunity(places=["Solna centrum"], region="sl")
        self.assertEqual(
            notify.decide({**stockholm, "cities": ["Malmö"]}, elsewhere).reason,
            "city_not_chosen",
        )
        unplaced = opportunity(region="rail", severity_tier=SeverityTier.LINE_PAUSED, demand_score=80)
        self.assertEqual(notify.decide(stockholm, unplaced).reason, "unplaced_tip")
        self.assertEqual(notify.decide(stockholm, o).reason, "match")

    def test_every_reason_code_is_documented(self):
        o = opportunity(region="sl", severity_tier=SeverityTier.LINE_PAUSED, demand_score=80)
        weak = opportunity(region="sl", severity_tier=SeverityTier.LINE_PAUSED, demand_score=1)
        codes = {
            notify.decide(prefs, tip).reason.split(":")[0]
            for prefs, tip in (
                ({}, weak), ({"enabled": False}, o), ({"types": {"line_paused": False}}, o),
                ({}, o), ({"counties": ["12"]}, o), ({"counties": ["01"]}, o),
                ({"counties": ["01"], "cities": ["Malmö"]}, opportunity(places=["Solna"], region="sl")),
            )
        }
        self.assertLessEqual(codes, set(notify.REASONS))


class AreaDecisionTests(TestCase):
    """
    P0-B2: ingen rikstäckande standardnotis. Utan körområde väcks ingen, och
    ett tips som inte går att placera i ett län pushas inte.
    """

    def test_no_area_means_no_push(self):
        o = opportunity(severity_tier=SeverityTier.LINE_PAUSED, demand_score=80)
        self.assertEqual(notify.decide({}, o).reason, "no_area")
        self.assertEqual(notify.decide({"regions": ["rail"]}, o).reason, "no_area")

    def test_a_tip_just_across_the_county_border_reaches_the_neighbour(self):
        arlanda = opportunity(
            region="sl", severity_tier=SeverityTier.LINE_PAUSED, demand_score=80, lat=59.6519, lon=17.9186,
        )
        self.assertTrue(notify.decide({"counties": ["03"]}, arlanda).ok)

    def test_stored_area_codes_are_used(self):
        o = opportunity(severity_tier=SeverityTier.LINE_PAUSED, demand_score=80, county_code="25", area_codes=["25"])
        self.assertEqual(notify.decide({"counties": ["12"]}, o).reason, "outside_area")
        self.assertTrue(notify.decide({"counties": ["25"]}, o).ok)

    def test_norrbotten_can_be_the_whole_area(self):
        kiruna = opportunity(
            region=None, severity_tier=SeverityTier.LINE_PAUSED, demand_score=80, lat=67.8558, lon=20.2253,
        )
        self.assertTrue(notify.decide({"counties": ["25"]}, kiruna).ok)


class PushCycleTests(SupabaseCompanyMixin, TestCase):
    """Cykeln, med en injicerad transport -- inget nätverk, inget Firebase."""

    def setUp(self):
        self.sent = []

        def sender(*, token, title, body, data, **_):
            self.sent.append({"token": token, "title": title, "body": body, "data": data})
            return {"ok": True}

        self.sender = sender

    def run_cycle(self, devices, **kwargs):
        from unittest.mock import patch

        with patch.object(notify, "_devices", return_value=devices):
            return notify.run_push_cycle(sender=self.sender, **kwargs)

    def test_sends_once_and_marks_notified_at(self):
        o = opportunity(severity_tier=SeverityTier.LINE_PAUSED, demand_score=80)
        device = FakeDevice()

        result = self.run_cycle([device])
        self.assertEqual(result["sent"], 1)
        o.refresh_from_db()
        self.assertIsNotNone(o.notified_at)

        # Andra varvet: samma störning får inte väcka samma förare igen.
        self.sent.clear()
        again = self.run_cycle([device])
        self.assertEqual(again["candidates"], 0)
        self.assertEqual(self.sent, [])

    def test_delivery_is_recorded_per_device_for_the_notification_list(self):
        o = opportunity(severity_tier=SeverityTier.LINE_PAUSED, demand_score=80)
        device = FakeDevice()
        self.run_cycle([device])

        delivery = PushDelivery.objects.get()
        self.assertEqual(delivery.device_token, device.token)
        self.assertEqual(delivery.opportunity_external_id, o.external_id)
        self.assertTrue(delivery.ok)
        # Ögonblicksbilden bär kortets innehåll, så listan överlever att
        # tipset gallras efter sju dagar.
        self.assertEqual(delivery.snapshot["title"], o.title)
        self.assertEqual(delivery.snapshot["demand_score"], 80)

    def test_a_device_that_filtered_it_out_gets_nothing_but_others_still_do(self):
        opportunity(region="sl", severity_tier=SeverityTier.LINE_PAUSED, demand_score=80)
        wants = FakeDevice({"regions": ["sl"]}, label="Stockholm")
        elsewhere = FakeDevice({"regions": ["skane"]}, label="Malmö")

        result = self.run_cycle([wants, elsewhere])
        self.assertEqual(result["sent"], 1)
        self.assertEqual(self.sent[0]["token"], wants.push_token)

    def test_notified_at_is_set_even_when_nobody_matched(self):
        """
        Annars får en förare som ändrar sina inställningar i morgon en notis
        om gårdagens störning -- tipset har passerat sin notisstund.
        """
        o = opportunity(severity_tier=SeverityTier.LINE_PAUSED, demand_score=80)
        result = self.run_cycle([FakeDevice({"enabled": False})])
        self.assertEqual(result["sent"], 0)
        o.refresh_from_db()
        self.assertIsNotNone(o.notified_at)

    def test_no_devices_at_all_leaves_the_tip_unnotified(self):
        """
        Skillnad mot fallet ovan: finns det inga enheter alls har ingen
        notisstund passerat. Att markera hade gjort att den första föraren
        som installerar appen tyst gick miste om allt dessförinnan.
        """
        o = opportunity(severity_tier=SeverityTier.LINE_PAUSED, demand_score=80)
        result = self.run_cycle([])
        self.assertEqual(result.get("skipped"), "no_devices")
        o.refresh_from_db()
        self.assertIsNone(o.notified_at)

    def test_a_broken_device_never_stops_the_batch(self):
        opportunity(severity_tier=SeverityTier.LINE_PAUSED, demand_score=80)
        ok_device = FakeDevice(label="Fungerar")
        broken = FakeDevice(label="Trasig")

        def flaky(*, token, title, body, data, **_):
            if token == broken.push_token:
                raise RuntimeError("nätverket dog")
            self.sent.append({"token": token})
            return {"ok": True}

        from unittest.mock import patch

        with patch.object(notify, "_devices", return_value=[broken, ok_device]):
            result = notify.run_push_cycle(sender=flaky)

        self.assertEqual(result["sent"], 1)
        # Ett undantag från transporten är tillfälligt: försöks igen, räknas inte som misslyckat.
        self.assertEqual(result["retrying"], 1)
        self.assertEqual(len(self.sent), 1)

    def test_push_title_leads_with_where_and_what(self):
        o = opportunity(places=["Malmö C"], severity_tier=SeverityTier.LINE_PAUSED)
        self.assertEqual(notify.push_title(o), "Malmö C: Hela linjen stoppad")
        # Utan plats får färdsättet bära raden -- råtiteln är ofta ett naket
        # "Inställd" utan sammanhang.
        o.places = []
        self.assertEqual(notify.push_title(o), "Tåg: Hela linjen stoppad")

    def test_push_body_does_not_repeat_the_next_departure(self):
        """Järnvägens summary skriver redan ut nästa avgång i sin egen text."""
        o = opportunity(
            summary="Avgången 08:00 är inställd. Nästa avgång går om 20 min.",
            next_departure_minutes=20,
        )
        self.assertEqual(notify.push_body(o).count("Nästa avgång"), 1)


class NotifyPrefsApiTests(TestCase):
    """Katalogerna serveras från ETT ställe -- appen och sändaren ska inte
    kunna ha olika uppfattning om vilka typer som finns."""

    def test_catalog_marks_which_types_can_actually_push(self):
        catalog = {t["id"]: t for t in notify.type_catalog()}
        self.assertTrue(catalog["line_paused"]["notifiable"])
        # Står kvar i listan, men ärligt märkt: den syns i flödet och väcker
        # aldrig telefonen. En rad som saknats hade lästs som bortglömd.
        self.assertFalse(catalog["line_delayed"]["notifiable"])

    def test_region_catalog_only_offers_counties_we_actually_poll(self):
        keys = {r["key"] for r in notify.region_catalog()}
        self.assertIn("skane", keys)
        self.assertIn("sl", keys)
        self.assertIn("vt", keys)
        self.assertIn("rail", keys)
        # Halland 404:ar hos Trafiklab. Att erbjuda länet hade varit ett
        # löfte vi inte kan hålla -- tystnaden hade lästs som "lugnt".
        labels = {r["label"] for r in notify.region_catalog()}
        self.assertNotIn("Halland", labels)

    def test_cities_by_region_scopes_towns_under_their_county(self):
        by_region = notify.cities_by_region()
        self.assertIn("Malmö", by_region["skane"])
        self.assertIn("Stockholm", by_region["sl"])
        # En Skåne-ort ska inte kunna väljas under Stockholm -- det hade
        # sett ut som ett filter men aldrig matchat rätt tips.
        self.assertNotIn("Malmö", by_region["sl"])


class FavoriteTests(TestCase):
    def test_favorite_survives_the_tip_being_purged(self):
        """
        `purge_old` tar bort tips efter sju dagar. En favoritlista som tömmer
        sig själv är värre än ingen favoritlista -- föraren minns att hen
        sparade något, inte att databasen har en retention.
        """
        o = opportunity(title="Sparat tips")
        fav = OpportunityFavorite.objects.create(
            owner_key="tok-1",
            opportunity=o,
            opportunity_external_id=o.external_id,
            snapshot=notify.snapshot_of(o),
        )
        o.delete()

        fav.refresh_from_db()
        self.assertIsNone(fav.opportunity)
        self.assertEqual(fav.snapshot["title"], "Sparat tips")

    def test_same_tip_cannot_be_favorited_twice_by_one_owner(self):
        from django.db import IntegrityError, transaction

        o = opportunity()
        OpportunityFavorite.objects.create(
            owner_key="tok-1", opportunity=o, opportunity_external_id=o.external_id
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            OpportunityFavorite.objects.create(
                owner_key="tok-1", opportunity=o, opportunity_external_id=o.external_id
            )

    def test_two_owners_can_favorite_the_same_tip(self):
        o = opportunity()
        OpportunityFavorite.objects.create(
            owner_key="tok-1", opportunity=o, opportunity_external_id=o.external_id
        )
        OpportunityFavorite.objects.create(
            owner_key="user:abc", opportunity=o, opportunity_external_id=o.external_id
        )
        self.assertEqual(OpportunityFavorite.objects.count(), 2)


class ReachTests(TestCase):
    """
    Fjärde grinden. Skriven efter en mätning, inte en aning: en förare i
    Malmö som valt "Skåne + järnväg" fick i den lokala databasen en notis om
    ett inställt tåg i Örnsköldsvik -- 1 400 km bort, och något appens egen
    lista aldrig hade visat (marknadsradien är 150 km).
    """

    MALMO = (55.605, 13.0038)
    ORNSKOLDSVIK = (63.29, 18.72)

    def test_a_tip_you_could_never_see_in_the_list_never_wakes_you(self):
        o = opportunity(
            region="rail",
            severity_tier=SeverityTier.VEHICLE_CANCELLED,
            demand_score=80,
            lat=self.ORNSKOLDSVIK[0],
            lon=self.ORNSKOLDSVIK[1],
        )
        match = notify.match_device({"regions": ["skane", "rail"]}, o)
        self.assertFalse(match.ok)
        self.assertEqual(match.reason, "outside_area")

    def test_the_same_choice_still_delivers_trains_at_home(self):
        o = opportunity(
            region="rail",
            severity_tier=SeverityTier.VEHICLE_CANCELLED,
            demand_score=80,
            lat=self.MALMO[0],
            lon=self.MALMO[1],
        )
        self.assertTrue(notify.match_device({"regions": ["skane", "rail"]}, o).ok)

    def test_no_chosen_county_means_no_distance_gate(self):
        """Har föraren inte sagt var hen kör finns inget att mäta mot."""
        self.assertTrue(
            notify.within_reach(self.ORNSKOLDSVIK[0], self.ORNSKOLDSVIK[1], [])
        )

    def test_rail_alone_is_national_by_choice(self):
        """
        Väljer föraren BARA järnväg har hen inte angett någon geografi --
        "rail" har ingen ankarort. Då gäller ingen avståndsgräns, och det är
        ett medvetet val snarare än en lucka.
        """
        self.assertTrue(
            notify.within_reach(self.ORNSKOLDSVIK[0], self.ORNSKOLDSVIK[1], ["rail"])
        )

    def test_a_tip_without_coordinates_is_never_suppressed(self):
        self.assertTrue(notify.within_reach(None, None, ["skane"]))

    def test_list_matches_regions_mirrors_app_filter(self):
        # Marknadsnyckel matchar rakt; rail nära ankaret ingår; långt bort bort.
        self.assertTrue(
            notify.list_matches_regions("sl", 59.33, 18.07, ["sl"])
        )
        self.assertFalse(
            notify.list_matches_regions("skane", 55.60, 13.00, ["sl"])
        )
        self.assertTrue(
            notify.list_matches_regions("rail", 59.33, 18.07, ["sl"])
        )
        self.assertFalse(
            notify.list_matches_regions(
                "rail", self.ORNSKOLDSVIK[0], self.ORNSKOLDSVIK[1], ["sl"]
            )
        )
        self.assertTrue(
            notify.list_matches_regions("sl", None, None, ["sl"])
        )
        self.assertFalse(
            notify.list_matches_regions("sl", None, None, ["vt"])
        )


class OutboxTests(SupabaseCompanyMixin, TestCase):
    """
    P0-B3: köa först, skicka sedan. Varken en krasch, ett tillfälligt fel eller
    en död token ger dubbletter, tappade notiser eller en tystad telefon.
    """

    def setUp(self):
        self.calls = []
        self.device = FakeDevice()
        self.tip = opportunity(severity_tier=SeverityTier.LINE_PAUSED, demand_score=80)

    def cycle(self, sender, now=None):
        from unittest.mock import patch

        with patch.object(notify, "_devices", return_value=[self.device]):
            return notify.run_push_cycle(sender=sender, now=now)

    def ok(self, **message):
        self.calls.append(message)
        return {"ok": True}

    def queued_as(self, status, next_attempt_at):
        PushDelivery.objects.create(
            opportunity=self.tip, opportunity_external_id=self.tip.external_id,
            device_id=self.device.id, device_token=self.device.token, title="t", body="b",
            snapshot={}, ok=False, status=status, next_attempt_at=next_attempt_at,
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        Opportunity.objects.filter(pk=self.tip.pk).update(notified_at=timezone.now())

    def test_a_crash_after_queueing_neither_loses_nor_duplicates(self):
        from unittest.mock import patch

        with patch.object(notify, "_send_due", side_effect=RuntimeError("workern dog")):
            with self.assertRaises(RuntimeError):
                self.cycle(self.ok)
        self.assertEqual(PushDelivery.objects.get().status, PushDelivery.Status.PENDING)
        self.cycle(self.ok)
        self.cycle(self.ok)
        self.assertEqual(len(self.calls), 1)

    def test_a_delivery_left_sending_by_a_killed_worker_is_sent_once_after_the_lease(self):
        self.queued_as(PushDelivery.Status.SENDING, timezone.now() - timedelta(seconds=1))
        self.cycle(self.ok)
        self.cycle(self.ok)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(PushDelivery.objects.get().status, PushDelivery.Status.SENT)

    def test_a_delivery_within_its_lease_is_left_alone(self):
        self.queued_as(PushDelivery.Status.SENDING, timezone.now() + timedelta(minutes=4))
        self.cycle(self.ok)
        self.assertEqual(self.calls, [])

    def test_a_transient_error_is_retried_and_then_sent(self):
        responses = [{"ok": False, "status": 503, "body": "Service Unavailable"}, {"ok": True}]

        def flaky(**message):
            self.calls.append(message)
            return responses.pop(0)

        self.assertEqual(self.cycle(flaky)["retrying"], 1)
        later = timezone.now() + notify.PUSH_RETRY_BACKOFF[0] + timedelta(seconds=1)
        self.assertEqual(self.cycle(flaky, now=later)["sent"], 1)
        delivery = PushDelivery.objects.get()
        self.assertEqual((delivery.status, delivery.attempts, delivery.ok), (PushDelivery.Status.SENT, 2, True))

    def test_nothing_is_sent_after_the_notification_has_expired(self):
        self.cycle(lambda **message: {"ok": False, "status": 503, "body": ""})
        much_later = timezone.now() + notify.PUSH_TTL + timedelta(minutes=1)
        result = self.cycle(self.ok, now=much_later)
        self.assertEqual(result["expired"], 1)
        self.assertEqual(self.calls, [])
        self.assertEqual(PushDelivery.objects.get().status, PushDelivery.Status.EXPIRED)

    def test_an_unregistered_token_is_cleared_and_not_retried(self):
        from unittest.mock import patch

        dead = {"ok": False, "status": 404, "body": json.dumps({"error": {
            "status": "NOT_FOUND",
            "details": [{"@type": "type.googleapis.com/google.firebase.fcm.v1.FcmError", "errorCode": "UNREGISTERED"}],
        }})}
        with patch.object(notify, "clear_push_token") as clear:
            result = self.cycle(lambda **message: dead)
        clear.assert_called_once_with(self.device.id)
        self.assertEqual(result["failed"], 1)
        self.assertEqual(PushDelivery.objects.get().status, PushDelivery.Status.FAILED)

    def test_a_payload_error_does_not_silence_a_working_phone(self):
        from unittest.mock import patch

        bad = {"ok": False, "status": 400, "body": json.dumps({"error": {
            "status": "INVALID_ARGUMENT", "message": "Invalid value at 'message.data[0].value'",
        }})}
        with patch.object(notify, "clear_push_token") as clear:
            result = self.cycle(lambda **message: bad)
        clear.assert_not_called()
        self.assertEqual(result["failed"], 1)

    def test_the_message_carries_a_collapse_key_and_a_ttl(self):
        self.cycle(self.ok)
        message = self.calls[0]
        self.assertEqual(message["collapse_key"], notify.collapse_key(self.tip.external_id))
        self.assertGreater(message["ttl_seconds"], 0)
        self.assertLessEqual(message["ttl_seconds"], notify.PUSH_TTL.total_seconds())


class MunicipalityDecisionTests(TestCase):
    def test_a_municipality_is_the_whole_area_for_its_county(self):
        stockholm = opportunity(region="sl", severity_tier=SeverityTier.LINE_PAUSED, demand_score=80, lat=59.3326, lon=18.0649)
        sodertalje = opportunity(region="sl", severity_tier=SeverityTier.LINE_PAUSED, demand_score=80, lat=59.1955, lon=17.6253)
        prefs = {"counties": ["01"], "municipalities": ["0180"]}
        self.assertTrue(notify.decide(prefs, stockholm).ok)
        self.assertEqual(notify.decide(prefs, sodertalje).reason, "outside_area")
