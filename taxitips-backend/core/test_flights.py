"""
Tester för flygkällan: Swedavia-normalisering och ankomstvågsreglerna.

Det viktigaste testet i filen är StatusSemanticsTests: `DEL` betyder
"Borttagen", inte "Delayed", och ett flyg som tagits ur tidtabellen bär noll
resenärer. Läser man det som "försenad" får man exakt motsatt signal, och
inget annat i systemet hade fångat felet -- tipsen hade bara varit fel.
"""

from __future__ import annotations

import datetime as dt

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone

from core import flight_scoring, thresholds
from core.management.commands.poll_flights import SOURCE, Command
from core.models import Confidence, Opportunity, SeverityTier, SourceEvent, SourceStatus
from core.sources.swedavia import normalize_arrivals, normalize_flight

UTC = dt.timezone.utc


def raw_flight(
    flight_id: str,
    scheduled: str,
    *,
    estimated: str | None = None,
    actual: str | None = None,
    status: str = "SCH",
    status_sv: str = "Planerad",
) -> dict:
    """Ett flyg i Swedavias form. Samma nycklar som ett riktigt svar."""
    times = {"scheduledUtc": scheduled}
    if estimated:
        times["estimatedUtc"] = estimated
    if actual:
        times["actualUtc"] = actual
    return {
        "flightId": flight_id,
        "departureAirportSwedish": "Köpenhamn",
        "departureAirportEnglish": "Copenhagen",
        "airlineOperator": {"iata": "SK", "icao": "SAS", "name": "SAS"},
        "arrivalTime": times,
        "locationAndStatus": {
            "terminal": "T5",
            "flightLegStatus": status,
            "flightLegStatusSwedish": status_sv,
            "flightLegStatusEnglish": status,
        },
        "baggage": {},
        "codeShareData": [],
        "flightLegIdentifier": {"flightId": flight_id, "departureAirportIata": "CPH"},
        "remarksSwedish": [],
        "viaDestinations": [],
        "diIndicator": "S",
    }


def evening(minute_offsets: list[int], **kwargs) -> list[dict]:
    """
    Flyg som landar 23:30 lokal tid + offset, dvs 21:30 UTC i september.

    Lokal tid är det som räknas: fönstergränserna ska ligga på halvtimmar en
    förare känner igen, inte på UTC-halvtimmar som vandrar med sommartiden.
    """
    out = []
    for i, offset in enumerate(minute_offsets):
        moment = dt.datetime(2026, 9, 12, 21, 30, tzinfo=UTC) + dt.timedelta(minutes=offset)
        out.append(raw_flight(f"SK{100 + i}", moment.isoformat().replace("+00:00", "Z"), **kwargs))
    return out


def windows_for(raws: list[dict], airport: str = "ARN", now: dt.datetime | None = None):
    flights = normalize_arrivals({"flights": raws}, airport)
    return flight_scoring.windows(flights, airport, now or dt.datetime(2026, 9, 12, 20, 0, tzinfo=UTC))


