"""
Tester för evenemangskalendern: Ticketmasters data, sluttiderna och vad
föraren får se.

Det viktigaste testet är test_end_local_time_is_a_copy_so_date_time_wins.
Ticketmasters `dates.end.localTime` är en kopia av starttiden -- den som läser
den fältet får ett evenemang som slutar samma minut som det börjar, och
utsläppsfönstret hamnar två timmar för tidigt.
"""

from __future__ import annotations

import datetime as dt
import json
from types import SimpleNamespace
from unittest import mock

from django.conf import settings
from django.core.management import call_command
from django.http import Http404
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from core.models import SourceStatus
from events import api, explain, ingest, live, matching, rights, timing
from events.models import Event
from events.sources import predicthq, ticketmaster

UTC = dt.timezone.utc


def tm_event(
    id="Z1", name="Konsert", *, local_date="2026-10-08", local_time="18:00:00",
    date_time="2026-10-08T16:00:00Z", end=None, tba=False, segment="Music", genre="Rock",
    sub_type=None, venue_name="Nalen", city="Stockholm", lat="59.3337", lon="18.0770",
    address="Regeringsgatan 74", status="onsale", multi=False, test=False,
):
    """Ett evenemang i Ticketmasters form, med samma nycklar som ett riktigt svar."""
    start = {"localDate": local_date, "dateTBD": False, "dateTBA": False, "timeTBA": tba, "noSpecificTime": False}
    if not tba:
        start.update(localTime=local_time, dateTime=date_time)
    venue = {"id": "V1", "city": {"name": city}, "address": {"line1": address},
             "location": {"latitude": lat, "longitude": lon}, "postalCode": "111 39"}
    if venue_name:
        venue["name"] = venue_name
    classification = {"primary": True, "segment": {"name": segment}, "genre": {"name": genre}}
    if sub_type:
        classification["subType"] = {"name": sub_type}
    dates = {"start": start, "timezone": "Europe/Stockholm", "status": {"code": status}, "spanMultipleDays": multi}
    if end:
        dates["end"] = end
    return {
        "id": id, "name": name, "url": f"https://www.ticketmaster.se/event/{id}", "test": test,
        "dates": dates, "classifications": [classification], "_embedded": {"venues": [venue]},
    }


def soon(id, name, days, hhmm, **kwargs):
    """Ett evenemang `days` dagar fram, kl `hhmm` svensk tid."""
    hour, minute = map(int, hhmm.split(":"))
    local = (timezone.now().astimezone(timing.STOCKHOLM) + dt.timedelta(days=days)).replace(
        hour=hour, minute=minute, second=0, microsecond=0,
    )
    return tm_event(
        id, name, local_date=local.date().isoformat(), local_time=local.strftime("%H:%M:%S"),
        date_time=local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), **kwargs,
    )


class NormalizeTests(SimpleTestCase):
    def test_end_local_time_is_a_copy_so_date_time_wins(self):
        # Författarbesök: Maja Larsson, 2026-10-08, exakt som Ticketmaster skickade det.
        event = tm_event(end={"localTime": "18:00:00", "dateTime": "2026-10-08T17:00:00Z",
                              "approximate": False, "noSpecificTime": False})
        row = ingest.build_row(event)
        self.assertEqual(row["end_at"], dt.datetime(2026, 10, 8, 17, 0, tzinfo=UTC))
        self.assertEqual(row["end_basis"], timing.BASIS_SOURCE)

    def test_concert_without_end_gets_an_estimate_that_says_so(self):
        row = ingest.build_row(tm_event(local_time="19:30:00", date_time="2026-10-08T17:30:00Z"))
        self.assertEqual(row["end_at"], dt.datetime(2026, 10, 8, 20, 15, tzinfo=UTC))
        self.assertEqual(row["end_basis"], timing.BASIS_ESTIMATED)
        self.assertIn("Uppskattad", row["end_note"])
        self.assertIn("Inte kalibrerad", row["end_note"])

    def test_end_before_start_is_ignored(self):
        row = ingest.build_row(tm_event(end={"dateTime": "2026-10-08T15:00:00Z"}))
        self.assertEqual(row["end_basis"], timing.BASIS_ESTIMATED)

    def test_time_to_be_announced_has_no_time_and_no_end(self):
        row = ingest.build_row(tm_event(tba=True))
        self.assertFalse(row["time_known"])
        self.assertIsNone(row["start_at"])
        self.assertIsNone(row["end_at"])
        self.assertEqual(row["end_basis"], timing.BASIS_UNKNOWN)
        self.assertEqual(row["start_date"], dt.date(2026, 10, 8))

    def test_multi_day_event_has_no_single_end(self):
        self.assertEqual(ingest.build_row(tm_event(multi=True))["end_basis"], timing.BASIS_UNKNOWN)

    def test_test_events_are_skipped(self):
        self.assertIsNone(ingest.build_row(tm_event(test=True)))

    def test_undefined_classification_is_blank(self):
        row = ingest.build_row(tm_event(segment="Undefined", genre="Undefined"))
        self.assertEqual((row["segment"], row["genre"], row["category"]), ("", "", "ovrigt"))

    def test_categories(self):
        self.assertEqual(timing.category_for("Arts & Theatre", "Comedy"), "humor")
        self.assertEqual(timing.category_for("Arts & Theatre", "Theatre"), "teater")
        self.assertEqual(timing.category_for("Sports", "Tennis"), "sport")
        self.assertEqual(timing.category_for("Arts & Theatre", "Children's Theatre"), "familj")
        self.assertEqual(timing.category_for("Miscellaneous", "Food & Drink", "Expo"), "massa")
        self.assertEqual(timing.category_for("Music", "Rock"), "konsert")

    def test_addons_are_hidden_but_real_shows_are_not(self):
        # Namnen är Ticketmasters, hämtade 2026-09-12.
        for name in ("President | Early entry and merchandise experience",
                     "Dryckeskuponger - Linköping Beer Expo - En ölmässa för alla!",
                     "A$AP Rocky - Don't Be Dumb World Tour, Platinum Tickets"):
            self.assertTrue(timing.addon_reason(name), name)
        for name in ("MAMMA MIA! THE PARTY", "FRANSKA VINDAGEN 2026", "Sweden Rock Festival 2027 -  4-days"):
            self.assertEqual(timing.addon_reason(name), "", name)

    def test_platinum_suffix_is_removed_for_display(self):
        # Namnen är Ticketmasters, hämtade 2026-09-12.
        for raw, shown in (
            ("J. Cole: The Fall-Off Tour, Platinum Tickets", "J. Cole: The Fall-Off Tour"),
            ("BENJAMIN INGROSSO | WHAT HAPPENS NEXT? | Platinum tickets", "BENJAMIN INGROSSO | WHAT HAPPENS NEXT?"),
            ("Don Toliver: NITROUS - OCTANE WORLD TOUR LEG 2- Platinum Tickets", "Don Toliver: NITROUS - OCTANE WORLD TOUR LEG 2"),
            ("MAMMA MIA! THE PARTY", "MAMMA MIA! THE PARTY"),
        ):
            self.assertEqual(timing.display_name(raw), shown)

    def test_cancelled_is_not_happening_but_rescheduled_is(self):
        self.assertFalse(timing.is_happening("cancelled"))
        self.assertFalse(timing.is_happening("postponed"))
        self.assertTrue(timing.is_happening("rescheduled"))
        self.assertTrue(timing.is_happening("offsale"))

    def test_trimmed_raw_drops_images_and_sales(self):
        event = tm_event()
        event["images"] = [{"url": "x"}]
        event["sales"] = {"public": {}}
        self.assertEqual(set(ticketmaster.trimmed(event)), {"id", "name", "url", "dates", "classification", "venue"})


