"""
Gemensam uppsättning för kundlivscykelns tester.

De omanagerade domäntabellerna (`companies`, `devices`, `company_members`)
skapas explicit, av samma skäl som i core/test_api.py och billing/tests.py:
gränsen mellan Djangos tabeller och Supabases ska kosta en rad att korsa, så
att den märks.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from django.core.cache import cache
from django.db import connection
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from billing.models import Company, CompanyMember, Device
from fleet import licensing, orders, pairing
from fleet.models import (
    CompanyProfile,
    DeviceApproval,
    DeviceCredential,
    License,
    PriceVersion,
    RiskConfig,
    Subscription,
    SubscriptionStatus,
)

SUPABASE_MODELS = (Company, Device, CompanyMember)


def create_supabase_tables():
    with connection.schema_editor() as editor:
        for model in SUPABASE_MODELS:
            editor.create_model(model)


def drop_supabase_tables():
    with connection.schema_editor() as editor:
        for model in reversed(SUPABASE_MODELS):
            editor.delete_model(model)


def price_version() -> PriceVersion:
    """
    Prislistan ur migrationen. `TransactionTestCase` trunkerar tabellerna
    mellan testerna, så den återskapas vid behov med exakt samma värden --
    ett test som råkar köra mot en annan prislista bevisar ingenting.
    """
    existing = PriceVersion.objects.filter(id="2026-09-v1").first()
    if existing is not None:
        return existing
    return PriceVersion.objects.create(
        id="2026-09-v1", label="Grundprislista 2026", currency="SEK",
        vat_rate_bp=2500, base_price_ore=79900, volume_price_ore=74900,
        volume_threshold=10, extra_county_price_ore=19900, intro_price_ore=69900,
        intro_months=3, intro_enabled=False, launch_date=None,
        intro_signup_window_days=60, terms_version="", is_default=True,
        active_from=timezone.now(),
    )


class FleetFixture:
    """Byggstenarna: bolag, ägare, bil, licens, godkänd telefon."""

    def make_company(self, name="Taxi Demo AB", org_number="5566778899", status="active"):
        company = Company.objects.create(
            id=uuid.uuid4(), name=name, email=f"{uuid.uuid4().hex[:8]}@example.test",
            org_number=org_number, join_code=uuid.uuid4().hex[:6].upper(), seats=5,
            status=status, created_at=timezone.now(),
            subscription_status="active" if status == "active" else "inactive",
        )
        CompanyProfile.objects.create(
            company_id=company.id, country="SE", org_number=org_number, legal_name=name
        )
        return company

    def make_owner(self, company, role="company_owner"):
        return CompanyMember.objects.create(
            id=uuid.uuid4(), company_id=company.id, user_id=uuid.uuid4(),
            role=role, status="active", created_at=timezone.now(),
        )

    def make_subscription(self, company, *, days_left=20, status=SubscriptionStatus.ACTIVE):
        now = timezone.now()
        subscription = orders.get_or_create_subscription(company.id, price_version=price_version())
        Subscription.objects.filter(id=subscription.id).update(
            status=status,
            current_period_start=now - timedelta(days=30 - days_left),
            current_period_end=now + timedelta(days=days_left),
            had_successful_payment=True,
        )
        subscription.refresh_from_db()
        return subscription

    def make_license(self, company, *, plate="ABC123", county="12"):
        vehicle = licensing.create_vehicle(company_id=company.id, plate=plate)
        license = licensing.create_license(
            company_id=company.id, vehicle=vehicle, base_county=county
        )
        return vehicle, license

    def make_device(self, company, label="Förare 1", push_token=None):
        return Device.objects.create(
            id=uuid.uuid4(), company_id=company.id, token=f"install-{uuid.uuid4().hex}",
            label=label, kind="driver", notify_prefs={}, created_at=timezone.now(),
            push_token=push_token,
        )

    def approve(self, company, license, vehicle, device, *, label=""):
        """Godkänner en telefon och ger den en hashad hemlighet -- som parkopplingen."""
        now = timezone.now()
        approval = DeviceApproval.objects.create(
            company_id=company.id, device_id=device.id, license=license,
            vehicle=vehicle, label=label or device.label, approved_at=now,
        )
        secret = f"secret-{uuid.uuid4().hex}"
        DeviceCredential.objects.create(
            device_id=device.id, company_id=company.id,
            token_hash=pairing.hash_token(secret), prefix=secret[:8],
            scheme=DeviceCredential.Scheme.HASHED_V1, approval=approval,
        )
        return approval, secret

    def full_setup(self, *, plate="ABC123", county="12", company=None):
        """Bolag med abonnemang, en licens och en godkänd telefon."""
        company = company or self.make_company()
        owner = self.make_owner(company)
        subscription = self.make_subscription(company)
        vehicle, license = self.make_license(company, plate=plate, county=county)
        device = self.make_device(company)
        approval, secret = self.approve(company, license, vehicle, device)
        return {
            "company": company, "owner": owner, "subscription": subscription,
            "vehicle": vehicle, "license": license, "device": device,
            "approval": approval, "secret": secret,
        }


class FleetTestCase(FleetFixture, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        create_supabase_tables()

    @classmethod
    def tearDownClass(cls):
        drop_supabase_tables()
        super().tearDownClass()

    def setUp(self):
        cache.clear()
        price_version()
        RiskConfig.current()


class FleetTransactionTestCase(FleetFixture, TransactionTestCase):
    """
    För det som måste köras med riktiga, samtidiga transaktioner.

    `TestCase` lägger varje test i en transaktion som rullas tillbaka, och då
    kan två trådar inte se varandras skrivningar -- ett samtidighetstest hade
    då bevisat motsatsen till vad det påstår.
    """

    # Migrationen som lägger in prislistan körs bara en gång; tabellerna
    # trunkeras mellan testerna. `price_version()` i setUp återskapar den.
    serialized_rollback = False

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        create_supabase_tables()

    @classmethod
    def tearDownClass(cls):
        drop_supabase_tables()
        super().tearDownClass()

    def setUp(self):
        cache.clear()
        price_version()
        RiskConfig.current()