class StatusSemanticsTests(TestCase):
    """DEL = Borttagen. Inte Delayed. Hela källans trovärdighet hänger på det."""

    def test_deleted_flight_is_not_a_delayed_flight(self):
        flight = normalize_flight(
            raw_flight("EW4607", "2026-09-12T21:15:00Z", status="DEL", status_sv="Borttagen"),
            "ARN",
        )
        # Inget estimat, ingen faktisk tid -- planet finns inte längre.
        self.assertIsNone(flight["delay_minutes"])
        self.assertFalse(flight["is_live"])
        self.assertEqual(flight["status_text"], "Borttagen")

    def test_deleted_and_cancelled_never_count_toward_a_wave(self):
        raws = evening([0, 5, 10, 15, 20, 25, 2, 7], status="DEL", status_sv="Borttagen")
        raws += evening([12], status="CAN", status_sv="Inställd")
        self.assertEqual(windows_for(raws), [])

    def test_a_real_wave_of_the_same_size_does_trigger(self):
        found = windows_for(evening([0, 5, 10, 15, 20, 25, 2, 7]))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].arrivals, 8)

    def test_delay_is_computed_from_times_not_from_status(self):
        flight = normalize_flight(
            raw_flight(
                "SK1428",
                "2026-09-12T21:00:00Z",
                estimated="2026-09-12T21:55:00Z",
                status="SCH",
            ),
            "ARN",
        )
        self.assertEqual(flight["delay_minutes"], 55)
        self.assertTrue(flight["is_live"])

    def test_schedule_only_flight_has_unknown_delay_not_zero(self):
        """None betyder "vet inte" -- ett flyg utan estimat är inte ett flyg i tid."""
        flight = normalize_flight(raw_flight("SK1", "2026-09-12T21:00:00Z"), "ARN")
        self.assertIsNone(flight["delay_minutes"])

    def test_actual_time_wins_over_estimate(self):
        flight = normalize_flight(
            raw_flight(
                "SK2",
                "2026-09-12T21:00:00Z",
                estimated="2026-09-12T21:30:00Z",
                actual="2026-09-12T21:10:00Z",
                status="LAN",
            ),
            "ARN",
        )
        self.assertEqual(flight["delay_minutes"], 10)


class WindowTests(TestCase):
    def test_flights_are_bucketed_on_local_half_hours(self):
        # 23:20-23:29 | 23:35-23:55 lokal tid -> två fönster, inte ett.
        raws = evening([-10, -5, -1, 5, 20, 25])
        flights = normalize_arrivals({"flights": raws}, "GOT")
        found = flight_scoring.windows(
            flights, "GOT", dt.datetime(2026, 9, 12, 20, 0, tzinfo=UTC)
        )
        self.assertEqual([w.arrivals for w in found], [3, 3])
        self.assertEqual(found[0].label(), "23:00–23:30")
        self.assertEqual(found[1].label(), "23:30–00:00")

    def test_daytime_wave_is_ignored(self):
        """Mitt på dagen finns full kollektivtrafik -- ingen står strandsatt."""
        noon = [
            raw_flight(f"SK{i}", f"2026-09-12T10:{i:02d}:00Z") for i in range(0, 25, 3)
        ]
        self.assertEqual(windows_for(noon), [])

    def test_threshold_is_per_airport(self):
        """
        Skalorna skiljer en tiopotens: ARN hade som mest 12 ankomster i ett
        fönster på en vardag, GOT 3. En gemensam tröskel hade betytt att bara
        Arlanda någonsin gav ett tips.
        """
        three = evening([0, 10, 20])
        self.assertEqual(len(windows_for(three, "GOT")), 1)
        self.assertEqual(windows_for(three, "ARN"), [])

    def test_external_id_is_stable_across_polls(self):
        """Samma fönster, andra flyg i det -> samma id, så upsert uppdaterar."""
        first = windows_for(evening([0, 5, 10, 15, 20, 25, 2, 7]))[0]
        second = windows_for(evening([0, 5, 10, 15, 20, 25, 2, 7, 12]))[0]
        self.assertEqual(first.external_id, second.external_id)
        self.assertEqual(first.external_id, "swedavia:ARN:2026-09-12T21:30Z")


