"""
Hämtar kommande evenemang i hela Sverige från Ticketmaster.

    python manage.py poll_events --dry-run     # visa, skriv inget
    python manage.py poll_events               # hämta, spara, rensa
    python manage.py poll_events --days 30     # kortare horisont
    python manage.py poll_events --source predicthq

Beat kör kommandot var sjätte timme (events.ingest.CADENCE_HOURS). Resultatet
syns på pipeline-sidan, avsnitt 2c, och i source_status-raden `ticketmaster`.

PredictHQ hämtas och sparas bara när events/rights.py tillåter lagring -- en
rättighetsreferens till ett skriftligt avtal. Annars görs inget anrop, och skälet
står i källstatus. Utan avtal visar pipeline-sidan PredictHQ live (events/live.py).
"""

from __future__ import annotations

import datetime as dt
from collections import Counter

from django.conf import settings
from django.core.management.base import BaseCommand
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
        sources = ingest.SOURCES if options["source"] == "all" else (options["source"],)
        for source in sources:
            with polling(source) as status:
                if source == ingest.PREDICTHQ:
                    self._poll_predicthq(options, status)
                elif source == ingest.THESPORTSDB:
                    self._poll_thesportsdb(options, status)
                else:
                    self._poll_ticketmaster(options, status)

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

    # En månad räcker för en förare, och PredictHQ:s planer kapar långa horisonter.
    PREDICTHQ_MAX_DAYS = 30

    def _poll_predicthq(self, options, status):
        rights = rights_for(ingest.PREDICTHQ)
        if not rights.may_store():
            # Inget anrop alls: utan rätt att lagra finns inget att hämta hit.
            status.note = rights.refusal("store")
            status.fetched = False
            self.stdout.write(f"predicthq: {status.note}")
            return
        token = settings.PREDICTHQ_ACCESS_TOKEN
        if not token:
            status.note = "PREDICTHQ_ACCESS_TOKEN saknas"
            status.fetched = False
            self.stderr.write(status.note)
            return

        now = timezone.now()
        days = min(options["days"], self.PREDICTHQ_MAX_DAYS)
        today = now.astimezone(timing.STOCKHOLM).date()
        until = today + dt.timedelta(days=days)
        raw_events, stats = predicthq.fetch_events(predicthq.Client(token), today, until)
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
        # Arenorna ur förra körningen: en uppslagning per arena, inte per körning.
        from core.models import SourceStatus

        previous = SourceStatus.objects.filter(source=ingest.THESPORTSDB).first()
        venues = dict(((previous.detail or {}) if previous else {}).get("venues") or {})
        raw_events, stats = thesportsdb.fetch_events(thesportsdb.Client(key), now, end, venues)
        if stats["errors"] and len(stats["errors"]) == len(stats["leagues"]):
            # Ingen liga svarade: ett fel i källstatusen, inte en tom "lyckad" hämtning.
            raise thesportsdb.TheSportsDbError(" | ".join(stats["errors"]))
        rows = [row for row in (ingest.build_row(e, ingest.THESPORTSDB) for e in raw_events) if row]
        status.events = len(raw_events)
        status.note = " | ".join(stats["errors"])
        detail = {**stats, "horizonDays": options["days"], "normalized": len(rows), "venues": venues}

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
