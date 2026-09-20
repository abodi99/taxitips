"""
Räknar county_code och area_codes för tips som skrevs innan länen fanns.

    python manage.py backfill_areas          # aktiva och senaste dygnets tips
    python manage.py backfill_areas --all    # alla utan län

Tar inte bort något och rör bara de två kolumnerna. Nästa pollrunda skriver dem
ändå för allt som fortfarande finns i källan; kommandot finns för att
notisbeslutet ska ha län direkt efter migreringen.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core import areas
from core.models import Opportunity


class Command(BaseCommand):
    help = "Fyller i län för befintliga tips (tar inte bort något)"

    def add_arguments(self, parser):
        parser.add_argument("--all", action="store_true", help="Även tips som tog slut för mer än ett dygn sedan.")

    def handle(self, *args, **options):
        # Utan kommun: skrivna innan länen fanns, eller innan kommunerna kom.
        rows = Opportunity.objects.filter(municipality_code__isnull=True)
        if not options["all"]:
            rows = rows.filter(end_time__gt=timezone.now() - timedelta(days=1))
        updated = unplaced = 0
        for tip in rows.only("id", "lat", "lon", "region").iterator(chunk_size=1000):
            county, municipality, area = areas.place_for(tip.lat, tip.lon, tip.region)
            if county is None:
                unplaced += 1
                continue
            Opportunity.objects.filter(pk=tip.pk).update(
                county_code=county, municipality_code=municipality, area_codes=area,
            )
            updated += 1
        self.stdout.write(f"uppdaterade {updated} tips, {unplaced} gick inte att placera i ett län")
