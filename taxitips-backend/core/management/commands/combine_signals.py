"""
Kör kombinationslagret en gång (core/combine.py).

    python manage.py combine_signals

Beat kör det var 60:e sekund. Resultatet ersätter förra körningens rader i
`opportunity_combinations`; förarflödet läser dem, notiserna gör det inte.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand

from core.combine import run


class Command(BaseCommand):
    help = "Hittar signaler från olika källor som gäller samma plats och tid"

    def handle(self, *args, **options):
        counts = run()
        summary = ", ".join(f"{rule} {n}" for rule, n in sorted(counts.items())) or "inga"
        self.stdout.write(f"kombinationer: {summary}")
