"""
Ett komplett testbolag i produktion: abonnemang, bil, licens, län och en
parkopplingskod att skriva in i appen.

Skapar INGEN Stripe-kund och ingen debitering. Abonnemanget sätts direkt till
aktivt med en period, vilket är precis vad ett testkonto ska vara: en riktig
rättighetskedja utan pengar i andra änden.

Idempotent -- körs den igen återanvänds bolaget och bilen, och bara en ny
parkopplingskod skapas. Den gamla koden återkallas då, så att det bara finns
en giltig i taget.

    manage.py seed_test_company --name "Testbolaget AB" \
        --base-county 14 --extra-counties 12,13 --plate TEST01
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from billing.models import Company
from core import areas
from fleet import licensing, orders, orgnr, pairing
from fleet.models import (
    CompanyProfile,
    License,
    LicenseCounty,
    Subscription,
    SubscriptionStatus,
    VerificationStatus,
)


class Command(BaseCommand):
    help = "Skapar eller uppdaterar ett testbolag med licens, län och parkopplingskod."

    def add_arguments(self, parser):
        parser.add_argument("--name", default="Testbolaget AB")
        parser.add_argument("--org", default="5566778899")
        parser.add_argument("--plate", default="TEST01")
        parser.add_argument("--base-county", default="14")
        parser.add_argument("--extra-counties", default="12,13")
        parser.add_argument("--days", type=int, default=30)
        parser.add_argument("--email", default="test@taxitips.se")

    @transaction.atomic
    def handle(self, *args, **options):
        now = timezone.now()
        name = options["name"]
        base = options["base_county"]
        extras = [c.strip() for c in options["extra_counties"].split(",") if c.strip()]

        for code in [base, *extras]:
            licensing.assert_county_available(code)

        company = Company.objects.filter(name=name).first()
        if company is None:
            company = Company.objects.create(
                id=uuid.uuid4(), name=name, email=options["email"],
                org_number=orgnr.normalize(options["org"]),
                join_code=uuid.uuid4().hex[:6].upper(), seats=1,
                status="active", subscription_status="active", created_at=now,
            )
        else:
            Company.objects.filter(id=company.id).update(
                status="active", subscription_status="active"
            )

        CompanyProfile.objects.update_or_create(
            company_id=company.id,
            defaults={
                "country": "SE",
                "org_number": orgnr.normalize(options["org"]),
                "legal_name": name,
                "contact_email": options["email"],
                # Testbolag, inte en verifierad avtalspart. Statusen ska inte
                # ljuga om att någon kontrollerat uppgifterna.
                "verification_status": VerificationStatus.UNVERIFIED,
                # Ingen övergångsåtkomst: testkontot ska gå genom den RIKTIGA
                # kedjan (licens -> godkänd telefon -> aktiv session), annars
                # provar vi inte det vi tror att vi provar.
                "legacy_access_until": None,
                "legacy_counties": [],
            },
        )

        subscription = orders.get_or_create_subscription(company.id)
        Subscription.objects.filter(id=subscription.id).update(
            status=SubscriptionStatus.ACTIVE,
            current_period_start=now,
            current_period_end=now + timedelta(days=options["days"]),
            had_successful_payment=True,
            cancel_at_period_end=False,
            canceled_at=None,
            access_until=None,
            grace_until=None,
            grace_origin=None,
            renewal_stopped_at=None,
        )

        vehicle = licensing.create_vehicle(
            company_id=company.id, plate=options["plate"], label="Testbil"
        )
        license = (
            License.objects.filter(company_id=company.id)
            .exclude(status=License.Status.CANCELED)
            .first()
        )
        if license is None:
            license = licensing.create_license(
                company_id=company.id, vehicle=vehicle, base_county=base, now=now
            )
        else:
            License.objects.filter(id=license.id).update(
                status=License.Status.ACTIVE, base_county=base, ends_at=None,
                canceled_at=None,
            )
            LicenseCounty.objects.filter(
                license=license, kind=LicenseCounty.Kind.BASE
            ).exclude(active_to__lte=now).update(active_to=now)
            LicenseCounty.objects.create(
                license=license, county_code=base,
                kind=LicenseCounty.Kind.BASE, active_from=now,
            )
            license.refresh_from_db()

        for code in extras:
            licensing.activate_extra_county(license=license, county_code=code, now=now)

        issued = pairing.issue_code(
            license=license, vehicle=vehicle, created_by=None,
            label="Testtelefon", now=now,
        )

        counties = ", ".join(
            f"{c} {areas.COUNTY_NAMES[c]}" for c in (base, *extras)
        )
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"ANSLUTNINGSKOD: {issued.code}"))
        self.stdout.write(f"giltig till   : {issued.expires_at:%H:%M:%S} UTC")
        self.stdout.write(f"bolag         : {company.name}")
        self.stdout.write(f"bolagskod     : {company.join_code}")
        self.stdout.write(f"bil           : {vehicle.plate}")
        self.stdout.write(f"lan           : {counties}")
        self.stdout.write(f"betalperiod   : till {now + timedelta(days=options['days']):%Y-%m-%d}")
        self.stdout.write("")