class ScoreTests(TestCase):
    def _classify(self, raws, airport="ARN", now=None):
        found = windows_for(raws, airport, now)
        self.assertEqual(len(found), 1)
        return found[0], flight_scoring.classify(
            found[0], now or dt.datetime(2026, 9, 12, 20, 0, tzinfo=UTC)
        )

    def test_minimum_wave_scores_base_plus_night(self):
        _w, a = self._classify(evening([0, 5, 10, 15, 20, 25, 2, 7]))
        self.assertEqual(a.tier, SeverityTier.ARRIVAL_WAVE)
        self.assertEqual(
            a.score, thresholds.FLIGHT_BASE_SCORE + thresholds.FLIGHT_NIGHT_BONUS
        )

    def test_extra_arrivals_raise_the_score(self):
        _w, small = self._classify(evening([0, 5, 10, 15, 20, 25, 2, 7]))
        _w, big = self._classify(evening([0, 5, 10, 15, 20, 25, 2, 7, 12, 17]))
        self.assertEqual(
            big.score - small.score, 2 * thresholds.FLIGHT_SCORE_PER_EXTRA_ARRIVAL
        )

    def test_delayed_flights_add_a_capped_bonus(self):
        late = [
            raw_flight(
                f"SK{i}",
                "2026-09-12T20:30:00Z",
                estimated=(
                    dt.datetime(2026, 9, 12, 21, 30, tzinfo=UTC) + dt.timedelta(minutes=i)
                ).isoformat().replace("+00:00", "Z"),
            )
            for i in range(8)
        ]
        window, a = self._classify(late)
        self.assertEqual(len(window.delayed), 8)
        # Taket biter: 8 * 6 = 48, men bonusen är begränsad.
        self.assertEqual(
            a.score,
            thresholds.FLIGHT_BASE_SCORE
            + thresholds.FLIGHT_DELAY_BONUS_CAP
            + thresholds.FLIGHT_NIGHT_BONUS,
        )
        self.assertIn("minst 40 minuter försenade", " ".join(a.reasons))

    def test_reasons_never_claim_a_passenger_count(self):
        """
        Svaret bär varken flygplanstyp eller passagerarantal. "500-600
        personer" hade varit påhittat -- samma regel som för GTFS-beläggning.
        """
        _w, a = self._classify(evening([0, 5, 10, 15, 20, 25, 2, 7]))
        text = " ".join(a.reasons).lower()
        for forbidden in ("personer", "resenärer", "passagerare"):
            self.assertNotIn(forbidden, text)

    def test_reasons_never_claim_the_last_train_has_gone(self):
        """Vi har ingen tidtabell för Arlanda Express -- invariant 2."""
        _w, a = self._classify(evening([0, 5, 10, 15, 20, 25, 2, 7]))
        text = " ".join(a.reasons).lower()
        self.assertNotIn("sista", text)
        self.assertNotIn("inga fler avgångar", text)

    def test_score_never_exceeds_100_without_a_scoring_rule(self):
        """Tom ScoringRule-tabell får aldrig släppa igenom en ogiltig poäng."""
        huge = evening(list(range(0, 30)))
        window = windows_for(huge)[0]
        a = flight_scoring.classify(window, dt.datetime(2026, 9, 12, 20, 0, tzinfo=UTC))
        self.assertLessEqual(a.score, 100)
        self.assertGreaterEqual(a.score, 0)


