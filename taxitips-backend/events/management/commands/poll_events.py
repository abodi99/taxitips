"""
Hämtar kommande evenemang i hela Sverige: Ticketmaster (konserter m.m.) och TheSportsDB
(fotboll, ishockey, handboll). PredictHQ är avslutad sedan 2026-09-26 och hämtas inte.

    python manage.py poll_events --dry-run     # visa, skriv inget
    python manage.py poll_events               # hämta, spara, rensa
    python manage.py poll_events --days 30     # kortare horisont
    python manage.py poll_events --source predicthq

Beat kör kommandot var sjätte timme (events.ingest.CADENCE_HOURS). Resultatet
syns på pipeline-sidan, avsnitt 2c, och i source_status-raden `ticketmaster`.

PredictHQ hämtas och sparas bara när events/rights.py tillåter lagring -- en
rättighetsreferens och en källa som inte är avslutad (`retired`). Annars görs inget
anrop, och skälet står i källstatus.

Varje källa hämtas för sig: ett fel i en källa skrivs i dess källstatus och stoppar
inte de andra. Kommandot felar ändå (CommandError) efteråt, så att felet syns i Celery.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.health import polling
from events import ingest, timing
from events.rights import rights_for
from events.sources import predicthq, thesportsdb, ticketmaster


class Command(BaseCommand):
    help = "Hämtar kommande evenemang i Sverige från källorna"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--days", type=int, default=ingest.DEFAULT_HORIZON_DAYS, help="Hur långt fram att hämta.")
        parser.add_argument("--source", choices=("all", *ingest.SOURCES), default="all")

    def handle(self, *args, **options):
        from celery.exceptions import SoftTimeLimitExceeded

        sources = ingest.SOURCES if options["source"] == "all" else (options["source"],)
        failed = []
        for source in sources:
            # En källas fel stoppar aldrig de andra. Fram till 2026-10-09 kastade PredictHQ:s
            # 402 (prenumerationen gick ut 2026-09-26) ur hela kommandot innan TheSportsDB
            # hann hämtas -- sporten stod still i två veckor utan att någon källa såg trasig ut.
            try:
                with polling(source) as status:
                    if source == ingest.PREDICTHQ:
                        self._poll_predicthq(options, status)
                    elif source == ingest.THESPORTSDB:
                        self._poll_thesportsdb(options, status)
                    else:
                        self._poll_ticketmaster(options, status)
            except SoftTimeLimitExceeded:
                raise
            except predicthq.SubscriptionExpired as exc:
                # Ett känt läge som bara ägaren kan lösa: står i källstatusen, men är inget
                # fel i körningen och ska inte larma i Celery var sjätte timme.
                self.stderr.write(f"{source}: {exc}")
            except Exception as exc:  # polling() har redan skrivit felet i källstatus
                failed.append(f"{source}: {type(exc).__name__}: {exc}")
                self.stderr.write(f"{source}: {type(exc).__name__}: {exc}")
        if failed:
            raise CommandError("; ".join(failed))

    def _poll_ticketmaster(self, options, status):
        rights = rights_for(ingest.TICKETMASTER)
        if not rights.may_store():
            status.note = rights.refusal("store")
            status.fetched = False
            self.stdout.write(f"ticketmaster: {status.note}")
            return
        key = settings.TICKETMASTER_API_KEY
        if not key:
            self.stderr.write("TICKETMASTER_API_KEY saknas")
            status.note = "TICKETMASTER_API_KEY saknas"
            status.fetched = False
            return

        now = timezone.now()
        end = now + dt.timedelta(days=options["days"])
        raw_events, stats = ticketmaster.fetch_events(ticketmaster.Client(key), now - ingest.LOOKBACK, end)
        rows = [row for row in (ingest.build_row(e) for e in raw_events) if row]
        status.events = len(raw_events)
        detail = {**stats, "horizonDays": options["days"], "normalized": len(rows)}

        if options["dry_run"]:
            status.detail = detail
            self._report(rows, detail, wrote=False)
            return

        saved = ingest.save(
            rows, source=ingest.TICKETMASTER, now=now, fetched_until=end.astimezone(timing.STOCKHOLM).date(),
            complete=not stats["truncated"],
        )
        purged = ingest.purge(now)
        status.written = len(rows)
        status.detail = {**detail, **saved, **purged}
        if stats["truncated"]:
            status.note = f"{stats['truncated']} fönster kapade vid 1000 träffar; inget markerades som borta"
        self._report(rows, status.detail, wrote=True)

    # 90 dagar framåt enligt avtalet 2026-10-09 (ägarens önskan: se kvällar och helger i god
    # tid). Hämtas var 6:e timme (beat poll-events) och sparas; appen läser databasen.
    PREDICTHQ_MAX_DAYS = 90
    PREDICTHQ_STATE = "predicthq"

    def _poll_predicthq(self, options, status):
        rights = rights_for(ingest.PREDICTHQ)
        if not rights.may_store():
            # Inget anrop alls: utan rätt att lagra finns inget att hämta hit. Avslutad källa
            # (prenumerationen gick ut 2026-09-26): hämtas inte, lagrade rader ligger kvar.
            status.note = rights.refusal("store")
            status.fetched = False
            self.stdout.write(f"predicthq: hämtas inte -- {status.note}")
            return
        token = settings.PREDICTHQ_ACCESS_TOKEN
        if not token:
            status.note = "PREDICTHQ_ACCESS_TOKEN saknas"
            status.fetched = False
            self.stderr.write(status.note)
            return

        from events.models import PollState

        now = timezone.now()
        checked = PollState.load(self.PREDICTHQ_STATE).get("expiredAt") or ""
        if checked and checked > (now - dt.timedelta(hours=24)).isoformat():
            # Abonnemanget var slut vid förra kontrollen: fråga högst en gång per dygn.
            raise predicthq.SubscriptionExpired(predicthq.EXPIRED_MESSAGE)

        days = min(options["days"], self.PREDICTHQ_MAX_DAYS)
        today = now.astimezone(timing.STOCKHOLM).date()
        until = today + dt.timedelta(days=days)
        try:
            raw_events, stats = predicthq.fetch_events(predicthq.Client(token), today, until)
        except predicthq.SubscriptionExpired:
            PollState.store(self.PREDICTHQ_STATE, {"expiredAt": now.isoformat()})
            raise
        PollState.store(self.PREDICTHQ_STATE, {})
        rows = [row for row in (ingest.build_row(e, ingest.PREDICTHQ) for e in raw_events) if row]
        status.events = len(raw_events)
        detail = {**stats, "horizonDays": days, "normalized": len(rows), "rightsReference": rights.store_reference}
        if options["dry_run"]:
            status.detail = detail
            self.stdout.write(f"predicthq: {len(rows)} evenemang (dry-run: inget skrevs)")
            return

        complete = not (stats.get("overflow") or stats.get("truncated"))
        saved = ingest.save(rows, source=ingest.PREDICTHQ, now=now, fetched_until=until, complete=complete)
        status.written = len(rows)
        status.detail = {**detail, **saved}
        if not complete:
            status.note = "PredictHQ kapade svaret; inget markerades som borta"
        self.stdout.write(self.style.SUCCESS(
            f"predicthq: sparade {len(rows)} ({saved['created']} nya, {saved['updated']} uppdaterade)"
        ))

    def _report(self, rows, detail, *, wrote: bool):
        now = timezone.now()
        addons = [r for r in rows if timing.addon_reason(r["name"])]
        # Hämtningen går tolv timmar bakåt för att pågående evenemang ska finnas
        # kvar; det som redan tagit slut hör inte hemma i "närmast".
        visible = [r for r in rows if not (r["end_at"] and r["end_at"] <= now)]
        self.stdout.write(
            f"{len(rows)} evenemang ({len(addons)} med tilläggsnamn) i {detail.get('windows', '-')} fönster, "
            f"{detail.get('calls', '-')} anrop, kvot kvar: {detail.get('rateLimitAvailable', '-')}"
        )
        self.stdout.write("  orter:      " + ", ".join(
            f"{c or '?'} {n}" for c, n in Counter(r["city"] for r in visible).most_common(8)
        ))
        self.stdout.write("  kategorier: " + ", ".join(
            f"{timing.CATEGORY_LABELS[c]} {n}" for c, n in Counter(r["category"] for r in visible).most_common()
        ))
        basis = Counter(r["end_basis"] for r in visible)
        self.stdout.write(
            f"  sluttid:    {basis['source']} från källan, {basis['estimated']} uppskattade, {basis['unknown']} okända"
        )
        self.stdout.write("\n  närmast:")
        soonest = sorted(visible, key=lambda r: (r["start_date"], r["start_at"] is None, r["start_at"] or now))
        for r in soonest[:12]:
            start = r["start_at"].astimezone(timing.STOCKHOLM).strftime("%H:%M") if r["start_at"] else "--:--"
            end = r["end_at"].astimezone(timing.STOCKHOLM).strftime("%H:%M") if r["end_at"] else "?"
            marker = "≈" if r["end_basis"] == timing.BASIS_ESTIMATED else " "
            self.stdout.write(
                f"    {r['start_date']} {start}-{marker}{end}  {r['name'][:42]:<42}  "
                f"{(r['venue_name'] or r['address'])[:24]:<24} {r['city']}"
            )
        if addons:
            self.stdout.write("\n  tilläggsnamn (döljs bara om huvudevenemanget finns samma dag och plats):")
            for r in addons[:8]:
                self.stdout.write(f"    {r['start_date']} {r['name'][:58]:<58} -> {timing.display_name(r['name'])[:40]}")
        if wrote:
            self.stdout.write(self.style.SUCCESS(
                f"\nsparade {len(rows)} ({detail['created']} nya, {detail['updated']} uppdaterade), "
                f"{detail['hidden']} tilläggsposter dolda, {detail['markedMissing']} borta ur källan, "
                f"raderade {detail['purgedPast']} passerade och {detail['purgedMissing']} försvunna"
            ))
        else:
            self.stdout.write("\n(dry-run: inget skrevs)")

    # Hela kommandot får 900 s av Celery (core.tasks.EVENTS_LIMITS). TheSportsDB går sist och
    # får högst tio minuter: en normal körning är ~100 anrop à 2,5 s, alltså drygt fyra.
    THESPORTSDB_BUDGET_S = 600
    THESPORTSDB_STATE = "thesportsdb"

    def _poll_thesportsdb(self, options, status):
        rights = rights_for(ingest.THESPORTSDB)
        if not rights.may_store():
            status.note = rights.refusal("store")
            status.fetched = False
            self.stdout.write(f"thesportsdb: {status.note}")
            return
        key = getattr(settings, "THESPORTSDB_API_KEY", "")
        if not key:
            self.stderr.write("THESPORTSDB_API_KEY är tom")
            status.note = "THESPORTSDB_API_KEY är tom"
            status.fetched = False
            return

        now = timezone.now()
        end = now + dt.timedelta(days=options["days"])
        # Arenor, säsonger och var förra körningen slutade ligger i databasen (PollState).
        # De låg förut i källstatusens detail, som töms vid varje fel: ett enda fel tappade
        # alla arenor, nästa körning behövde hundratals uppslag, hann inte klart och felade igen.
        from events.models import PollState

        state = PollState.load(self.THESPORTSDB_STATE)
        venues = dict(state.get("venues") or {})
        today = now.date().isoformat()
        # Säsongen byts en gång om året: slå upp den högst en gång i veckan.
        fresh = (state.get("seasonsAt") or "") >= (now - dt.timedelta(days=7)).date().isoformat()
        seasons = dict(state.get("seasons") or {}) if fresh else {}
        client = thesportsdb.Client(key, budget_s=self.THESPORTSDB_BUDGET_S)
        resume_at = state.get("resumeAt")
        try:
            # Börja där förra körningen slutade: källan släpper igenom ungefär 17 anrop per
            # två minuter (uppmätt 2026-11-11), så alla tio ligor ryms inte i en körning.
            raw_events, stats = thesportsdb.fetch_events(
                client, now, end, venues, first_league=resume_at, seasons=seasons,
            )
            resume_at = stats.get("resumeAt")
        finally:
            # Också när körningen avbryts: uppslagen som hanns med ska inte göras om.
            if not options["dry_run"]:
                PollState.store(self.THESPORTSDB_STATE, {
                    "venues": venues, "seasons": seasons,
                    "seasonsAt": state.get("seasonsAt") if fresh else today,
                    "resumeAt": resume_at,
                })
        if stats["errors"] and len(stats["errors"]) == len(stats["leagues"]):
            # Ingen liga svarade: ett fel i källstatusen, inte en tom "lyckad" hämtning.
            raise thesportsdb.TheSportsDbError(" | ".join(stats["errors"]))
        rows = [row for row in (ingest.build_row(e, ingest.THESPORTSDB) for e in raw_events) if row]
        status.events = len(raw_events)
        notes = list(stats["errors"])
        if stats.get("skipped"):
            notes.append("Hann inte med: " + ", ".join(stats["skipped"]) + " (tas nästa körning)")
        status.note = " | ".join(notes)
        detail = {**stats, "horizonDays": options["days"], "normalized": len(rows), "venuesCached": len(venues)}

        if options["dry_run"]:
            status.detail = detail
            self._report(rows, detail, wrote=False)
            return

        # Borta-markeringen bara efter en komplett hämtning: en liga som felade får inte
        # radera sina matcher.
        saved = ingest.save(
            rows, source=ingest.THESPORTSDB, now=now, fetched_until=end.astimezone(timing.STOCKHOLM).date(),
            complete=stats["complete"],
        )
        purged = ingest.purge(now)
        status.written = len(rows)
        status.detail = {**detail, **saved, **purged}
        self._report(rows, status.detail, wrote=True)