class FakeClient:
    """Svarar som Ticketmaster: totalElements per fönster, sidor om PAGE_SIZE."""

    def __init__(self, total_for):
        self.total_for = total_for
        self.params = []
        self.rate_limit_available = 4900

    @property
    def call_count(self):
        return len(self.params)

    def get(self, **params):
        self.params.append(params)
        start = dt.datetime.fromisoformat(params["startDateTime"].replace("Z", "+00:00"))
        end = dt.datetime.fromisoformat(params["endDateTime"].replace("Z", "+00:00"))
        total = self.total_for(end - start)
        size, page = params["size"], params["page"]
        count = max(0, min(size, total - page * size))
        return {
            "page": {"totalElements": total, "totalPages": -(-total // size), "number": page},
            "_embedded": {"events": [tm_event(id=f"{params['startDateTime']}/{page}/{i}") for i in range(count)]},
        }


class FetchTests(SimpleTestCase):
    START = dt.datetime(2026, 9, 12, tzinfo=UTC)

    def test_window_with_a_thousand_hits_is_split(self):
        client = FakeClient(lambda span: 1500 if span > dt.timedelta(days=20) else 450)
        events, stats = ticketmaster.fetch_events(client, self.START, self.START + dt.timedelta(days=30))
        self.assertEqual((stats["splits"], stats["windows"], stats["truncated"]), (1, 2, 0))
        self.assertEqual(len(events), 900)

    def test_never_pages_past_the_thousandth_item(self):
        client = FakeClient(lambda span: 5000)
        _, stats = ticketmaster.fetch_events(client, self.START, self.START + dt.timedelta(days=1))
        self.assertTrue(all(p["page"] * p["size"] < ticketmaster.DEEP_PAGING_LIMIT for p in client.params))
        self.assertGreater(stats["truncated"], 0, "en kapning ska synas, inte tappas tyst")

    def test_every_request_is_sweden_and_includes_time_to_be_announced(self):
        client = FakeClient(lambda span: 10)
        ticketmaster.fetch_events(client, self.START, self.START + dt.timedelta(days=60))
        self.assertTrue(all(p["countryCode"] == "SE" and p["includeTBA"] == "yes" for p in client.params))
        self.assertEqual(len(client.params), 2, "två 30-dagarsfönster, en sida var")


class FakeResponse:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)

    def get(self, url, params=None, headers=None, timeout=None):
        return self.responses.pop(0)


class ClientTests(SimpleTestCase):
    def make_client(self, *responses):
        return ticketmaster.Client("hemlig-nyckel", session=FakeSession(*responses), sleep=lambda s: None, clock=lambda: 0.0)

    def test_exhausted_daily_quota_raises(self):
        c = self.make_client(FakeResponse(429, headers={"Rate-Limit-Available": "0"}))
        with self.assertRaisesMessage(ticketmaster.TicketmasterError, "kvoten"):
            c.get(page=0)

    def test_server_error_is_retried(self):
        c = self.make_client(FakeResponse(503), FakeResponse(200, {"page": {}}, {"Rate-Limit-Available": "4990"}))
        self.assertEqual(c.get(page=0), {"page": {}})
        self.assertEqual((c.call_count, c.rate_limit_available), (2, 4990))

    def test_error_never_contains_the_key(self):
        c = self.make_client(FakeResponse(401, {"fault": {"faultstring": "Invalid ApiKey"}}))
        with self.assertRaises(ticketmaster.TicketmasterError) as ctx:
            c.get(page=0)
        self.assertNotIn("hemlig-nyckel", str(ctx.exception))


# Ingen sportkälla på nätet i testerna: poll_events utan --source kör alla källor, och
# TheSportsDB:s gratisnyckel hade gått ut på nätet.
@override_settings(THESPORTSDB_API_KEY="")
class IngestTests(TestCase):
    def test_disappeared_event_is_hidden_then_purged(self):
        now = timezone.now()
        until = (now + dt.timedelta(days=30)).date()
        rows = [ingest.build_row(soon("A", "Kvar", 3, "19:00")), ingest.build_row(soon("B", "Borta", 3, "19:00"))]
        ingest.save(rows, source="ticketmaster", now=now, fetched_until=until)
        ingest.save([ingest.build_row(soon("A", "Kvar", 3, "19:00"))], source="ticketmaster", now=now, fetched_until=until)
        self.assertIsNotNone(Event.objects.get(external_id="B").missing_since)
        self.assertIsNone(Event.objects.get(external_id="A").missing_since)
        ingest.purge(now + dt.timedelta(hours=25))
        self.assertEqual(list(Event.objects.values_list("external_id", flat=True)), ["A"])

    def test_a_truncated_fetch_marks_nothing_as_gone(self):
        """Ett kapat fönster är ett urval: det som saknas där är inte borta ur källan."""
        now = timezone.now()
        until = (now + dt.timedelta(days=30)).date()
        rows = [ingest.build_row(soon("A", "Kvar", 3, "19:00")), ingest.build_row(soon("B", "Utanför urvalet", 3, "19:00"))]
        ingest.save(rows, source="ticketmaster", now=now, fetched_until=until)
        stats = ingest.save(
            [ingest.build_row(soon("A", "Kvar", 3, "19:00"))], source="ticketmaster", now=now,
            fetched_until=until, complete=False,
        )
        self.assertEqual(stats["markedMissing"], 0)
        self.assertIsNone(Event.objects.get(external_id="B").missing_since)

    def test_past_events_are_purged_a_day_after_they_end(self):
        now = timezone.now()
        ingest.save([ingest.build_row(soon("P", "Igår", -2, "19:00"))], source="ticketmaster", now=now, fetched_until=now.date())
        self.assertEqual(ingest.purge(now)["purgedPast"], 1)

    def save(self, *events):
        now = timezone.now()
        return ingest.save([ingest.build_row(e) for e in events], source="ticketmaster", now=now,
                           fetched_until=(now + dt.timedelta(days=30)).date())

    def test_platinum_listing_is_the_concert_when_nothing_else_is_listed(self):
        stats = self.save(soon("PL", "J. Cole: The Fall-Off Tour, Platinum Tickets", 5, "20:00"))
        event = Event.objects.get(external_id="PL")
        self.assertEqual((event.hidden_reason, stats["hidden"]), ("", 0), "annars försvinner konserten ur kalendern")
        row = api.event_row(event, timezone.now())
        self.assertEqual((row["name"], row["sourceName"]), ("J. Cole: The Fall-Off Tour", event.name))

    def test_addon_is_hidden_when_the_main_event_is_listed(self):
        stats = self.save(soon("M", "President", 6, "19:00"),
                          soon("EE", "President | Early entry and merchandise experience", 6, "17:00"))
        self.assertIn('"President"', Event.objects.get(external_id="EE").hidden_reason)
        self.assertEqual((Event.objects.get(external_id="M").hidden_reason, stats["hidden"]), ("", 1))

    def test_addon_at_another_venue_does_not_hide(self):
        self.save(soon("M2", "President", 6, "19:00"),
                  soon("EE2", "President | Early entry", 6, "17:00", venue_name="Annexet", address="Arenaslingan 14"))
        # Samma venue_id i tm_event -- byt det för att simulera en annan plats.
        other = Event.objects.get(external_id="EE2")
        other.venue_id = "V2"
        other.save(update_fields=["venue_id"])
        ingest.resolve_addons("ticketmaster")
        self.assertEqual(Event.objects.get(external_id="EE2").hidden_reason, "")

    def test_two_addon_listings_for_the_same_show_become_one(self):
        stats = self.save(soon("P1", "Tove Lo - ESTRUS TOUR, Platinum Tickets", 7, "20:00"),
                          soon("P2", "Tove Lo - ESTRUS TOUR - Platinum tickets", 7, "20:00"))
        self.assertEqual(stats["hidden"], 1)

    @override_settings(TICKETMASTER_API_KEY="k")
    def test_poll_command_writes_events_and_status(self):
        fake = ([soon("C1", "Konsert", 2, "19:30"), soon("C2", "President | Early entry and merchandise", 2, "18:00")],
                {"windows": 1, "splits": 0, "truncated": 0, "calls": 1, "rateLimitAvailable": 4999})
        with mock.patch("events.sources.ticketmaster.fetch_events", return_value=fake):
            call_command("poll_events", stdout=mock.MagicMock())
        self.assertEqual(Event.objects.count(), 2)
        self.assertTrue(Event.objects.get(external_id="C2").hidden_reason)
        status = SourceStatus.objects.get(source="ticketmaster")
        self.assertTrue(status.ok)
        self.assertEqual((status.events, status.written, status.detail["rateLimitAvailable"]), (2, 2, 4999))

    @override_settings(TICKETMASTER_API_KEY="")
    def test_missing_key_is_reported_not_crashed(self):
        call_command("poll_events", stdout=mock.MagicMock(), stderr=mock.MagicMock())
        self.assertEqual(SourceStatus.objects.get(source="ticketmaster").message, "TICKETMASTER_API_KEY saknas")


# Ticketmaster får lagras och visas i appen -- som om ett avtal fanns. Bara för testerna.
TM_IN_APP = {
    "ticketmaster": {"store": True, "store_reference": "test: villkor", "show_in_app": True, "app_reference": "test: avtal"},
    "predicthq": {"store": False, "store_reference": "", "show_in_app": False, "app_reference": ""},
}


@override_settings(EVENT_SOURCES=TM_IN_APP)
class ApiTests(TestCase):
    def setUp(self):
        now = timezone.now()
        rows = [
            ingest.build_row(soon("NEAR", "Nära konsert", 1, "19:30")),
            ingest.build_row(soon("TBA", "Tid ej satt", 2, "00:00", tba=True)),
            ingest.build_row(soon("FAR", "Malmökonsert", 1, "19:30", city="Malmö", lat="55.605", lon="13.003")),
            ingest.build_row(soon("ADDON", "Parkering Avicii Arena", 1, "17:00")),
            ingest.build_row(soon("OLD", "Redan slut", -1, "12:00")),
            ingest.build_row(soon("OFF", "Inställd", 3, "20:00", status="cancelled")),
            ingest.build_row(soon("NONAME", "Ella Mai", 4, "20:00", venue_name=None, address="Styckmästergatan 10")),
            ingest.build_row(soon("PLAT", "Tove Lo - ESTRUS TOUR, Platinum Tickets", 5, "20:00")),
        ]
        ingest.save(rows, source="ticketmaster", now=now, fetched_until=(now + dt.timedelta(days=30)).date())

    def get(self, entitled=True, **params):
        request = RequestFactory().get("/api/events", params)
        ent = SimpleNamespace(ok=entitled, reason="" if entitled else "no_token")
        with mock.patch("events.api.entitlement_for_request", return_value=ent):
            return json.loads(api.upcoming(request).content)

    def test_not_entitled_gets_an_empty_list(self):
        body = self.get(entitled=False)
        self.assertEqual((body["events"], body["entitled"], body["reason"]), ([], False, "no_token"))

    def test_driver_sees_upcoming_events_within_reach(self):
        body = self.get(lat="59.33", lon="18.07", radius_km="150")
        names = [e["name"] for e in body["events"]]
        self.assertEqual(names, ["Nära konsert", "Tid ej satt", "Inställd", "Ella Mai", "Tove Lo - ESTRUS TOUR"])
        near = body["events"][0]
        self.assertEqual(near["endBasis"], "estimated")
        self.assertIsNotNone(near["leaveUntil"])
        self.assertLess(near["distanceKm"], 5)

    def test_without_position_the_whole_country_is_returned(self):
        self.assertIn("Malmökonsert", [e["name"] for e in self.get()["events"]])

    def test_cancelled_is_shown_but_flagged(self):
        off = next(e for e in self.get()["events"] if e["name"] == "Inställd")
        self.assertEqual((off["happening"], off["statusLabel"]), (False, "Inställt"))

    def test_venue_without_name_falls_back_to_address(self):
        row = next(e for e in self.get()["events"] if e["name"] == "Ella Mai")
        self.assertEqual(row["venueName"], "Styckmästergatan 10")

    def test_pipeline_block_matches_the_api(self):
        block = explain.build(timezone.now())
        self.assertNotIn("error", block)
        self.assertEqual(len(block["calendar"]), len(self.get()["events"]))
        self.assertEqual(block["totals"]["hidden"], 1)
        self.assertEqual({t["source"] for t in block["terms"]}, {"ticketmaster", "predicthq", "thesportsdb"})


# -- PredictHQ ------------------------------------------------------------------


def phq_event(
    id="P1", title="Allsvenskan - Hammarby vs Brommapojkarna", *, category="sports", labels=("soccer", "regular-season"),
    start="2026-10-08T16:00:00Z", start_local="2026-10-08T18:00:00", end=None, end_local=None,
    predicted_end="2026-10-08T17:50:00Z", attendance=27867, rank=79, local_rank=92, venue="3Arena",
    address="Arenaslingan 14, 121 77 Johanneshov, Sweden", locality="Johanneshov", lat=59.2911437, lon=18.084515,
    duration=0, state="active", private=False,
):
    """Ett evenemang i PredictHQ:s form; standardvärdena är ett riktigt svar från 2026-09-13."""
    entities = [{"entity_id": "O1", "name": "Hammarby IF", "type": "organization"}]
    if venue:
        entities.append({"entity_id": "V3ARENA", "name": venue, "type": "venue", "formatted_address": address})
    geo_address = {"country_code": "SE", "formatted_address": address, "postcode": "121 77", "region": "Stockholms län"}
    if locality:
        geo_address["locality"] = locality
    event = {
        "id": id, "title": title, "category": category,
        "phq_labels": [{"label": label, "weight": 0.5} for label in labels],
        "rank": rank, "local_rank": local_rank, "phq_attendance": attendance, "entities": entities,
        "start": start, "start_local": start_local, "end": end or start, "end_local": end_local or start_local,
        "duration": duration, "timezone": "Europe/Stockholm",
        "geo": {"geometry": {"type": "Point", "coordinates": [lon, lat]}, "address": geo_address},
        "location": [lon, lat], "state": state, "private": private, "country": "SE", "scope": "locality",
    }
    if predicted_end:
        event["predicted_end"] = predicted_end
    return event


def phq_soon(id, title, days, hhmm, *, minutes=110, **kwargs):
    hour, minute = map(int, hhmm.split(":"))
    local = (timezone.now().astimezone(timing.STOCKHOLM) + dt.timedelta(days=days)).replace(
        hour=hour, minute=minute, second=0, microsecond=0,
    )
    utc = local.astimezone(UTC)
    fmt = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    kwargs.setdefault("predicted_end", fmt(utc + dt.timedelta(minutes=minutes)))
    return phq_event(id, title, start=fmt(utc), start_local=local.strftime("%Y-%m-%dT%H:%M:%S"), **kwargs)


class PredictHQNormalizeTests(SimpleTestCase):
    def build(self, **kwargs):
        return ingest.build_row(phq_event(**kwargs), ingest.PREDICTHQ)

    def test_real_football_match(self):
        row = self.build()
        self.assertEqual((row["category"], row["attendance"], row["venue_name"], row["city"]),
                         ("sport", 27867, "3Arena", "Johanneshov"))
        self.assertEqual(row["end_at"], dt.datetime(2026, 10, 8, 17, 50, tzinfo=UTC))
        self.assertEqual(row["end_basis"], timing.BASIS_PREDICTED)
        self.assertEqual((row["rank"], row["local_rank"]), (79, 92))

    def test_end_equal_to_start_means_unknown_so_estimate(self):
        row = self.build(predicted_end=None)
        self.assertEqual(row["end_basis"], timing.BASIS_ESTIMATED)

    def test_real_end_wins_over_prediction(self):
        row = self.build(end="2026-10-08T19:00:00Z", end_local="2026-10-08T21:00:00")
        self.assertEqual((row["end_at"].hour, row["end_basis"]), (19, timing.BASIS_SOURCE))

    def test_all_day_event_has_no_time(self):
        row = self.build(start="2026-10-07T22:00:00Z", start_local="2026-10-08T00:00:00",
                         end="2026-10-08T21:59:59Z", end_local="2026-10-08T23:59:59", duration=86399, predicted_end=None)
        self.assertFalse(row["time_known"])
        self.assertIsNone(row["start_at"])
        self.assertEqual((row["start_date"], row["end_basis"]), (dt.date(2026, 10, 8), timing.BASIS_UNKNOWN))

    def test_multi_day_expo(self):
        row = self.build(category="expos", labels=("lifestyle",), duration=4 * 86400)
        self.assertTrue(row["multi_day"])
        self.assertEqual((row["category"], row["end_basis"]), ("massa", timing.BASIS_UNKNOWN))

    def test_double_encoded_title_is_repaired(self):
        self.assertEqual(self.build(title="GÃ¶teborg Book Fair")["name"], "Göteborg Book Fair")

    def test_missing_venue_and_locality_fall_back_to_the_address(self):
        row = self.build(venue=None, locality=None, address="Borås arena, 506 30 Borås, Sweden")
        self.assertEqual((row["venue_name"], row["city"], row["address"]), ("Borås arena", "Borås", "Borås arena, 506 30 Borås"))

    def test_english_city_names_become_swedish(self):
        self.assertEqual(self.build(locality="Gothenburg")["city"], "Göteborg")
        self.assertEqual(self.build(locality="Skelleftea")["city"], "Skellefteå")

    def test_performing_arts_are_split_on_labels(self):
        self.assertEqual(timing.category_for_phq("performing-arts", ["comedy-club"]), "humor")
        self.assertEqual(timing.category_for_phq("performing-arts", ["movie"]), "film")
        self.assertEqual(timing.category_for_phq("performing-arts", ["family-theatre"]), "familj")
        self.assertEqual(timing.category_for_phq("performing-arts", ["general-theatre"]), "teater")
        self.assertEqual(timing.category_for_phq("community", ["family-fun"]), "familj")
        self.assertEqual(timing.category_for_phq("conferences", ["medical"]), "massa")

    def test_private_and_deleted_are_skipped(self):
        self.assertIsNone(self.build(private=True))
        self.assertIsNone(self.build(state="deleted"))

    def test_attendance_is_rounded_never_exact(self):
        self.assertEqual(timing.attendance_text(27867), "≈ 28\u00a0000 besökare")
        self.assertEqual(timing.attendance_text(776), "≈ 800 besökare")
        self.assertEqual(timing.attendance_text(None), "")
        self.assertEqual([timing.size_level(n) for n in (None, 400, 1000, 5000)], ["okand", "liten", "medel", "stor"])


class PhqSession(FakeSession):
    def __init__(self, *responses):
        super().__init__(*responses)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        return super().get(url, params, headers, timeout)


class PredictHQClientTests(SimpleTestCase):
    def client_for(self, *responses):
        session = PhqSession(*responses)
        return predicthq.Client("hemlig-token", session=session, sleep=lambda s: None, clock=lambda: 0.0), session

    def test_follows_next_pages_without_resending_params(self):
        client, session = self.client_for(
            FakeResponse(200, {"count": 3, "results": [phq_event("A"), phq_event("B")], "next": "https://api.predicthq.com/v1/events/?offset=2"}),
            FakeResponse(200, {"count": 3, "results": [phq_event("C")], "next": None}, {"x-ratelimit-remaining": "197"}),
            FakeResponse(200, {"count": 0, "results": [], "next": None}),  # DK
        )
        events, stats = predicthq.fetch_events(client, dt.date(2026, 9, 13), dt.date(2027, 1, 11))
        self.assertEqual(([e["id"] for e in events], stats["pages"], stats["count"]), (["A", "B", "C"], 3, 3))
        self.assertEqual(session.calls[0][1]["country"], "SE")
        self.assertIsNone(session.calls[1][1], "next-länken bär redan parametrarna")
        self.assertEqual(session.calls[2][1]["country"], "DK")
        self.assertEqual(stats["rateLimitRemaining"], 197)

    def test_overflow_is_recorded(self):
        client, _ = self.client_for(
            FakeResponse(200, {"count": 9, "results": [], "next": None, "overflow": True}),
            FakeResponse(200, {"count": 0, "results": [], "next": None})
        )
        self.assertTrue(predicthq.fetch_events(client, dt.date(2026, 9, 13), dt.date(2026, 10, 13))[1]["overflow"])

    def test_rate_limit_is_retried(self):
        client, _ = self.client_for(FakeResponse(429, headers={"Retry-After": "1"}), FakeResponse(200, {"results": []}))
        self.assertEqual(client.get(predicthq.API_URL), {"results": []})
        self.assertEqual(client.call_count, 2)

    def test_error_never_contains_the_token(self):
        client, _ = self.client_for(FakeResponse(401, {"error": "invalid_token"}))
        with self.assertRaises(predicthq.PredictHQError) as ctx:
            client.get(predicthq.API_URL)
        self.assertNotIn("hemlig-token", str(ctx.exception))


class MatchingTests(SimpleTestCase):
    """Parningen i minnet mellan PredictHQ och sparade Ticketmaster-rader."""

    def tm(self, *args, **kwargs):
        return SimpleNamespace(**ingest.build_row(soon(*args, **kwargs)), source="ticketmaster")

    def phq(self, *args, **kwargs):
        return SimpleNamespace(**ingest.build_row(phq_soon(*args, **kwargs), ingest.PREDICTHQ), source="predicthq")

    def test_same_concert_from_both_sources_pairs(self):
        pairs = matching.pair(
            [self.phq("PH1", "Stevie Wonder at 3Arena", 5, "20:00", category="concerts", labels=("pop",),
                      attendance=38706, lat=59.2944, lon=18.0810)],
            [self.tm("TM1", "Stevie Wonder: Songs In The Key of Life Performances, Platinum Tickets", 5, "20:00",
                     venue_name=None, address="Globentorget 2", lat="59.2941", lon="18.0808")],
        )
        self.assertEqual(list(pairs), [0])
        self.assertIn("m bort", pairs[0][1])

    def test_two_shows_the_same_day_pair_by_start_time(self):
        primaries = [self.phq("PH19", "MAMMA MIA! THE PARTY", 6, "19:30", category="performing-arts", attendance=None,
                              lat=59.3337, lon=18.0770),
                     self.phq("PH13", "MAMMA MIA! THE PARTY", 6, "13:00", category="performing-arts", attendance=None,
                              lat=59.3337, lon=18.0770)]
        others = [self.tm("TM13", "MAMMA MIA! THE PARTY", 6, "13:00"), self.tm("TM19", "MAMMA MIA! THE PARTY", 6, "19:30")]
        pairs = matching.pair(primaries, others)
        self.assertEqual({others[j].external_id: primaries[i].external_id for j, (i, _) in pairs.items()},
                         {"TM13": "PH13", "TM19": "PH19"})

    def test_different_event_at_the_same_venue_is_not_paired(self):
        self.assertEqual(matching.pair([self.phq("PHJ", "Jazzkväll med husbandet", 4, "20:00", lat=59.3337, lon=18.0770)],
                                       [self.tm("TME", "Ella Mai", 4, "20:00")]), {})

    def test_same_name_hours_apart_is_not_paired(self):
        self.assertEqual(matching.pair([self.phq("PHA", "Konsert med Kören", 4, "19:30", lat=59.3337, lon=18.0770)],
                                       [self.tm("TMA", "Konsert med Kören", 4, "13:00")]), {})


class PredictHQLiveTests(TestCase):
    def setUp(self):
        now = timezone.now()
        ingest.save([ingest.build_row(soon("TM1", "Stevie Wonder: Songs In The Key of Life Performances, Platinum Tickets",
                                           5, "20:00", venue_name=None, address="Globentorget 2", lat="59.2941", lon="18.0808"))],
                    source="ticketmaster", now=now, fetched_until=(now + dt.timedelta(days=30)).date())

    def call(self, **params):
        response = live.pipeline_predicthq(RequestFactory().get("/api/pipeline/predicthq", params))
        return response.status_code, json.loads(response.content)

    @override_settings(DEBUG=True, PREDICTHQ_ACCESS_TOKEN="t")
    def test_live_adds_attendance_and_ticket_link_and_stores_nothing(self):
        fake = ([phq_soon("PH1", "Stevie Wonder at 3Arena", 5, "20:00", category="concerts", labels=("pop",),
                          attendance=38706, lat=59.2944, lon=18.0810),
                 phq_soon("PH2", "Allsvenskan - AIK vs Mjällby", 3, "19:00", attendance=35284, lat=59.3727, lon=18.0012)],
                {"pages": 1, "count": 2, "overflow": False, "truncated": 0, "calls": 1, "rateLimitRemaining": 199})
        before = Event.objects.count()
        with mock.patch("events.sources.predicthq.fetch_events", return_value=fake):
            status, body = self.call(days="14")
        self.assertEqual(status, 200)
        self.assertEqual(Event.objects.count(), before, "PredictHQ-data får inte sparas")
        self.assertFalse(SourceStatus.objects.filter(source="predicthq").exists())
        self.assertFalse(body["stored"])
        stevie = next(e for e in body["events"] if e["id"] == "predicthq:PH1")
        self.assertEqual((stevie["ticketmasterId"], stevie["attendance"], stevie["sources"]),
                         ("ticketmaster:TM1", 38706, ["predicthq", "ticketmaster"]))
        self.assertTrue(stevie["url"].startswith("https://www.ticketmaster.se/"))
        self.assertEqual((body["matchedTicketmaster"], body["attribution"]), (1, "Evenemangsdata från PredictHQ"))

    @override_settings(DEBUG=False, PREDICTHQ_ACCESS_TOKEN="t")
    def test_live_endpoint_does_not_exist_outside_debug(self):
        with self.assertRaises(Http404):
            self.call()

    @override_settings(DEBUG=True, PREDICTHQ_ACCESS_TOKEN="")
    def test_missing_token_is_reported(self):
        status, body = self.call()
        self.assertEqual(status, 502)
        self.assertIn("saknas", body["error"])

    def test_saving_predicthq_is_refused(self):
        with self.assertRaises(ValueError):
            ingest.save([], source="predicthq", now=timezone.now(), fetched_until=timezone.now().date())


PHQ_AGREED = {
    "ticketmaster": TM_IN_APP["ticketmaster"],
    "predicthq": {"store": True, "store_reference": "test: skriftligt avtal", "show_in_app": True, "app_reference": "test: avtal"},
}


def _entitled_upcoming(**params):
    request = RequestFactory().get("/api/events", params)
    with mock.patch("events.api.entitlement_for_request", return_value=SimpleNamespace(ok=True, reason="")):
        return json.loads(api.upcoming(request).content)


class RightsTests(SimpleTestCase):
    """En brytare ger ingen rätt. Utan referens till villkor eller avtal är svaret nej."""

    def phq(self, **config):
        with override_settings(EVENT_SOURCES={"predicthq": config}):
            return rights.rights_for("predicthq")

    def test_a_switch_without_a_reference_grants_nothing(self):
        r = self.phq(store=True, store_reference="", show_in_app=True, app_reference="")
        self.assertFalse(r.may_store())
        self.assertFalse(r.may_show_in_app())
        self.assertIn("rättighetsreferens", r.refusal("store"))

    def test_a_reference_without_the_switch_grants_nothing(self):
        self.assertFalse(self.phq(store=False, store_reference="avtal 2026-10-01").may_store())

    def test_the_app_needs_storage_its_own_switch_and_its_own_reference(self):
        self.assertFalse(self.phq(store=True, store_reference="avtal", show_in_app=True, app_reference="").may_show_in_app())
        self.assertTrue(self.phq(store=True, store_reference="avtal", show_in_app=True, app_reference="avtal").may_show_in_app())

    def test_an_unknown_source_grants_nothing(self):
        self.assertFalse(rights.rights_for("okänd källa").may_store())

    def test_shipped_defaults(self):
        """Utan miljövariabler: Ticketmaster lagras enligt villkoren men visas inte i appen; PredictHQ inget."""
        self.assertTrue(rights.rights_for("ticketmaster").may_store())
        self.assertFalse(rights.rights_for("ticketmaster").may_show_in_app())
        self.assertFalse(rights.rights_for("predicthq").may_store())


class PredictHQStorageTests(TestCase):
    def rows(self):
        return [ingest.build_row(
            phq_soon("PHS1", "Stort derby", 3, "19:00", attendance=24000, lat=59.2944, lon=18.0810), ingest.PREDICTHQ,
        )]

    def test_refused_without_a_reference(self):
        with self.assertRaises(rights.StorageNotPermitted):
            ingest.save(self.rows(), source="predicthq", now=timezone.now(), fetched_until=timezone.now().date())
        self.assertFalse(Event.objects.filter(source="predicthq").exists())

    @override_settings(EVENT_SOURCES=PHQ_AGREED)
    def test_stored_with_a_reference_including_the_attendance_forecast(self):
        now = timezone.now()
        ingest.save(self.rows(), source="predicthq", now=now, fetched_until=(now + dt.timedelta(days=30)).date())
        self.assertEqual(Event.objects.get(source="predicthq", external_id="PHS1").attendance, 24000)

    @override_settings(PREDICTHQ_ACCESS_TOKEN="t")
    def test_the_poll_makes_no_call_when_storage_is_not_permitted(self):
        with mock.patch("events.sources.predicthq.fetch_events") as fetch:
            call_command("poll_events", "--source", "predicthq", stdout=mock.MagicMock())
        fetch.assert_not_called()
        status = SourceStatus.objects.get(source="predicthq")
        self.assertTrue(status.message)
        self.assertIsNone(status.last_success_at)


# Den egna källan (events/manual.py) får alltid visas. Grindtesterna nedan
# prövar de externa källornas rättigheter och körs därför utan den.
WITHOUT_MANUAL = {k: v for k, v in settings.EVENT_SOURCES.items() if k != "manual"}


class AppGateTests(TestCase):
    @override_settings(EVENT_SOURCES=WITHOUT_MANUAL)
    def test_without_an_app_reference_the_driver_app_gets_no_events(self):
        now = timezone.now()
        ingest.save([ingest.build_row(soon("G1", "Konsert", 2, "19:00"))], source="ticketmaster", now=now,
                    fetched_until=(now + dt.timedelta(days=30)).date())
        body = _entitled_upcoming()
        self.assertEqual((body["events"], body["reason"]), ([], "no_licensed_sources"))

    @override_settings(EVENT_SOURCES=PHQ_AGREED)
    def test_the_same_event_from_both_sources_is_one_row(self):
        now = timezone.now()
        until = (now + dt.timedelta(days=30)).date()
        ingest.save([ingest.build_row(soon("TM1", "Stevie Wonder: Songs In The Key of Life Performances, Platinum Tickets",
                                           5, "20:00", venue_name=None, address="Globentorget 2", lat="59.2941", lon="18.0808"))],
                    source="ticketmaster", now=now, fetched_until=until)
        ingest.save([ingest.build_row(phq_soon("PH1", "Stevie Wonder at 3Arena", 5, "20:00", category="concerts", labels=("pop",),
                                               attendance=38706, lat=59.2944, lon=18.0810), ingest.PREDICTHQ)],
                    source="predicthq", now=now, fetched_until=until)
        stevie = [e for e in _entitled_upcoming()["events"] if "Stevie" in e["name"]]
        self.assertEqual(len(stevie), 1)
        self.assertEqual((stevie[0]["sources"], stevie[0]["attendance"]), (["predicthq", "ticketmaster"], 38706))


class AreaAndPreviewTests(TestCase):
    """Appen filtrerar evenemang på förarens län och kommuner; förhandsvisning bara med DEBUG."""

    def setUp(self):
        now = timezone.now()
        rows = [
            ingest.build_row(soon("STHLM", "Konsert i Stockholm", 1, "19:30")),
            ingest.build_row(soon("MALMO", "Konsert i Malmö", 1, "19:30", city="Malmö", lat="55.605", lon="13.003")),
        ]
        ingest.save(rows, source="ticketmaster", now=now, fetched_until=(now + dt.timedelta(days=30)).date())

    def test_a_county_choice_keeps_only_its_events(self):
        with override_settings(EVENT_SOURCES=TM_IN_APP):
            body = _entitled_upcoming(counties="12")
        self.assertEqual([e["name"] for e in body["events"]], ["Konsert i Malmö"])
        self.assertEqual(body["counties"], ["12"])

    def test_preview_needs_debug_and_is_labelled(self):
        with override_settings(EVENTS_APP_PREVIEW=True, DEBUG=False, EVENT_SOURCES=WITHOUT_MANUAL):
            self.assertEqual(_entitled_upcoming(counties="01")["reason"], "no_licensed_sources")
        with override_settings(EVENTS_APP_PREVIEW=True, DEBUG=True, EVENT_SOURCES=WITHOUT_MANUAL):
            body = _entitled_upcoming(counties="01")
        self.assertTrue(body["preview"])
        self.assertIn("Förhandsvisning", body["previewNote"])
        self.assertEqual([e["name"] for e in body["events"]], ["Konsert i Stockholm"])


class PeriodTests(TestCase):
    """Evenemang per datum: en dag, en period, och aldrig längre fram än hämtningen."""

    def setUp(self):
        now = timezone.now()
        rows = [
            ingest.build_row(soon("D1", "I morgon", 1, "19:30")),
            ingest.build_row(soon("D10", "Om tio dagar", 10, "19:30")),
            ingest.build_row(soon("D100", "Om hundra dagar", 100, "19:30")),
        ]
        ingest.save(rows, source="ticketmaster", now=now, fetched_until=(now + dt.timedelta(days=130)).date())
        self.today = timezone.now().astimezone(timing.STOCKHOLM).date()

    def test_a_single_day_shows_that_day_and_counts_the_whole_horizon(self):
        day = (self.today + dt.timedelta(days=10)).isoformat()
        with override_settings(EVENT_SOURCES=TM_IN_APP):
            body = _entitled_upcoming(**{"from": day, "to": day, "counties": "01"})
        self.assertEqual([e["name"] for e in body["events"]], ["Om tio dagar"])
        self.assertEqual((body["from"], body["to"]), (day, day))
        self.assertEqual(sum(body["dayCounts"].values()), 3)

    def test_months_ahead_are_allowed_and_the_horizon_caps_the_period(self):
        with override_settings(EVENT_SOURCES=TM_IN_APP):
            body = _entitled_upcoming(days="400", counties="01")
        self.assertIn("Om hundra dagar", [e["name"] for e in body["events"]])
        self.assertEqual(body["to"], (self.today + dt.timedelta(days=api.MAX_DAYS)).isoformat())
        self.assertEqual(body["maxDays"], api.MAX_DAYS)

    def test_a_period_in_the_past_starts_today(self):
        with override_settings(EVENT_SOURCES=TM_IN_APP):
            body = _entitled_upcoming(**{"from": "2020-01-01", "to": "2020-01-02", "counties": "01"})
        self.assertEqual((body["from"], body["to"]), (self.today.isoformat(), self.today.isoformat()))


# -- Sort: sport och kategori ---------------------------------------------------------


class SportKindTests(SimpleTestCase):
    """Fotboll, ishockey och handboll läses per källa; allt annat behåller sin kategori."""

    def test_sport_per_source(self):
        self.assertEqual(timing.sport_for("predicthq", "sport", "sport", "soccer"), "fotboll")
        self.assertEqual(timing.sport_for("predicthq", "sport", "ice-hockey"), "ishockey")
        self.assertEqual(timing.sport_for("thesportsdb", "sport", "Handball"), "handboll")
        self.assertEqual(timing.sport_for("thesportsdb", "sport", "Ice Hockey"), "ishockey")
        # Hos Ticketmaster är "Football" amerikansk fotboll.
        self.assertEqual(timing.sport_for("ticketmaster", "sport", "Football"), "annan")
        self.assertEqual(timing.sport_for("ticketmaster", "sport", "Soccer"), "fotboll")
        self.assertEqual(timing.sport_for("predicthq", "sport", "sport", "", "Allsvenskan - Hammarby vs AIK"), "fotboll")
        self.assertEqual(timing.sport_for("ticketmaster", "konsert", "Rock"), "")

    def test_predicthq_airport_delays_weather_and_festivals_get_their_own_kind(self):
        self.assertEqual(timing.category_for_phq("airport-delays", []), "flyg")
        self.assertEqual(timing.category_for_phq("severe-weather", []), "vader")
        self.assertEqual(timing.category_for_phq("festivals", []), "festival")
        self.assertEqual(timing.category_for("Miscellaneous", "Fairs & Festivals", "Festival"), "festival")

    def test_only_copenhagen_among_danish_airport_delays(self):
        from events.sources import predicthq

        cph = {"title": "Airport Delays - Copenhagen Airport (CPH)", "entities": []}
        billund = {"title": "Airport Delays", "entities": [{"type": "airport", "name": "Billund Airport"}]}
        self.assertEqual((predicthq.is_copenhagen_airport(cph), predicthq.is_copenhagen_airport(billund)), (True, False))
