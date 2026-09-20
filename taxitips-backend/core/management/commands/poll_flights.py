"""
Hämtar flygankomster från Swedavia och skriver ankomstvågor som tips.

Kör så här:
    python manage.py poll_flights --dry-run --force   # visa allt, skriv inget
    python manage.py poll_flights                     # en cykel, respekterar kadens
    python manage.py poll_flights --airport ARN --date 2026-09-13 --dry-run

Kadens och kvot
---------------
FlightInfo Free ger 10 001 anrop / 30 dagar och exponerar inga kvot-headers,
så räkningen sker här och sparas i SourceStatus.detail. Beat kör kommandot var
femte minut; kommandot avgör själv vilka flygplatser som är mogna, utifrån
flygplatsens egen kadens (thresholds.AIRPORTS). Att polla Malmö var tionde
minut för sju flyg om dygnet vore rent slöseri.
"""

from __future__ import annotations

import datetime as dt
import json

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from core import flight_scoring, thresholds
from core.health import polling
from core.models import SourceStatus
from core.repository import upsert_opportunities, upsert_source_events
from core.sources.swedavia import NON_ARRIVING_STATUSES, fetch_arrivals
from core.time_limits import reraise_time_limit

SOURCE = "swedavia"

# Hur länge tipset ligger kvar efter att sista planet landat. Ankomsthallen
# töms inte i samma sekund som hjulen tar mark -- bagage och passkontroll tar
# sin tid, och en förare som ser tipset 23:55 ska hinna dit.
TAIL_MINUTES = 45


