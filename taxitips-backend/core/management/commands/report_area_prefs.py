"""
Hur förarnas sparade notisinställningar blir körområden (län). Läser bara.

    python manage.py report_area_prefs

Före länen valde föraren marknader (sl, skane, rail ...). Rapporten visar vad
de sparade valen översätts till, och hur många enheter som saknar körområde
och därmed inte får notiser när notisbeslutet kräver ett område. Inga
enhets-id, tokens eller positioner skrivs ut.
"""

from __future__ import annotations

from collections import Counter

from django.core.management.base import BaseCommand

from billing.models import Device
from core import areas


class Command(BaseCommand):
    help = "Visar hur sparade notisinställningar blir körområden (ändrar ingenting)"

    def handle(self, *args, **options):
        outcomes: Counter = Counter()
        translations: Counter = Counter()
        for prefs in Device.objects.values_list("notify_prefs", flat=True):
            prefs = prefs if isinstance(prefs, dict) else {}
            counties = areas.device_counties(prefs)
            if isinstance(prefs.get("counties"), list) and prefs["counties"]:
                outcomes["har valda län"] += 1
            elif counties:
                outcomes["översätts från sparade marknader"] += 1
                regions = tuple(sorted(str(r) for r in prefs.get("regions") or []))
                translations[(regions, tuple(counties))] += 1
            else:
                outcomes["inget körområde: får inga notiser förrän län väljs"] += 1

        self.stdout.write(f"{sum(outcomes.values())} enheter")
        for label, n in outcomes.most_common():
            self.stdout.write(f"  {n:>5}  {label}")
        if translations:
            self.stdout.write("\nsparade marknader -> län:")
            for (regions, counties), n in translations.most_common():
                names = ", ".join(areas.COUNTY_NAMES[c] for c in counties)
                self.stdout.write(f"  {n:>5}  {', '.join(regions)} -> {names}")