class LastArrivalTests(TestCase):
    """
    De åtta små flygplatserna. Mätt lördag och måndag: ingen av dem har
    någonsin mer än två ankomster i samma halvtimme, så en volymtröskel hade
    gett noll tips för evigt. Signalen där är i stället att inget MER landar.
    """

    def _windows(self, raws, airport="LLA", now=None):
        flights = normalize_arrivals({"flights": raws}, airport)
        return flight_scoring.windows(
            flights, airport, now or dt.datetime(2026, 9, 12, 20, 0, tzinfo=UTC)
        )

    def test_a_single_late_arrival_is_a_tip(self):
        found = self._windows(evening([0]))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0].arrivals, 1)
        self.assertTrue(found[0].is_last)

    def test_not_the_last_when_another_lands_within_the_gap(self):
        """23:30 och 00:30 -- det första planet är inte kvällens sista."""
        found = self._windows(evening([0, 60]))
        self.assertEqual([w.label() for w in found], ["00:30–01:00"])

    def test_is_the_last_when_the_next_is_beyond_the_gap(self):
        gap = thresholds.FLIGHT_ISOLATION_HOURS * 60
        found = self._windows(evening([0, gap + 30]))
        self.assertEqual(len(found), 2)

    def test_a_daytime_arrival_after_it_still_cancels_it(self):
        """
        Ensamheten mäts mot ALLA ankomster, inte bara de sena. Ett plan 05:30
        är inte kvällens sista om nästa landar 06:15, även om 06:15 ligger
        utanför det sena fönstret.
        """
        raws = [
            raw_flight("SK1", "2026-09-12T03:30:00Z"),   # 05:30 lokalt, sen timme
            raw_flight("SK2", "2026-09-12T04:15:00Z"),   # 06:15 lokalt, dagtid
        ]
        self.assertEqual(self._windows(raws), [])

    def test_scores_lower_than_a_wave_but_still_reaches_the_list(self):
        window = self._windows(evening([0]))[0]
        a = flight_scoring.classify(window, dt.datetime(2026, 9, 12, 20, 0, tzinfo=UTC))
        self.assertEqual(a.tier, SeverityTier.LAST_ARRIVAL)
        self.assertEqual(
            a.score, thresholds.FLIGHT_LAST_ARRIVAL_BASE + thresholds.FLIGHT_NIGHT_BONUS
        )

    def test_says_what_it_knows_and_not_what_it_does_not(self):
        window = self._windows(evening([0]))[0]
        a = flight_scoring.classify(window, dt.datetime(2026, 9, 12, 20, 0, tzinfo=UTC))
        text = " ".join(a.reasons).lower()
        # Det vi VET ur tidtabellen:
        self.assertIn("inget mer plan landar", text)
        # Det vi INTE vet: om bussen eller tåget går.
        for invented in ("buss", "tåg", "ingen transport", "strandsatt"):
            self.assertNotIn(invented, text)

    def test_title_does_not_call_a_single_plane_a_wave(self):
        window = self._windows(evening([0]))[0]
        self.assertIn("Sista ankomsten", flight_scoring.title(window))
        self.assertNotIn("Ankomstvåg", flight_scoring.title(window))


class AirportRegistryTests(TestCase):
    def test_every_swedavia_airport_is_covered(self):
        """Alla tio som FlightInfo svarar för. De fyra icke-Swedavia ger 400."""
        self.assertEqual(
            set(thresholds.AIRPORTS),
            {"ARN", "BMA", "GOT", "MMX", "LLA", "UME", "VBY", "KRN", "RNB", "OSD"},
        )

    def test_wave_airports_have_a_threshold_and_others_do_not(self):
        for iata, a in thresholds.AIRPORTS.items():
            if a["rule"] == thresholds.RULE_WAVE:
                self.assertIn("wave_min", a, iata)
            else:
                self.assertNotIn("wave_min", a, iata)

    def test_region_is_null_never_empty_when_there_is_no_market(self):
        """Invariant 5: NULL, aldrig tom sträng."""
        for iata, a in thresholds.AIRPORTS.items():
            self.assertNotEqual(a["region"], "", iata)

    def test_city_matches_its_region_so_the_city_filter_cannot_hide_the_tip(self):
        """
        core/notify.py matchar förarens valda ort som delsträng mot `places`.
        Står flygplatsens ort inte i REGION_CITIES för dess region försvinner
        tipset tyst för alla som valt orter i det länet.
        """
        from core.geo import REGION_CITIES

        for iata, a in thresholds.AIRPORTS.items():
            if not a["region"]:
                continue
            cities = [c.lower() for c in REGION_CITIES.get(a["region"], [])]
            city = a["city"].lower()
            self.assertTrue(
                any(city in c or c in city for c in cities),
                f"{iata}: {a['city']} saknas i REGION_CITIES[{a['region']!r}]",
            )


