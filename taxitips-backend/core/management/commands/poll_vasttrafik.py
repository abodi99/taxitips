"""
Hämtar Västtrafiks (Göteborg) trafiksituationer och poängsätter dem.

Uppdaterar samtidigt StopArea-registret (operator="vt") -- situationsflödet
bär bara stopAreaGid, ingen koordinat, så registret krävs för att placera
ett Göteborgstips på kartan alls.

Kör så här:
    python manage.py poll_vasttrafik              # en cykel
    python manage.py poll_vasttrafik --dry-run    # visa utan att skriva
    python manage.py poll_vasttrafik --skip-sites # hoppa över registret
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.ingest import assess, dry_run_lines, write
from core.models import StopArea
from core.sources.vasttrafik import (
    build_stop_area_index, fetch_vasttrafik_situations, fetch_vasttrafik_stop_areas,
)


class Command(BaseCommand):
    help = "Hämtar och poängsätter Västtrafik-störningar (tåg/spårvagn/buss/båt)"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--skip-sites", action="store_true",
            help="Hoppa över hållplatsregistret (snabbare, sämre platsupplösning om det saknas sedan tidigare)",
        )

    def handle(self, *args, **options):
        client_id = settings.VASTTRAFIK_CLIENT_ID
        client_secret = settings.VASTTRAFIK_CLIENT_SECRET
        if not client_id or not client_secret:
            self.stderr.write("VASTTRAFIK_CLIENT_ID/VASTTRAFIK_CLIENT_SECRET saknas")
            return

        if not options["skip_sites"]:
            self.stdout.write("uppdaterar hållplatsregister...")
            rows = fetch_vasttrafik_stop_areas(client_id, client_secret)
            now = timezone.now()
            StopArea.objects.bulk_create(
                [
                    StopArea(gid=r["gid"], operator="vt", name=r["name"], lat=r["lat"], lon=r["lon"], fetched_at=now)
                    for r in rows
                ],
                update_conflicts=True, unique_fields=["gid"],
                update_fields=["operator", "name", "lat", "lon", "fetched_at"],
            )
            self.stdout.write(f"  {len(rows)} hållplatsområden")

        stop_area_rows = list(StopArea.objects.filter(operator="vt").values("gid", "lat", "lon"))
        stop_area_index = build_stop_area_index(stop_area_rows)

        fetched = fetch_vasttrafik_situations(client_id, client_secret, stop_area_index=stop_area_index)
        if fetched.get("skipped"):
            self.stderr.write(f"hoppade över: {fetched['skipped']}")
            return

        alerts = fetched["alerts"]
        if not alerts:
            self.stdout.write("inga störningar just nu")
            return

        assessed = assess(alerts)

        if options["dry_run"]:
            for line in dry_run_lines(assessed):
                self.stdout.write(line)
            self.stdout.write(f"\n{len(alerts)} störningar (inget skrevs)")
            return

        written, spread = write("vt", assessed)
        self.stdout.write(self.style.SUCCESS(f"skrev {written} tips | poängnivåer: {spread}"))
