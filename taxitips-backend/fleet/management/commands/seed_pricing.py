"""
Skapar eller uppdaterar en prisversion.

Befintliga avtal pekar på SIN version och påverkas aldrig av att en ny läggs
till -- det är hela poängen med versioneringen. Att ändra en version som redan
har beställningar knutna till sig ändrar däremot historiken, och kommandot
vägrar göra det utan `--force`.

Introduktionskampanjen slås på här och ingen annanstans:

    manage.py seed_pricing --enable-intro --launch-date 2026-10-01

Utan ett uttryckligt lanseringsdatum förblir den avstängd. Ett gissat datum
hade börjat ge rabatt till fel företag, och det syns först på fakturan (§6).
"""

from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from fleet.models import Order, PriceVersion


class Command(BaseCommand):
    help = "Skapar eller uppdaterar en prisversion (SEK, ören, exklusive moms)."

    def add_arguments(self, parser):
        parser.add_argument("--id", default="2026-09-v1")
        parser.add_argument("--label", default="")
        parser.add_argument("--base-price-ore", type=int)
        parser.add_argument("--volume-price-ore", type=int)
        parser.add_argument("--volume-threshold", type=int)
        parser.add_argument("--extra-county-price-ore", type=int)
        parser.add_argument("--intro-price-ore", type=int)
        parser.add_argument("--intro-months", type=int)
        parser.add_argument("--vat-rate-bp", type=int, help="2500 = 25,00 %%")
        parser.add_argument("--terms-version", default=None)
        parser.add_argument("--enable-intro", action="store_true")
        parser.add_argument("--disable-intro", action="store_true")
        parser.add_argument("--launch-date", help="ÅÅÅÅ-MM-DD. Krävs för introduktionen.")
        parser.add_argument("--intro-window-days", type=int)
        parser.add_argument("--make-default", action="store_true")
        parser.add_argument("--force", action="store_true",
                            help="Tillåt ändring av en version som redan har beställningar.")

    def handle(self, *args, **options):
        version_id = options["id"]
        version = PriceVersion.objects.filter(id=version_id).first()

        if version is not None:
            used_by = Order.objects.filter(price_version_id=version_id).count()
            if used_by and not options["force"]:
                raise CommandError(
                    f"{version_id} används av {used_by} beställningar. Skapa en NY "
                    "version i stället, eller kör med --force om du verkligen menar "
                    "att ändra historiken."
                )

        defaults = {
            "label": options["label"] or (version.label if version else version_id),
            "currency": "SEK",
            "vat_rate_bp": _pick(options["vat_rate_bp"], version, "vat_rate_bp", 2500),
            "base_price_ore": _pick(options["base_price_ore"], version, "base_price_ore", 79900),
            "volume_price_ore": _pick(
                options["volume_price_ore"], version, "volume_price_ore", 74900
            ),
            "volume_threshold": _pick(
                options["volume_threshold"], version, "volume_threshold", 10
            ),
            "extra_county_price_ore": _pick(
                options["extra_county_price_ore"], version, "extra_county_price_ore", 19900
            ),
            "intro_price_ore": _pick(options["intro_price_ore"], version, "intro_price_ore", 69900),
            "intro_months": _pick(options["intro_months"], version, "intro_months", 3),
            "intro_signup_window_days": _pick(
                options["intro_window_days"], version, "intro_signup_window_days", 60
            ),
            "terms_version": (
                options["terms_version"]
                if options["terms_version"] is not None
                else (version.terms_version if version else "")
            ),
            "active_from": version.active_from if version else timezone.now(),
        }

        launch = version.launch_date if version else None
        if options["launch_date"]:
            launch = date.fromisoformat(options["launch_date"])
        defaults["launch_date"] = launch

        intro_enabled = version.intro_enabled if version else False
        if options["enable_intro"]:
            if launch is None:
                raise CommandError(
                    "--enable-intro kräver --launch-date. Kampanjen får inte startas "
                    "från ett gissat lanseringsdatum."
                )
            intro_enabled = True
        if options["disable_intro"]:
            intro_enabled = False
        defaults["intro_enabled"] = intro_enabled

        if options["make_default"]:
            PriceVersion.objects.filter(is_default=True).exclude(id=version_id).update(
                is_default=False
            )
            defaults["is_default"] = True

        version, created = PriceVersion.objects.update_or_create(id=version_id, defaults=defaults)
        self.stdout.write(
            f"{'Skapade' if created else 'Uppdaterade'} {version.id}: "
            f"{version.base_price_ore / 100:.0f}/{version.volume_price_ore / 100:.0f} kr per bil, "
            f"extra län {version.extra_county_price_ore / 100:.0f} kr, "
            f"moms {version.vat_rate_bp / 100:.2f} %, "
            f"introduktion {'PÅ' if version.intro_enabled else 'AV'}"
            + (f" från {version.launch_date}" if version.launch_date else "")
        )
        if not version.terms_version:
            self.stdout.write(self.style.WARNING(
                "Villkorsversion saknas. Sätt --terms-version innan riktiga "
                "beställningar läggs -- en order utan villkorsversion går inte "
                "att knyta till ett avtal i efterhand."
            ))


def _pick(value, version, field, fallback):
    if value is not None:
        return value
    if version is not None:
        return getattr(version, field)
    return fallback