class ConfidenceTests(TestCase):
    def _confidence(self, raws, now):
        found = windows_for(raws, "ARN", now)
        return flight_scoring.classify(found[0], now).confidence

    def test_far_ahead_is_low_because_it_is_only_a_timetable(self):
        morning = dt.datetime(2026, 9, 12, 8, 0, tzinfo=UTC)
        self.assertEqual(
            self._confidence(evening([0, 5, 10, 15, 20, 25, 2, 7]), morning),
            Confidence.LOW,
        )

    def test_live_estimates_close_in_time_are_high(self):
        near = dt.datetime(2026, 9, 12, 21, 0, tzinfo=UTC)
        live = evening([0, 5, 10, 15, 20, 25, 2, 7], estimated="2026-09-12T21:40:00Z")
        self.assertEqual(self._confidence(live, near), Confidence.HIGH)

    def test_schedule_only_close_in_time_is_medium(self):
        near = dt.datetime(2026, 9, 12, 21, 0, tzinfo=UTC)
        self.assertEqual(
            self._confidence(evening([0, 5, 10, 15, 20, 25, 2, 7]), near),
            Confidence.MEDIUM,
        )


class WriteTests(TestCase):
    def _assessed(self):
        now = dt.datetime(2026, 9, 12, 20, 0, tzinfo=UTC)
        found = windows_for(evening([0, 5, 10, 15, 20, 25, 2, 7]), "ARN", now)
        return [(w, flight_scoring.classify(w, now)) for w in found]

    def test_writes_tip_and_cites_every_counted_flight(self):
        written = Command()._write(self._assessed())
        self.assertEqual(written, 1)

        tip = Opportunity.objects.get(kind="flight")
        self.assertEqual(tip.severity_tier, SeverityTier.ARRIVAL_WAVE)
        self.assertEqual(tip.mode, "flight")
        self.assertEqual(tip.region, "sl")
        self.assertEqual(SourceEvent.objects.filter(source=SOURCE).count(), 8)
        # Förklaringspanelen joinar strikt på source_event_ids -- ett tips som
        # inte citerar sina flyg går inte att förklara (invariant 10).
        self.assertEqual(len(tip.source_event_ids), 8)

    def test_repolling_the_same_window_updates_instead_of_duplicating(self):
        Command()._write(self._assessed())
        Command()._write(self._assessed())
        self.assertEqual(Opportunity.objects.filter(kind="flight").count(), 1)
        self.assertEqual(SourceEvent.objects.filter(source=SOURCE).count(), 8)

    def test_tip_outlives_the_window_so_a_driver_can_still_get_there(self):
        Command()._write(self._assessed())
        tip = Opportunity.objects.get(kind="flight")
        self.assertGreater(tip.end_time, tip.start_time + dt.timedelta(minutes=30))


