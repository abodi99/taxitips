"""
Tester för push-steget och favoriterna.

Tyngdpunkten ligger på de fall som går sönder TYST: ett filter som råkar
tysta allt, en notis som skickas två gånger, en favoritlista som tömmer sig
själv. Ingen av dem ger ett felmeddelande någonstans -- de ser ut som "det
var lugnt", vilket är exakt vad AGENTS.md §9 varnar för.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

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
    """En enhet utan databas -- matchningen ska gå att prova utan Supabase."""

    def __init__(self, prefs=None, label="Testbil"):
        self.id = uuid.uuid4()
        self.label = label
        self.token = f"tok-{self.id}"
        self.push_token = f"fcm-{self.id}"
        self.notify_prefs = prefs if prefs is not None else {}


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
        self.assertFalse(notify.match_device({}, o).ok)
        o.demand_score = thresholds.NOTIFY_SCORE_FLOOR
        self.assertTrue(notify.match_device({}, o).ok)

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
        self.assertEqual(
            notify.match_device({"enabled": False}, o).reason, "notifications_off"
        )
        self.assertEqual(
            notify.match_device({"types": {"line_paused": False}}, o).reason,
            "type_off:line_paused",
        )
        self.assertEqual(
            notify.match_device({"regions": ["skane"]}, o).reason,
            "region_not_chosen:sl",
        )
        elsewhere = opportunity(places=["Solna centrum"], region="sl")
        self.assertEqual(
            notify.match_device({"cities": ["Malmö"]}, elsewhere).reason,
            "city_not_chosen",
        )
        self.assertEqual(notify.match_device({}, o).reason, "match")


class PushCycleTests(TestCase):
    """Cykeln, med en injicerad transport -- inget nätverk, inget Firebase."""

    def setUp(self):
        self.sent = []

        def sender(*, token, title, body, data):
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

        def flaky(*, token, title, body, data):
            if token == broken.push_token:
                raise RuntimeError("nätverket dog")
            self.sent.append({"token": token})
            return {"ok": True}

        from unittest.mock import patch

        with patch.object(notify, "_devices", return_value=[broken, ok_device]):
            result = notify.run_push_cycle(sender=flaky)

        self.assertEqual(result["sent"], 1)
        self.assertEqual(result["failed"], 1)
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
        self.assertEqual(match.reason, "too_far")

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
