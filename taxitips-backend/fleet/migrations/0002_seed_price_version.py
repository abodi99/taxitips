"""
Prisversionen nya beställningar utgår från, plus riskgränsernas startvärden.

Beloppen står i uppdraget och är exklusive moms, i ören:
799 / 749 / 199 / 699 kr per månad.

**Introduktionen är AVSTÄNGD här.** `intro_enabled=False` och
`launch_date=None`: kampanjen får inte startas från ett gissat lanseringsdatum
(§6). Den som ska slå på den sätter båda fälten -- i admin eller med
`manage.py seed_pricing --launch-date YYYY-MM-DD --enable-intro`.

**Momssatsen är 25 %** (2500 punkter). Det är den svenska normalskattesatsen
och den enda siffra här som inte stod i uppdraget. Den ligger som ett fält på
prisversionen just för att den ska gå att ändra utan kodändring, och för att
en framtida prisversion ska kunna bära en annan sats utan att röra befintliga
avtal.

`terms_version` är tom med flit. Den fylls när villkorsdokumentet har en
version -- en påhittad versionssträng i en order är värre än ingen alls.
"""

from django.db import migrations
from django.utils import timezone


def seed(apps, schema_editor):
    PriceVersion = apps.get_model("fleet", "PriceVersion")
    RiskConfig = apps.get_model("fleet", "RiskConfig")

    PriceVersion.objects.update_or_create(
        id="2026-09-v1",
        defaults={
            "label": "Grundprislista 2026",
            "currency": "SEK",
            "vat_rate_bp": 2500,
            "base_price_ore": 79900,
            "volume_price_ore": 74900,
            "volume_threshold": 10,
            "extra_county_price_ore": 19900,
            "intro_price_ore": 69900,
            "intro_months": 3,
            "intro_enabled": False,
            "launch_date": None,
            "intro_signup_window_days": 60,
            "terms_version": "",
            "is_default": True,
            "active_from": timezone.now(),
        },
    )
    RiskConfig.objects.update_or_create(
        id=1,
        defaults={
            "new_pairings_per_vehicle_24h": 3,
            "takeovers_per_hour": 6,
            "vehicle_changes_per_30d": 2,
            "pairing_code_ttl_seconds": 300,
        },
    )


def unseed(apps, schema_editor):
    apps.get_model("fleet", "PriceVersion").objects.filter(id="2026-09-v1").delete()


class Migration(migrations.Migration):
    dependencies = [("fleet", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
