"""
Migreringsvägen för konton som fanns före licensmodellen.

**Vad kommandot GÖR:**

* Skapar en `CompanyProfile` med normaliserat organisationsnummer.
* Öppnar ett daterat övergångsfönster (`legacy_access_until`) med de län
  bolaget faktiskt bevakade, så att befintliga telefoner fortsätter fungera
  medan kunden parkopplar om dem.
* Skapar en `Subscription` som SPEGLAR bolagets nuvarande läge och Stripe-id:n,
  utan att räkna om ett enda belopp.

**Vad kommandot INTE gör, med flit:**

* Det skapar inga bilar och inga licenser. Vilken telefon som sitter i vilken
  bil vet bara kunden -- `devices` bär en etikett som "Anna" eller "Bil 3",
  inte ett registreringsnummer. Att gissa hade gett fel bil på fel licens och
  fel län, och §"Gissa inte bilkopplingar" säger uttryckligen ifrån.
* Det rör inget pris. En befintlig kund ska inte upptäcka den nya prislistan
  genom en högre faktura. Prisversionen anges med `--price-version` och ska
  peka på en version som speglar det kunden redan betalar; finns ingen sådan,
  skapa den med `seed_pricing` först.
* Det anropar inte Stripe.

**Ordning vid utrullning:**

1. `manage.py migrate_legacy_fleet --dry-run` -- läs vad som skulle hända.
2. `manage.py migrate_legacy_fleet --price-version <id> --days 30`
3. Informera kunderna. De lägger upp bilar och parkopplar telefoner i portalen.
4. `FLEET_ENFORCE_LICENSES=1` när övergångsfönstren löpt ut.

**Återställning:** sätt tillbaka `FLEET_ENFORCE_LICENSES=0`. Kommandot lägger
bara till rader; inget tas bort och inget skrivs över.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from billing.models import Company, Device
from fleet import audit, orgnr
from fleet.models import (
    CompanyProfile,
    License,
    PriceVersion,
    Subscription,
    SubscriptionStatus,
)

_STATUS_MAP = {
    "active": SubscriptionStatus.ACTIVE,
    "trial": SubscriptionStatus.TRIALING,
    "past_due": SubscriptionStatus.PAST_DUE,
    "canceled": SubscriptionStatus.CANCELED,
}


class Command(BaseCommand):
    help = "Öppnar ett övergångsfönster för konton som fanns före licensmodellen."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--days", type=int, default=30,
                            help="Övergångsfönstrets längd i dagar.")
        parser.add_argument("--price-version", default=None,
                            help="Prisversionen som speglar vad kunden redan betalar.")
        parser.add_argument("--company", default=None, help="Bara det här bolags-id:t.")
        parser.add_argument("--close", action="store_true",
                            help="Stäng övergångsfönstren i stället för att öppna dem.")

    def handle(self, *args, **options):
        now = timezone.now()
        companies = Company.objects.all()
        if options["company"]:
            companies = companies.filter(id=options["company"])

        if options["close"]:
            return self._close(companies, now, options["dry_run"])

        price_version = None
        if options["price_version"]:
            price_version = PriceVersion.objects.filter(id=options["price_version"]).first()
            if price_version is None:
                raise CommandError(f"Prisversionen {options['price_version']} finns inte.")
        else:
            price_version = PriceVersion.objects.filter(is_default=True).first()
            if price_version is None:
                raise CommandError("Ingen prisversion. Kör `manage.py seed_pricing` först.")
            self.stdout.write(self.style.WARNING(
                f"Ingen --price-version angavs. Använder den förvalda ({price_version.id}). "
                "Kontrollera att den speglar vad de befintliga kunderna redan betalar -- "
                "annars ändras deras pris vid nästa omräkning."
            ))

        until = now + timedelta(days=options["days"])
        touched = skipped = 0
        for company in companies:
            device_count = Device.objects.filter(company_id=company.id).count()
            has_licenses = License.objects.filter(company_id=company.id).exists()
            if has_licenses:
                skipped += 1
                continue

            counties = sorted({str(a) for a in (self._watched_areas(company) or [])})
            line = (
                f"{company.name} ({company.id}): {device_count} telefoner, "
                f"status {company.status}/{company.subscription_status}, "
                f"län {counties or '—'} -> övergång till {until:%Y-%m-%d}"
            )
            if options["dry_run"]:
                self.stdout.write(line)
                touched += 1
                continue

            with transaction.atomic():
                CompanyProfile.objects.update_or_create(
                    company_id=company.id,
                    defaults={
                        "country": "SE",
                        "org_number": orgnr.normalize(company.org_number, "SE"),
                        "legal_name": company.name,
                        "contact_email": company.email or "",
                        "legacy_access_until": until,
                        "legacy_counties": counties,
                    },
                )
                subscription, created = Subscription.objects.get_or_create(
                    company_id=company.id,
                    defaults={
                        "price_version": price_version,
                        "status": _STATUS_MAP.get(company.status, SubscriptionStatus.NONE),
                        "stripe_customer_id": company.stripe_customer_id or "",
                        "stripe_subscription_id": company.stripe_subscription_id or "",
                        # Ingen period antas. Den fylls av nästa
                        # Stripe-händelse eller av avstämningen -- att gissa
                        # ett förfallodatum hade kunnat låsa ute en betalande
                        # kund en dag för tidigt.
                        "had_successful_payment": bool(company.stripe_subscription_id),
                    },
                )
                audit.record(
                    "legacy_company_migrated", company_id=company.id, actor_kind="system",
                    subject_type="company", subject_id=company.id,
                    detail={
                        "devices": device_count, "counties": counties,
                        "legacy_access_until": until.isoformat(),
                        "subscription_created": created,
                        "price_version": price_version.id,
                    },
                )
            self.stdout.write(line)
            touched += 1

        self.stdout.write(self.style.SUCCESS(
            f"{touched} bolag {'skulle få' if options['dry_run'] else 'fick'} ett "
            f"övergångsfönster. {skipped} hade redan licenser och rördes inte."
        ))
        if not options["dry_run"]:
            self.stdout.write(
                "Nästa steg: informera kunderna, låt dem lägga upp bilar och parkoppla "
                "telefoner, och sätt sedan FLEET_ENFORCE_LICENSES=1."
            )

    def _close(self, companies, now, dry_run):
        open_profiles = CompanyProfile.objects.filter(
            company_id__in=[c.id for c in companies], legacy_access_until__gt=now
        )
        count = open_profiles.count()
        if dry_run:
            for profile in open_profiles:
                self.stdout.write(f"{profile.company_id}: {profile.legacy_access_until} -> nu")
        else:
            open_profiles.update(legacy_access_until=now)
        self.stdout.write(self.style.SUCCESS(
            f"{count} övergångsfönster {'skulle stängas' if dry_run else 'stängdes'}."
        ))

    def _watched_areas(self, company) -> list:
        """
        `companies.watched_areas` är en text[]-kolumn som billing-modellen
        medvetet inte beskriver (se billing/models.py). Läs den med rå SQL i
        stället för att lägga till ett fält som skulle mappa fel.

        Kolumnen finns i produktion men inte i Djangos testdatabas, som bygger
        `companies` ur den omanagerade modellen. Saknas den blir svaret en tom
        lista -- inte ett fel: ett bolag utan bevakade län är ett giltigt
        läge, och kommandot ska gå att köra mot båda.
        """
        from django.db import connection

        if not self._has_watched_areas():
            return []
        with connection.cursor() as cursor:
            cursor.execute(
                "select watched_areas from public.companies where id = %s", [str(company.id)]
            )
            row = cursor.fetchone()
        return list(row[0]) if row and row[0] else []

    _watched_areas_present = None

    def _has_watched_areas(self) -> bool:
        if self._watched_areas_present is None:
            from django.db import connection

            with connection.cursor() as cursor:
                cursor.execute(
                    "select 1 from information_schema.columns "
                    "where table_schema = 'public' and table_name = 'companies' "
                    "and column_name = 'watched_areas'"
                )
                self.__class__._watched_areas_present = cursor.fetchone() is not None
        return bool(self._watched_areas_present)
