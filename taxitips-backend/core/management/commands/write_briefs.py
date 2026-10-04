"""
Skriver förarbesked för aktiva tips på medel- och stark nivå (core/briefs.py).

    python manage.py write_briefs
    python manage.py write_briefs --limit 5
"""

from django.core.management.base import BaseCommand

from core import briefs


class Command(BaseCommand):
    help = "Förarbesked: en rad per tips, bara ur tipsets egna fält"

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=None)

    def handle(self, *args, limit=None, **options):
        counts = briefs.run(limit=limit)
        self.stdout.write(self.style.SUCCESS(f"förarbesked: {dict(counts) or 'inget att skriva'}"))
