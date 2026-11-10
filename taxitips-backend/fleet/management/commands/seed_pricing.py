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

Prislistan 2026-11 (399 kr per plats, samma pris oavsett antal) skapas och görs
förvald i ETT idempotent steg -- att byta förvald lista sker i samma transaktion,
så det finns aldrig noll eller två förvalda:

    manage.py seed_pricing --id 2026-11-v1 --label "Prislista 2026-11" \
        --base 399 --volume 399 --terms-version 2026-11 --disable-intro \
        --default --dry-run          # visar bara vad som skulle ändras

Ta bort `--dry-run` för att köra. `--base`/`--volume` är hela kronor; de
exakta `--*-ore`-flaggorna finns kvar. Länsavgiften (`extra_county_price_ore`)
ärvs från den nuvarande förvalda listan när en ny skapas, bara för att befintliga
rader med extra län ska kunna prissättas. Den gamla listan rörs inte annat än
att den slutar vara förvald.
"""

from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from fleet.models import Order, PriceVersion


class Command(BaseCommand):
    help = "Skapar eller uppdaterar en prisversion (SEK, ören, exklusive moms)."

    def add_arguments(self, parser):
        parser.add_argument("--id", default="2026-09-v1")
        parser.add_argument("--label", default="")
        parser.add_argument("--base-price-ore", type=int)
        parser.add_argument("--volume-price-ore", type=int)
        parser.add_argument("--base", type=int, help="Grundpris i hela kronor (ex moms).")
        parser.add_argument("--volume", type=int, help="Volympris i hela kronor (ex moms).")
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
        parser.add_argument("--make-default", "--default", dest="make_default",
                            action="store_true", help="Gör versionen förvald (den gamla blir det inte).")
        parser.add_argument("--dry-run", action="store_true",
                            help="Visa vad som skulle ändras, utan att skriva något.")
        parser.add_argument("--force", action="store_true",
                            help="Tillåt ändring av en version som redan har beställningar.")

    def handle(self, *args, **options):
        for kr, ore in (("base", "base_price_ore"), ("volume", "volume_price_ore")):
            if options[kr] is not None:
                if options[ore] is not None:
                    raise CommandError(f"Ange antingen --{kr} (kronor) eller --{kr}-price-ore, inte båda.")
                options[ore] = options[kr] * 100
        version_id = options["id"]
        version = PriceVersion.objects.filter(id=version_id).first()

        # En NY lista ärver länsavgiften från den förvalda: extra län säljs inte
        # längre på den, men rader som redan har dem ska fortfarande gå att prissätta.
        inherit = PriceVersion.objects.filter(is_default=True).exclude(id=version_id).first()
        extra_fallback = inherit.extra_county_price_ore if inherit else 19900

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
                options["extra_county_price_ore"], version, "extra_county_price_ore", extra_fallback
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
            defaults["is_default"] = True

        # Historikskyddet gäller bara FAKTISKA ändringar av en använd version: att
        # köra samma kommando igen (idempotent) ändrar inget och ska inte nekas.
        if version is not None:
            used_by = Order.objects.filter(price_version_id=version_id).count()
            changed = [
                key for key, value in defaults.items()
                if key != "is_default" and getattr(version, key) != value
            ]
            if used_by and changed and not options["force"]:
                raise CommandError(
                    f"{version_id} används av {used_by} beställningar och skulle ändras "
                    f"({', '.join(changed)}). Skapa en NY "
                    "version i stället, eller kör med --force om du verkligen menar "
                    "att ändra historiken."
                )

        demoted = list(
            PriceVersion.objects.filter(is_default=True).exclude(id=version_id)
            .values_list("id", flat=True)
        ) if options["make_default"] else []

        if options["dry_run"]:
            self._print_plan(version_id, version, defaults, demoted)
            return

        # Samma transaktion för att släcka den gamla förvalda och tända den nya:
        # den partiella unika indexen tillåter bara en, och en krasch mitt emellan
        # får inte lämna oss utan förvald lista (nya registreringar skulle fallera).
        with transaction.atomic():
            if demoted:
                PriceVersion.objects.filter(id__in=demoted).update(is_default=False)
            version, created = PriceVersion.objects.update_or_create(
                id=version_id, defaults=defaults
            )
        self.stdout.write(
            f"{'Skapade' if created else 'Uppdaterade'} {version.id}: "
            f"{version.base_price_ore / 100:.0f}/{version.volume_price_ore / 100:.0f} kr per plats/bil, "
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


    def _print_plan(self, version_id, version, defaults, demoted):
        self.stdout.write(self.style.WARNING("DRY RUN -- ingenting skrivs."))
        if version is None:
            self.stdout.write(f"Skulle SKAPA {version_id}:")
            for key, value in defaults.items():
                self.stdout.write(f"  {key} = {value!r}")
        else:
            changes = [
                (key, getattr(version, key), value)
                for key, value in defaults.items()
                if getattr(version, key) != value
            ]
            if not changes:
                self.stdout.write(f"{version_id}: inga fältändringar (redan som önskat).")
            for key, old, new in changes:
                self.stdout.write(f"  {version_id}.{key}: {old!r} -> {new!r}")
        for other in demoted:
            self.stdout.write(f"  {other}.is_default: True -> False (rörs inte i övrigt)")


def _pick(value, version, field, fallback):
    if value is not None:
        return value
    if version is not None:
        return getattr(version, field)
    return fallback
