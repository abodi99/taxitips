"""
Kör hela pipelinen kontinuerligt i en process -- Djangos motsvarighet till
worker/index.js:s tre oberoende setInterval-loopar (60s huvudpoll, 24h
GTFS-uppdatering, 24h SL-hållplatsuppdatering).

Utan den här loopen är varje poll_*-kommando en engångskörning: data blir
inaktuell inom en timme (rails 1h-fönster, se PLATFORM_LIFETIME i
trafikverket_rail.py) tills någon kör kommandot manuellt igen -- precis det
som hände tidigare i den här sessionen.

En enkel loop i en process, samma mönster som Node-workern redan bevisat
fungerar, bara portad. Celery Beat (core/tasks.py) är sedan Spår B den
rekommenderade vägen lokalt via `docker compose up` -- det här kommandot
lämnas oförändrat som en beroendefri reservväg (ingen Redis behövs) för
snabba manuella körningar.

    python manage.py run_pipeline          # kör tills avbrutet (Ctrl-C)
    python manage.py run_pipeline --once   # en cykel av allt, avsluta sedan

Körs lokalt i en terminal, eller i bakgrunden med t.ex.
`nohup python manage.py run_pipeline > pipeline.log 2>&1 &`.
"""

import logging
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand

log = logging.getLogger(__name__)

# Störningspollarna delar en cykel. Node kör en enda källa (allt samlat)
# var 60:e sekund; här delar fyra källor samma cykel, så något glesare
# håller sig inom samma anda utan att öka anropstakten mot varje API.
POLL_INTERVAL_SECONDS = 90

# Hållplats-/stationsregistren (SL, Västtrafik) ändras sällan -- samma
# 24h-kadens som Node:s gtfsRefreshLoop/slSitesRefreshLoop.
SITES_REFRESH_SECONDS = 24 * 60 * 60

# AI-granskningen är billig och cachead (se core/genkit.py), men kör den
# glesare än störningspollarna ändå -- den granskar bara confidence=low,
# som inte förändras varje cykel.
REVIEW_INTERVAL_SECONDS = 5 * 60

# (kommando, extra kwargs). site-uppdatering styrs separat nedan via
# skip_sites, så den bara körs var 24:e timme, inte varje 90s-cykel.
DISRUPTION_COMMANDS = ["poll_rail", "poll_trafiklab", "poll_sl", "poll_vasttrafik"]
SITE_AWARE_COMMANDS = {"poll_sl", "poll_vasttrafik"}


class Command(BaseCommand):
    help = "Kör poll_rail/poll_trafiklab/poll_sl/poll_vasttrafik/review_uncertain kontinuerligt"

    def add_arguments(self, parser):
        parser.add_argument(
            "--once", action="store_true",
            help="Kör en cykel av allt och avsluta, i stället för att loopa",
        )

    def handle(self, *args, **options):
        last_sites_refresh = 0.0
        last_review = 0.0
        cycle = 0

        while True:
            cycle += 1
            cycle_start = time.monotonic()
            refresh_sites = (time.monotonic() - last_sites_refresh) >= SITES_REFRESH_SECONDS
            written = {}

            for name in DISRUPTION_COMMANDS:
                kwargs = {"skip_sites": not refresh_sites} if name in SITE_AWARE_COMMANDS else {}
                try:
                    call_command(name, **kwargs)
                except Exception:
                    # En källas fel får aldrig stoppa de andra -- samma
                    # princip som poller.js:s per-källa try/catch.
                    log.exception("run_pipeline: %s misslyckades, fortsätter", name)

            if refresh_sites:
                last_sites_refresh = time.monotonic()

            if (time.monotonic() - last_review) >= REVIEW_INTERVAL_SECONDS:
                try:
                    call_command("review_uncertain")
                except Exception:
                    log.exception("run_pipeline: review_uncertain misslyckades")
                last_review = time.monotonic()

            self.stdout.write(
                f"[cykel {cycle}] klar på {time.monotonic() - cycle_start:.1f}s"
                + (" (hållplatsregister uppdaterat)" if refresh_sites else "")
            )

            if options["once"]:
                return

            elapsed = time.monotonic() - cycle_start
            time.sleep(max(0.0, POLL_INTERVAL_SECONDS - elapsed))