class Command(BaseCommand):
    help = "Hämtar och poängsätter flygankomstvågor från Swedavia FlightInfo"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--airport",
            action="append",
            choices=sorted(thresholds.AIRPORTS),
            help="Bara den här flygplatsen (kan upprepas). Standard: alla.",
        )
        parser.add_argument("--date", help="Lokalt datum YYYY-MM-DD i stället för idag/imorgon.")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Strunta i kadensen och hämta allt nu.",
        )

    def handle(self, *args, **options):
        # Bokför utfallet oavsett hur det går -- en källa som slutat svara ska
        # synas som trasig, inte som en lugn kväll. Se core/health.py.
        with polling(SOURCE) as status:
            self._poll(options, status)

    # -- kvot- och kadensbokföring -------------------------------------------

    def _load_state(self, now) -> dict:
        """Kvoträknaren och senaste hämtning per flygplats, från förra rundan."""
        row = SourceStatus.objects.filter(source=SOURCE).first()
        state = dict((row.detail if row else None) or {})
        month = now.strftime("%Y-%m")
        # Kvoten är rullande 30 dagar hos Swedavia; vi nollar per kalendermånad,
        # vilket är strängare och därmed säkert.
        if state.get("month") != month:
            state = {"month": month, "calls": 0, "per_airport": {}, "last_fetch": {}}
        state.setdefault("calls", 0)
        state.setdefault("per_airport", {})
        state.setdefault("last_fetch", {})
        return state

    def _due(self, state, iata: str, slot: str, now, now_local, force: bool) -> bool:
        if force:
            return True
        if slot == "tomorrow":
            # Morgondagen alltid med den glesa kadensen -- samma antagande som
            # thresholds.flight_calls_per_day() räknar budgeten på.
            interval = thresholds.CADENCE[thresholds.AIRPORTS[iata]["cadence"]]["quiet_minutes"]
        else:
            interval = thresholds.flight_poll_interval_minutes(iata, now_local.hour)
        last = state["last_fetch"].get(f"{iata}:{slot}")
        if not last:
            return True
        try:
            when = dt.datetime.fromisoformat(last)
        except ValueError:
            return True
        return (now - when) >= dt.timedelta(minutes=interval)

    def _planned_fetches(self, options, state, now, now_local) -> list[tuple[str, dt.date, str]]:
        """(flygplats, datum, slot) för allt som ska hämtas den här cykeln."""
        airports = options["airport"] or sorted(thresholds.AIRPORTS)
        force = options["force"]

        if options["date"]:
            chosen = dt.date.fromisoformat(options["date"])
            return [(iata, chosen, "today") for iata in airports]

        planned = []
        for iata in airports:
            if self._due(state, iata, "today", now, now_local, force):
                planned.append((iata, now_local.date(), "today"))
            # Fönstret 00:00-05:59 ligger i morgondagens svar, eftersom {date}
            # är lokalt datum. Utan den här raden vore natten osynlig.
            if now_local.hour >= thresholds.FLIGHT_TOMORROW_HOUR_FROM and self._due(
                state, iata, "tomorrow", now, now_local, force
            ):
                planned.append((iata, now_local.date() + dt.timedelta(days=1), "tomorrow"))
        return planned

    # -- själva cykeln --------------------------------------------------------

    def _poll(self, options, status):
        key = settings.SWEDAVIA_API_KEY
        if not key:
            self.stderr.write("SWEDAVIA_API_KEY saknas")
            status.note = "SWEDAVIA_API_KEY saknas"
            status.fetched = False
            return

        now = timezone.now()
        now_local = timezone.localtime(now)
        state = self._load_state(now)
        budget = thresholds.FLIGHT_MONTHLY_CALL_BUDGET

        if state["calls"] >= budget:
            # Hellre synligt trasig än tyst tom: raise gör att core/health.py
            # skriver ok=False, och pipelinevyn visar källan som nere.
            status.detail = state
            raise RuntimeError(
                f"Swedavia-budgeten är slut ({state['calls']}/{budget} anrop denna månad)"
            )

        planned = self._planned_fetches(options, state, now, now_local)
        if not planned:
            status.detail = state
            # Bär fram förra cykelns siffror. Utan det nollställs larm/tips i
            # pipelinevyn varje gång kadensgrinden hoppar över en cykel -- och
            # en frisk källa som just hämtat 335 ankomster hade sett ut som en
            # källa som slutat leverera. Se core/health.py:s PollResult.
            status.events = state.get("last_events", 0)
            status.written = state.get("last_written", 0)
            # Ingen `note`: pipelinevyn renderar den i rött som ett fel, och
            # att kadensen gör sitt jobb är normal drift. Tidpunkten står
            # ändå i detail.last_fetch.
            self.stdout.write("ingen flygplats är mogen för hämtning än")
            return

        flights_by_airport: dict[str, list[dict]] = {}
        per_airport_note: dict[str, dict] = {}
        errors: list[str] = []

        for iata, date, slot in planned:
            if state["calls"] >= budget:
                errors.append("budgeten tog slut mitt i cykeln")
                break
            try:
                fetched = fetch_arrivals(key, iata, date)
            except Exception as exc:
                reraise_time_limit(exc)
                # En flygplats som fallerar får inte stoppa de andra. Samma
                # mönster som poll_trafiklab per operatör.
                errors.append(f"{iata} {date}: {exc}")
                continue

            state["calls"] += 1
            state["per_airport"][iata] = state["per_airport"].get(iata, 0) + 1
            state["last_fetch"][f"{iata}:{slot}"] = now.isoformat()

            flights_by_airport.setdefault(iata, []).extend(fetched)
            note = per_airport_note.setdefault(iata, {"arrivals": 0, "not_arriving": 0})
            note["arrivals"] += len(fetched)
            note["not_arriving"] += sum(
                1 for f in fetched if f.get("status") in NON_ARRIVING_STATUSES
            )

        assessed: list[tuple[flight_scoring.FlightWindow, flight_scoring.FlightAssessment]] = []
        for iata, flights in flights_by_airport.items():
            found = flight_scoring.windows(flights, iata, now)
            per_airport_note[iata]["windows"] = len(found)
            assessed.extend((w, flight_scoring.classify(w, now)) for w in found)

        assessed.sort(key=lambda pair: pair[0].start)

        state["budget"] = budget
        state["airports"] = per_airport_note
        state["errors"] = errors
        status.events = sum(len(f) for f in flights_by_airport.values())
        if errors:
            status.note = "; ".join(errors)[:500]

        if options["dry_run"]:
            status.detail = state
            self._report(assessed, state, per_airport_note, wrote=False)
            return

        status.written = self._write(assessed)
        # Sparas så att en kadensöverhoppad cykel kan bära fram dem i stället
        # för att nollställa vyn.
        state["last_events"] = status.events
        state["last_written"] = status.written
        status.detail = state
        self._report(assessed, state, per_airport_note, wrote=True)

    # -- skrivning ------------------------------------------------------------

    def _write(self, assessed) -> int:
        if not assessed:
            return 0

        # Källhändelserna först: tipsen citerar deras id:n, och det är den
        # kopplingen förarens förklaringspanel bygger på. Bara flygen som
        # faktiskt räknades in i ett fönster skrivs -- resten av dygnets 230
        # ankomster är inte del av någon motivering.
        rows = {}
        for window, _assessment in assessed:
            airport = window.config
            for flight in window.flights:
                rows[flight_scoring.flight_external_id(flight)] = {
                    "source": SOURCE,
                    "external_id": flight_scoring.flight_external_id(flight),
                    "mode": "flight",
                    "active_from": flight["effective"],
                    "active_to": window.end + dt.timedelta(minutes=TAIL_MINUTES),
                    "raw": json.dumps(
                        {
                            "flight_id": flight["flight_id"],
                            "airport": flight["airport"],
                            "airline": flight["airline"],
                            "airline_iata": flight["airline_iata"],
                            "origin": flight["origin"],
                            "origin_iata": flight["origin_iata"],
                            "scheduled": _iso(flight["scheduled"]),
                            "estimated": _iso(flight["estimated"]),
                            "actual": _iso(flight["actual"]),
                            "delay_minutes": flight["delay_minutes"],
                            # Statustexten sparas rå så att en framtida läsare
                            # ser att DEL betyder "Borttagen", inte "Delayed".
                            "status": flight["status"],
                            "status_text": flight["status_text"],
                            "terminal": flight["terminal"],
                            "di_indicator": flight["di_indicator"],
                        },
                        ensure_ascii=False,
                    ),
                    "lat": airport["lat"],
                    "lon": airport["lon"],
                }

        source_ids = upsert_source_events(rows.values())

        return upsert_opportunities([
            {
                "external_id": window.external_id,
                # Varken "transit" eller "road". core/api.py delar bara ut
                # vägtips som `context`, så "flight" hamnar rätt: i listan.
                "kind": "flight",
                "mode": "flight",
                "severity_tier": assessment.tier,
                # Samma grova nivå som de andra pollarna skriver. Det föraren
                # ser är INTE den här utan thresholds.customer_likelihood(),
                # som core/api.py räknar fram vid varje svar.
                "level": "high" if assessment.score >= 60 else "medium",
                "title": flight_scoring.title(window),
                "summary": flight_scoring.summary(window),
                "lat": window.config["lat"],
                "lon": window.config["lon"],
                "h3_index": "",
                # places[0] blir push-prefixet och matchas som delsträng mot
                # förarens valda orter -- "Stockholm Arlanda" träffar därför
                # "Stockholm" i REGION_CITIES. Se core/notify.py.
                "places": json.dumps([window.config["name"]], ensure_ascii=False),
                "region": window.config["region"],
                "start_time": window.start,
                "end_time": window.end + dt.timedelta(minutes=TAIL_MINUTES),
                "demand_score": assessment.score,
                "confidence": assessment.confidence,
                "reasons": json.dumps(assessment.reasons, ensure_ascii=False),
                "rule_id": assessment.rule_id,
                "source_event_ids": json.dumps([
                    source_ids[fid]
                    for fid in (
                        flight_scoring.flight_external_id(f) for f in window.flights
                    )
                    if fid in source_ids
                ]),
                # Lagstadgad förseningsersättning gäller kollektivtrafik, inte
                # flyg -- EU261 är en annan ordning med andra belopp och gäller
                # mot flygbolaget, aldrig som taxiersättning. Se core/compensation.py.
                "compensation_eligible": False,
                "compensation_amount_kr": None,
                # Vi har ingen tidtabell för Arlanda Express eller flygbussarna.
                # NULL betyder "vet inte", vilket är sant -- och skiljer sig
                # från att påstå att nästa avgång saknas (invariant 2).
                "next_departure_minutes": None,
                "next_departure_at": None,
                "is_last_departure": False,
                "has_alternative": False,
                "alternative_note": "",
            }
            for window, assessment in assessed
        ])

    # -- utskrift -------------------------------------------------------------

    def _report(self, assessed, state, per_airport_note, *, wrote: bool):
        for window, assessment in assessed:
            self.stdout.write(
                f"  {window.airport}  {window.local_start:%Y-%m-%d} {window.label()}"
                f"  {window.arrivals:3} ankomster, {len(window.delayed):2} sena"
                f"  ->  {assessment.score:3}  {assessment.tier}  ({assessment.confidence})"
            )
        for iata, note in sorted(per_airport_note.items()):
            self.stdout.write(
                f"  {iata}: {note['arrivals']} ankomster hämtade, "
                f"{note['not_arriving']} borttagna/inställda, "
                f"{note.get('windows', 0)} fönster över tröskeln"
            )
        tail = f"anrop denna månad: {state['calls']}/{thresholds.FLIGHT_MONTHLY_CALL_BUDGET}"
        if not wrote:
            self.stdout.write(f"\n{len(assessed)} fönster (inget skrevs) | {tail}")
            return
        self.stdout.write(self.style.SUCCESS(
            f"\nskrev {len(assessed)} tips | poängnivåer: "
            f"{sorted({a.score for _, a in assessed}, reverse=True)} | {tail}"
        ))


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value else None