class BudgetTests(TestCase):
    @override_settings(SWEDAVIA_API_KEY="test-key")
    def test_exhausted_budget_stops_the_poll_visibly(self):
        """
        Synligt trasig slår tyst tom: en källa som slutat hämta ska synas som
        nere i pipelinevyn, inte som en lugn kväll utan ankomster.
        """
        SourceStatus.objects.create(
            source=SOURCE,
            ok=True,
            checked_at=timezone.now(),
            detail={
                "month": timezone.now().strftime("%Y-%m"),
                "calls": thresholds.FLIGHT_MONTHLY_CALL_BUDGET,
                "per_airport": {},
                "last_fetch": {},
            },
        )
        with self.assertRaises((RuntimeError, CommandError)):
            call_command("poll_flights", force=True)
        self.assertFalse(SourceStatus.objects.get(source=SOURCE).ok)

    @override_settings(SWEDAVIA_API_KEY="")
    def test_missing_key_is_reported_not_crashed(self):
        call_command("poll_flights", force=True)
        self.assertEqual(Opportunity.objects.filter(kind="flight").count(), 0)

    @override_settings(SWEDAVIA_API_KEY="test-key")
    def test_skipped_cycle_keeps_the_previous_counts(self):
        """
        En kadensöverhoppad cykel får inte nollställa larm/tips i pipelinevyn.
        Gör den det ser en frisk källa som just hämtat 335 ankomster likadan ut
        som en källa som slutat leverera -- precis den förväxling SourceStatus
        finns för att förhindra.
        """
        now = timezone.now()
        SourceStatus.objects.create(
            source=SOURCE, ok=True, checked_at=now, events=335, written=3,
            detail={
                "month": now.strftime("%Y-%m"),
                "calls": 6,
                "per_airport": {},
                # Alla flygplatser nyss hämtade -> ingen är mogen. Båda
                # slottarna: efter FLIGHT_TOMORROW_HOUR_FROM är morgondagen
                # också med, och utan den gick testet bara igenom före 21:00.
                "last_fetch": {
                    f"{iata}:{slot}": now.isoformat()
                    for iata in thresholds.AIRPORTS
                    for slot in ("today", "tomorrow")
                },
                "last_events": 335,
                "last_written": 3,
            },
        )
        call_command("poll_flights")
        status = SourceStatus.objects.get(source=SOURCE)
        self.assertTrue(status.ok)
        self.assertEqual(status.events, 335)
        self.assertEqual(status.written, 3)

    def test_counter_resets_on_a_new_month(self):
        now = timezone.now()
        SourceStatus.objects.create(
            source=SOURCE, ok=True, checked_at=now,
            detail={"month": "2001-01", "calls": 9999, "per_airport": {}, "last_fetch": {}},
        )
        state = Command()._load_state(now)
        self.assertEqual(state["calls"], 0)
        self.assertEqual(state["month"], now.strftime("%Y-%m"))


class CadenceTests(TestCase):
    def test_busy_airport_is_polled_more_often_than_a_quiet_one(self):
        """Arlanda var tionde minut, Kiruna var nittionde -- tre flyg om dygnet."""
        self.assertLess(
            thresholds.flight_poll_interval_minutes("ARN", 22),
            thresholds.flight_poll_interval_minutes("KRN", 22),
        )

    def test_off_peak_is_slower_than_peak(self):
        self.assertGreater(
            thresholds.flight_poll_interval_minutes("ARN", 9),
            thresholds.flight_poll_interval_minutes("ARN", 23),
        )

    def test_hour_windows_wrap_around_midnight(self):
        self.assertTrue(thresholds.is_flight_late_hour(23))
        self.assertTrue(thresholds.is_flight_late_hour(2))
        self.assertFalse(thresholds.is_flight_late_hour(12))
        self.assertTrue(thresholds.is_flight_night_hour(0))
        self.assertFalse(thresholds.is_flight_night_hour(21))

    def test_monthly_budget_stays_under_the_subscription_quota(self):
        """
        FlightInfo Free ger 10 001 anrop/30 dagar, och tio flygplatser delar
        på dem. Vaktas här och inte i en kommentar: en kadens som ändras utan
        att någon räknar om summan slår i taket mitt i månaden, och då slutar
        källan leverera tills nästa månadsskifte.
        """
        per_day = sum(thresholds.flight_calls_per_day(i) for i in thresholds.AIRPORTS)
        self.assertLess(per_day * 30, thresholds.FLIGHT_MONTHLY_CALL_BUDGET)
        # Och budgeten i sin tur under det prenumerationen faktiskt ger.
        self.assertLess(thresholds.FLIGHT_MONTHLY_CALL_BUDGET, 10001)

    def test_arlanda_gets_the_most_calls(self):
        """Där signalen finns ska pengarna läggas: 326 flyg mot Kirunas tre."""
        by_airport = {i: thresholds.flight_calls_per_day(i) for i in thresholds.AIRPORTS}
        self.assertEqual(max(by_airport, key=by_airport.get), "ARN")
