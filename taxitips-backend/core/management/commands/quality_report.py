"""
Nattrapporten om tipsens kvalitet (core/quality_report.py).

    python manage.py quality_report            # gårdagen, om den inte redan finns
    python manage.py quality_report --force    # bygg om gårdagen nu
    python manage.py quality_report --day 2026-10-03 --no-ai
"""

from datetime import date

from django.core.management.base import BaseCommand

from core import quality_report


class Command(BaseCommand):
    help = "Bygger gårdagens kvalitetsrapport: siffror av koden, sammanfattning av AI:n"

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--day", type=date.fromisoformat, default=None)
        parser.add_argument("--no-ai", action="store_true", help="Bara siffrorna, ingen sammanfattning.")

    def handle(self, *args, force=False, day=None, no_ai=False, **options):
        if day:
            report = quality_report.build(day, summarize=not no_ai)
        else:
            report = quality_report.run(force=force)
        if report is None:
            self.stdout.write("ingen ny rapport (redan byggd, eller före klockan fem)")
            return
        self.stdout.write(self.style.SUCCESS(f"kvalitetsrapport {report.day}: {len(report.suggestions)} förslag"))
        if report.summary:
            self.stdout.write(report.summary)
