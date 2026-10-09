"""
Låter Genkit läsa linje och hållplats där reglerna inte räckte (core/places_ai.py).

    python manage.py read_places --dry-run      # vilka texter som skulle läsas
    python manage.py read_places                # en körning, högst AI_PLACES_MAX_PER_RUN texter
    python manage.py read_places --limit 5

Körs av beat ("read-places", varannan minut). Stängs av med TAXITIPS_AI=off
eller TAXITIPS_BEAT_DISABLE=read-places; reglernas svar gäller då ensamma.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from core import places_ai


class Command(BaseCommand):
    help = "Genkit läser linje och hållplats ur fritexten där reglerna inte räckte."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limit", type=int, default=None)

    def handle(self, *args, dry_run=False, limit=None, **options):
        now = timezone.now()
        if dry_run:
            picked = places_ai.pick(now, limit)
            for key, o in picked:
                self.stdout.write(
                    f"  {key[:8]}  {o.level:6} {o.confidence:6} linje={o.line or '-':12} "
                    f"plats={o.station or '-':20} {(o.title or '')[:48]}"
                )
            self.stdout.write(f"\n{len(picked)} texter skulle läsas (inget anropades)")
            return
        stats = places_ai.run(now, limit, stdout=self.stdout)
        tail = f" -- stannade: {stats['skipped']}" if stats["skipped"] else ""
        self.stdout.write(self.style.SUCCESS(
            f"läste {stats['texts']} texter ({stats['tips']} tips), misslyckades {stats['failed']}{tail}"
        ))
