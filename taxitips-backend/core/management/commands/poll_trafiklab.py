"""
Hämtar och poängsätter Trafiklab-larm (tåg/buss, GTFS-Realtime ServiceAlerts).

Kör så här:
    python manage.py poll_trafiklab            # en cykel
    python manage.py poll_trafiklab --dry-run  # visa utan att skriva
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from core.health import polling
from core.ingest import assess, dry_run_lines, write
from core.sources.smhi import cached_region_weather
from core.sources.trafiklab import fetch_trafiklab_alerts


class Command(BaseCommand):
    help = "Hämtar och poängsätter Trafiklab-larm (tåg/buss)"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        # Bokför utfallet oavsett hur det går -- en källa som slutat
        # svara ska synas som trasig, inte som lugn trafik. Se
        # core/health.py.
        with polling("trafiklab") as status:
            self._poll(options, status)

    def _poll(self, options, status):
        key = settings.TRAFIKLAB_API_KEY
        if not key:
            self.stderr.write("TRAFIKLAB_API_KEY saknas")
            return

        fetched = fetch_trafiklab_alerts(key)
        alerts = fetched["alerts"]
        status.events = len(alerts)

        # Utfall per operatör, inte bara summan: en region som 404:ar ser
        # annars ut som en region utan störningar. Räknas på larmens egen
        # region-nyckel, som fetch_operator_alerts sätter.
        per_operator = {op: {"ok": True, "alerts": 0} for op in fetched.get("operators") or []}
        for a in alerts:
            row = per_operator.get(a.get("region"))
            if row:
                row["alerts"] += 1
        for err in fetched.get("errors") or []:
            per_operator[err["operator"]] = {"ok": False, "alerts": 0, "error": err["error"][:200]}
        status.detail = per_operator
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

        written, spread = write("trafiklab", assessed, cached_region_weather())
        status.written = written
        self.stdout.write(self.style.SUCCESS(f"skrev {written} tips | poängnivåer: {spread}"))
