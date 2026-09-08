"""
Hämtar Trafikverkets väghändelser (Situation) och poängsätter dem.

Kör så här:
    python manage.py poll_road              # en cykel
    python manage.py poll_road --dry-run    # visa utan att skriva

Om utdatan mest består av nollor är det rätt svar, inte ett fel: väginfo
kapas medvetet lågt (max 15 poäng, se core/taxi_relevance.score_road_alert).
Den finns för att en förare ska veta att vägen dit är avstängd -- inte för
att skicka någon dit.
"""

from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from core.health import polling
from core.ingest import assess, dry_run_lines, write
from core.sources.smhi import cached_region_weather
from core.sources.trafikverket_road import configured_counties, fetch_road_situations

# Taket för hur länge ett vägtips får synas. Trafikverkets egen EndTime är
# ofta ett planeringsfönster -- ett vägarbete i stickprovet slutade 2029 --
# så den kapas mot det här. Fyra timmar är samma fönster som Node-workern
# gav vägtips, och pollcykeln förlänger det så länge händelsen ligger kvar
# i källan.
#
# Åt andra hållet respekteras källan: en avstängning som Trafikverket säger
# slutar kl 16 slutar visas kl 16, i stället för att hänga kvar fyra timmar
# till. Se docs/api-field-inventory.md, förslag 2.
ROAD_TTL = timedelta(hours=4)


class Command(BaseCommand):
    help = "Hämtar och poängsätter Trafikverkets väghändelser"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--counties",
            help="Kommaseparerade länsnamn, eller 'all'. Default: TRAFIKVERKET_COUNTIES.",
        )

    def handle(self, *args, **options):
        # Bokför utfallet oavsett hur det går -- en källa som slutat
        # svara ska synas som trasig, inte som lugn trafik. Se
        # core/health.py.
        with polling("trafikverket") as status:
            self._poll(options, status)

    def _poll(self, options, status):
        key = settings.TRAFIKVERKET_API_KEY
        if not key:
            raise CommandError("TRAFIKVERKET_API_KEY saknas i .env")

        counties = None
        if options.get("counties"):
            from core.sources.trafikverket_road import COUNTY

            counties = [
                COUNTY[n.strip().lower()]
                for n in options["counties"].split(",")
                if n.strip().lower() in COUNTY
            ] or None

        fetched = fetch_road_situations(key, counties)
        alerts = fetched["alerts"]
        status.events = len(alerts)
        self.stdout.write(
            f"{fetched['situations']} situationer → {len(alerts)} avvikelser "
            f"({len(counties or configured_counties())} län)"
        )
        if not alerts:
            self.stdout.write("inga väghändelser just nu")
            return

        now = timezone.now()
        horizon = now + ROAD_TTL
        for alert in alerts:
            alert["active_from"] = alert.get("active_from") or now
            source_end = alert.get("active_to")
            alert["active_to"] = (
                min(source_end, horizon) if source_end and source_end > now else horizon
            )

        assessed = assess(alerts)

        if options["dry_run"]:
            for line in dry_run_lines(assessed):
                self.stdout.write(line)
            self.stdout.write(f"\n{len(alerts)} väghändelser (inget skrevs)")
            return

        written, spread = write(
            "trafikverket", assessed, cached_region_weather(), kind="road"
        )
        status.written = written
        self.stdout.write(
            self.style.SUCCESS(f"skrev {written} vägtips | poängnivåer: {spread}")
        )
