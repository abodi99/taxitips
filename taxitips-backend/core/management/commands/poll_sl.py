"""
Hämtar SL:s (Stockholm) trafikstörningar och poängsätter dem.

Uppdaterar samtidigt StopArea-registret (operator="sl") -- SL:s egen
platsupplösning OCH den delade gazetteer-slagningen i
core.geo.resolve_coords förutsätter ett färskt register.

Kör så här:
    python manage.py poll_sl              # en cykel
    python manage.py poll_sl --dry-run    # visa utan att skriva
    python manage.py poll_sl --skip-sites # hoppa över registret (snabbare)
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.ingest import assess, dry_run_lines, write
from core.models import StopArea
from core.sources.sl import build_site_index, fetch_sl_deviations, fetch_sl_sites


class Command(BaseCommand):
    help = "Hämtar och poängsätter SL-störningar (tåg/tunnelbana/spårvagn/buss)"

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument(
            "--skip-sites", action="store_true",
            help="Hoppa över hållplatsregistret (snabbare, sämre platsupplösning om det saknas sedan tidigare)",
        )

    def handle(self, *args, **options):
        if not options["skip_sites"]:
            self.stdout.write("uppdaterar hållplatsregister...")
            rows = fetch_sl_sites()
            now = timezone.now()
            StopArea.objects.bulk_create(
                [
                    StopArea(gid=r["gid"], operator="sl", name=r["name"], lat=r["lat"], lon=r["lon"], fetched_at=now)
                    for r in rows
                ],
                update_conflicts=True, unique_fields=["gid"],
                update_fields=["operator", "name", "lat", "lon", "fetched_at"],
            )
            self.stdout.write(f"  {len(rows)} hållplatser")

        site_rows = list(StopArea.objects.filter(operator="sl").values("gid", "lat", "lon"))
        site_index = build_site_index(site_rows)

        fetched = fetch_sl_deviations(site_index=site_index)
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

        written, spread = write("sl", assessed)
        self.stdout.write(self.style.SUCCESS(f"skrev {written} tips | poängnivåer: {spread}"))
