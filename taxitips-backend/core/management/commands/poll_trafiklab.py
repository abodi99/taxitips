"""
Hämtar och poängsätter Trafiklab-larm (tåg/buss, GTFS-Realtime ServiceAlerts).

Kör så här:
    python manage.py poll_trafiklab            # en cykel
    python manage.py poll_trafiklab --dry-run  # visa utan att skriva
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from core.ingest import assess, dry_run_lines, write
from core.sources.trafiklab import fetch_trafiklab_alerts


class Command(BaseCommand):
    help = "Hämtar och poängsätter Trafiklab-larm (tåg/buss)"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        key = settings.TRAFIKLAB_API_KEY
        if not key:
            self.stderr.write("TRAFIKLAB_API_KEY saknas")
            return

        fetched = fetch_trafiklab_alerts(key)
        alerts = fetched["alerts"]
        if not alerts:
            self.stdout.write("inga störningar just nu")
            return
        for err in fetched.get("errors") or []:
            self.stderr.write(self.style.WARNING(f"  {err['operator']}: {err['error']}"))

        assessed = assess(alerts)

        if options["dry_run"]:
            for line in dry_run_lines(assessed):
                self.stdout.write(line)
            self.stdout.write(f"\n{len(alerts)} störningar (inget skrevs)")
            return

        written, spread = write("trafiklab", assessed)
        self.stdout.write(self.style.SUCCESS(f"skrev {written} tips | poängnivåer: {spread}"))
