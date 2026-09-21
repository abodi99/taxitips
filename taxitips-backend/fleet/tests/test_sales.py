"""
Säljflödet i adminwebben: från samtal till förare på vägen.

Stripe är ersatt av en fake som svarar som Stripes API och sparar varje anrop.
Det finns ingen Stripe-testnyckel i den här miljön, och en fake som bara
svarar "ok" hade inte bevisat något -- den här håller fakturor och abonnemang
i minnet så att testet kan betala en faktura och se webhooken verkställa den.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from unittest import mock

from django.test import Client, override_settings
from django.utils import timezone

from billing.models import Company, CompanyMember
from fleet import access, orders, sessions, webhook_events
from fleet.models import (
    AuditEvent,
    CompanyProfile,
    Coupon,
    CouponRedemption,
    License,
    Order,
    OwnerInvite,
    StaffRole,
    Subscription,
    SubscriptionStatus,
    Trial,
    VehicleSession,
)
from fleet.tests.base import FleetTestCase
from fleet.tests.test_access import tip
from fleet.tests.test_admin import SECRET, jwt

ORG = "556677-8899"  # giltig enligt Luhn, samma som fixturen använder
ORG_2 = "5560360793"


def jwt_with_email(sub: str, email: str) -> str:
    import base64
    import hashlib
    import hmac
    import time

    def seg(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    head = seg({"alg": "HS256", "typ": "JWT"})
    body = seg({"sub": sub, "exp": int(time.time()) + 3600, "aal": "aal1", "email": email})
    sig = hmac.new(SECRET.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"


# ---------------------------------------------------------------------------
# Stripe-fake
# ---------------------------------------------------------------------------


class Obj(dict):
    """Ett Stripe-objekt: både nycklar och attribut, som stripe-biblioteket."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def to_dict(self):
        return dict(self)


class FakeStripe:
    def __init__(self):
        self.calls: list[tuple] = []
        self.invoices: dict[str, Obj] = {}
        self.subscriptions: dict[str, Obj] = {}
        self._n = 0
        fake = self

        def next_id(prefix):
            fake._n += 1
            return f"{prefix}_{fake._n}"

        def new_invoice(customer, subscription=None, **kw):
            invoice = Obj(
                object="invoice", id=next_id("in"), customer=customer, status="draft",
                subscription=subscription, metadata=dict(kw.get("metadata") or {}),
                hosted_invoice_url="", amount_due=0, amount_paid=0,
                collection_method=kw.get("collection_method", "charge_automatically"),
                lines={"data": []},
            )
            fake.invoices[invoice.id] = invoice
            return invoice

        def existing(sub_id):
            """Ett abonnemang som redan fanns hos Stripe innan testet började."""
            return fake.subscriptions.setdefault(sub_id, Obj(
                id=sub_id, status="active", items={"data": [{"id": "si_x"}]}, schedule=None,
                current_period_end=int((timezone.now() + timedelta(days=20)).timestamp()),
                trial_end=None,
            ))

        def finalize(invoice):
            invoice["status"] = "open"
            invoice["hosted_invoice_url"] = f"https://invoice.stripe.test/{invoice.id}"
            return invoice

        class Customer:
            @staticmethod
            def create(**kw):
                fake.calls.append(("Customer.create", kw))
                return Obj(id="cus_fake")

            @staticmethod
            def modify(customer_id, **kw):
                fake.calls.append(("Customer.modify", customer_id, kw))
                return Obj(id=customer_id)

        class Subscription:
            @staticmethod
            def create(**kw):
                fake.calls.append(("Subscription.create", kw))
                sub_id = next_id("sub")
                now = int(timezone.now().timestamp())
                invoice = new_invoice(
                    kw["customer"], subscription=sub_id,
                    collection_method=kw.get("collection_method", "charge_automatically"),
                )
                amount = kw["items"][0]["price_data"]["unit_amount"]
                invoice["amount_due"] = amount
                invoice["lines"] = {"data": [{
                    "type": "subscription", "subscription": sub_id, "amount": amount,
                    "period": {"start": now, "end": now + 30 * 86400},
                }]}
                # Första fakturan: fakturans egna period-fält är samma tidpunkt,
                # precis som hos Stripe.
                invoice["period_start"] = now
                invoice["period_end"] = now
                if kw.get("collection_method") != "send_invoice":
                    finalize(invoice)
                sub = Obj(
                    id=sub_id, status="incomplete", customer=kw["customer"],
                    items={"data": [{"id": "si_" + sub_id}]}, schedule=None,
                    current_period_end=now + 30 * 86400, trial_end=None,
                    latest_invoice=invoice, metadata=kw.get("metadata", {}),
                )
                fake.subscriptions[sub_id] = sub
                return sub

            @staticmethod
            def retrieve(sub_id):
                return existing(sub_id)

            @staticmethod
            def modify(sub_id, **kw):
                fake.calls.append(("Subscription.modify", sub_id, kw))
                sub = existing(sub_id)
                if "trial_end" in kw:
                    sub["trial_end"] = kw["trial_end"]
                    sub["status"] = "trialing"
                if "cancel_at_period_end" in kw:
                    sub["cancel_at_period_end"] = kw["cancel_at_period_end"]
                return sub

            @staticmethod
            def cancel(sub_id):
                fake.calls.append(("Subscription.cancel", sub_id))
                if sub_id in fake.subscriptions:
                    fake.subscriptions[sub_id]["status"] = "canceled"
                return Obj(id=sub_id, status="canceled")

        class Invoice:
            @staticmethod
            def create(**kw):
                fake.calls.append(("Invoice.create", kw))
                return new_invoice(**kw)

            @staticmethod
            def finalize_invoice(invoice_id, **kw):
                fake.calls.append(("Invoice.finalize_invoice", invoice_id))
                return finalize(fake.invoices[invoice_id])

            @staticmethod
            def modify(invoice_id, **kw):
                fake.calls.append(("Invoice.modify", invoice_id, kw))
                fake.invoices[invoice_id]["metadata"].update(kw.get("metadata") or {})
                return fake.invoices[invoice_id]

            @staticmethod
            def send_invoice(invoice_id):
                fake.calls.append(("Invoice.send_invoice", invoice_id))
                return fake.invoices[invoice_id]

            @staticmethod
            def retrieve(invoice_id):
                return fake.invoices[invoice_id]

            @staticmethod
            def void_invoice(invoice_id):
                fake.calls.append(("Invoice.void_invoice", invoice_id))
                fake.invoices[invoice_id]["status"] = "void"
                return fake.invoices[invoice_id]

            @staticmethod
            def delete(invoice_id):
                fake.calls.append(("Invoice.delete", invoice_id))
                return Obj(id=invoice_id, deleted=True)

        class InvoiceItem:
            @staticmethod
            def create(**kw):
                fake.calls.append(("InvoiceItem.create", kw))
                return Obj(id=next_id("ii"))

        self.Customer = Customer
        self.Subscription = Subscription
        self.Invoice = Invoice
        self.InvoiceItem = InvoiceItem

    def names(self) -> list[str]:
        return [c[0] for c in self.calls]

    def pay(self, invoice_id: str) -> Obj:
        invoice = self.invoices[invoice_id]
        invoice["status"] = "paid"
        invoice["amount_paid"] = invoice.get("amount_due", 0)
        return invoice


def stripe_connected(fake: FakeStripe):
    return mock.patch("fleet.stripe_sync._client", return_value=fake)


# ---------------------------------------------------------------------------
# Gemensamt
# ---------------------------------------------------------------------------


@override_settings(SUPABASE_JWT_SECRET=SECRET, STRIPE_SECRET_KEY="")
class SalesTestCase(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.sales_id = str(uuid.uuid4())
        self.admin_id = str(uuid.uuid4())
        self.support_id = str(uuid.uuid4())
        StaffRole.objects.create(user_id=self.sales_id, role=StaffRole.Role.SALES)
        StaffRole.objects.create(user_id=self.admin_id, role=StaffRole.Role.PLATFORM_ADMIN)
        StaffRole.objects.create(user_id=self.support_id, role=StaffRole.Role.SUPPORT)

    def post(self, path, body=None, user=None):
        return self.client.post(
            path, data=json.dumps(body or {}), content_type="application/json",
            headers={"authorization": f"Bearer {jwt(user or self.sales_id)}"},
        )

    def get(self, path, user=None, **params):
        return self.client.get(
            path, params, headers={"authorization": f"Bearer {jwt(user or self.sales_id)}"}
        )

    def new_company(self, org=ORG, **overrides) -> Company:
        body = {
            "name": "Göteborgs Taxi AB", "orgNumber": org,
            "contactName": "Anna Andersson", "contactRole": "VD",
            "contactEmail": "anna@gbgtaxi.test", "contactPhone": "070-123 45 67",
            "billingEmail": "faktura@gbgtaxi.test", "billingReference": "Anna A",
            "billingAddress": {"line1": "Hamngatan 1", "postalCode": "411 06", "city": "Göteborg"},
            "verificationNote": "Ringde växeln på numret i Bolagsverket, kopplades till VD.",
            **overrides,
        }
        response = self.post("/api/admin/companies/new", body)
        self.assertEqual(response.status_code, 200, response.content)
        return Company.objects.get(id=response.json()["companyId"])

    def vehicles(self, *plates, county="14", extras=None):
        return [
            {"plate": p, "baseCounty": county, "extraCounties": list(extras or [])}
            for p in plates
        ]


# ---------------------------------------------------------------------------
# Behörighet
# ---------------------------------------------------------------------------


class SalesPermissionTests(SalesTestCase):
    def test_support_reads_but_cannot_sell(self):
        response = self.post("/api/admin/companies/new", {"name": "X"}, user=self.support_id)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.get("/api/admin/sales/config", user=self.support_id).status_code, 200)

    def test_a_customer_owner_cannot_reach_the_sales_flow(self):
        company = self.make_company(name="Kund AB", org_number=ORG_2)
        owner = self.make_owner(company)
        response = self.post("/api/admin/companies/new", {}, user=str(owner.user_id))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["reason"], "not_staff")

    def test_sales_cannot_give_access_without_payment(self):
        """Kuponger, betald-markering och direktavslut är administratörens."""
        company = self.new_company()
        order = Order.objects.create(
            company_id=company.id, kind=Order.Kind.ADD_LICENSE,
            status=Order.Status.PENDING_PAYMENT,
            price_version=Subscription.objects.get(company_id=company.id).price_version,
        )
        for path, body in (
            ("/api/admin/coupons/new", {"days": 30}),
            (f"/api/admin/orders/{order.id}/mark-paid", {"note": "betald"}),
            (f"/api/admin/companies/{company.id}/cancel", {"immediate": True, "reason": "x"}),
        ):
            with self.subTest(path=path):
                self.assertEqual(self.post(path, body).status_code, 403)

    def test_config_reports_that_stripe_is_not_connected(self):
        body = self.get("/api/admin/sales/config").json()
        self.assertFalse(body["stripe"]["available"])
        self.assertTrue(body["canSell"])
        self.assertFalse(body["canManage"])
        self.assertEqual(body["price"]["baseOre"], 79900)
        self.assertTrue(any(c["code"] == "14" for c in body["counties"]))


# ---------------------------------------------------------------------------
# Företaget
# ---------------------------------------------------------------------------


class CompanyTests(SalesTestCase):
    def test_a_company_is_created_with_a_verified_contact(self):
        company = self.new_company()
        profile = CompanyProfile.objects.get(company_id=company.id)
        self.assertEqual(company.org_number, "5566778899")
        self.assertEqual(company.email, "faktura@gbgtaxi.test")
        self.assertEqual(len(company.join_code), 6)
        self.assertEqual(profile.verification_status, "verified")
        self.assertEqual(profile.billing_address["city"], "Göteborg")
        self.assertEqual(profile.billing_address["postal_code"], "411 06")
        subscription = Subscription.objects.get(company_id=company.id)
        self.assertEqual(subscription.status, SubscriptionStatus.NONE)
        self.assertTrue(AuditEvent.objects.filter(
            action="sales_company_created", company_id=company.id, actor_kind="sales"
        ).exists())

    def test_a_new_company_has_no_access_until_something_is_started(self):
        company = self.new_company()
        self.assertFalse(access.company_window(company.id).ok)

    def test_a_mistyped_org_number_is_refused(self):
        response = self.post("/api/admin/companies/new", {
            "name": "Fel AB", "orgNumber": "556677-8898", "contactName": "A",
            "contactEmail": "a@b.test", "verificationNote": "x",
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["reason"], "invalid_org_number")

    def test_the_same_org_number_cannot_be_added_twice(self):
        first = self.new_company()
        response = self.post("/api/admin/companies/new", {
            "name": "Samma AB", "orgNumber": "5566778899", "contactName": "B",
            "contactEmail": "b@b.test", "verificationNote": "x",
        })
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["detail"]["companyId"], str(first.id))

    def test_the_verification_note_is_required(self):
        response = self.post("/api/admin/companies/new", {
            "name": "Utan AB", "orgNumber": ORG_2, "contactName": "C",
            "contactEmail": "c@c.test", "verificationNote": "  ",
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["reason"], "verification_note_required")

    def test_lookup_shows_an_existing_company_and_trial_eligibility(self):
        self.new_company()
        body = self.get("/api/admin/sales/lookup", orgNumber="556677-8899").json()
        self.assertTrue(body["valid"])
        self.assertEqual(body["existingCompany"]["name"], "Göteborgs Taxi AB")
        self.assertTrue(body["trial"]["eligible"])
        other = self.get("/api/admin/sales/lookup", orgNumber=ORG_2).json()
        self.assertIsNone(other["existingCompany"])

    def test_customer_details_can_be_changed_but_not_the_org_number(self):
        company = self.new_company()
        response = self.post(f"/api/admin/companies/{company.id}/profile", {
            "contactPhone": "070-999", "billingEmail": "ny@gbgtaxi.test",
            "orgNumber": ORG_2, "name": "Göteborgs Taxi & Buss AB",
        })
        self.assertEqual(response.status_code, 200, response.content)
        company.refresh_from_db()
        profile = CompanyProfile.objects.get(company_id=company.id)
        self.assertEqual(profile.contact_phone, "070-999")
        self.assertEqual(company.email, "ny@gbgtaxi.test")
        self.assertEqual(company.name, "Göteborgs Taxi & Buss AB")
        self.assertEqual(company.org_number, "5566778899")


# ---------------------------------------------------------------------------
# Prov
# ---------------------------------------------------------------------------


class SalesTrialTests(SalesTestCase):
    def test_a_trial_driver_gets_tips_after_pairing(self):
        """
        Regressionstest: ett prov gav ingen åtkomst alls, eftersom inget satte
        abonnemanget till `trialing` och `company_window` nekade `none`.
        """
        company = self.new_company()
        response = self.post(f"/api/admin/companies/{company.id}/trial", {
            "vehicles": self.vehicles("GBG001", county="14", extras=["13"]),
        })
        self.assertEqual(response.status_code, 200, response.content)
        license = License.objects.get(company_id=company.id)
        self.assertEqual(license.status, License.Status.TRIAL)

        code = self.post(
            f"/api/admin/companies/{company.id}/pairing-code",
            {"license_id": str(license.id), "label": "Förare Ali"},
        ).json()["code"]
        paired = self.client.post(
            "/api/fleet/pair",
            data=json.dumps({"code": code, "installation_id": "install-ali", "label": "Ali"}),
            content_type="application/json",
        ).json()
        self.assertTrue(paired["ok"], paired)
        trial = Trial.objects.get(company_id=company.id)
        self.assertEqual(trial.status, Trial.Status.ACTIVE)

        sessions.start_session(device_id=paired["deviceId"], license_id=license.id)
        tip(area_codes=["14"], lat=57.7089, lon=11.9746, region="vt", title="Göteborg C")
        body = self.client.get(
            "/api/alerts", {"lat": 57.7089, "lon": 11.9746},
            headers={"x-device-token": paired["deviceToken"]},
        ).json()
        self.assertTrue(body["entitled"], body)
        self.assertEqual(len(body["alerts"]), 1)
        self.assertEqual(access.license_counties(license.id), ("13", "14"))

    def test_the_trial_is_limited_to_three_vehicles(self):
        company = self.new_company()
        response = self.post(f"/api/admin/companies/{company.id}/trial", {
            "vehicles": self.vehicles("A1", "A2", "A3", "A4"),
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["reason"], "trial_vehicle_limit")

    def test_one_trial_per_org_number_also_through_sales(self):
        company = self.new_company()
        self.post(f"/api/admin/companies/{company.id}/trial", {"vehicles": self.vehicles("B1")})
        trial = Trial.objects.get(company_id=company.id)
        Trial.objects.filter(id=trial.id).update(
            status=Trial.Status.ENDED, started_at=timezone.now() - timedelta(days=20)
        )
        response = self.post(
            f"/api/admin/companies/{company.id}/trial", {"vehicles": self.vehicles("B2")}
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["reason"], "trial_used_recently")

    def test_converting_a_trial_drops_counties_that_were_not_ordered(self):
        company = self.new_company()
        self.post(f"/api/admin/companies/{company.id}/trial", {
            "vehicles": self.vehicles("C1", county="14", extras=["13", "12"]),
        })
        license = License.objects.get(company_id=company.id)
        trial = Trial.objects.get(company_id=company.id)
        trials_start = timezone.now()
        Trial.objects.filter(id=trial.id).update(
            status=Trial.Status.ACTIVE, started_at=trials_start,
            ends_at=trials_start + timedelta(days=14),
        )
        plan = orders.plan_change(company.id, add_vehicles=[
            orders.VehicleSpec(plate="C1", base_county="14", extra_counties=["13"]),
        ])
        order = orders.create_order(company.id, plan)
        orders.mark_order_paid(order)
        license.refresh_from_db()
        self.assertEqual(license.status, License.Status.ACTIVE)
        self.assertEqual(access.license_counties(license.id), ("13", "14"))


# ---------------------------------------------------------------------------
# Kuponger
# ---------------------------------------------------------------------------


class CouponTests(SalesTestCase):
    def create_coupon(self, **body):
        response = self.post("/api/admin/coupons/new", {"days": 30, **body}, user=self.admin_id)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()["coupon"]

    def test_an_admin_creates_a_coupon_with_a_readable_code(self):
        coupon = self.create_coupon(code=" sommar 30 ", vehicleLimit=5)
        self.assertEqual(coupon["code"], "SOMMAR30")
        self.assertEqual(coupon["vehicleLimit"], 5)
        generated = self.create_coupon()
        self.assertTrue(generated["code"].startswith("TT-"))

    def test_a_coupon_gives_a_new_company_temporary_access(self):
        self.create_coupon(code="DEMO30", days=30, vehicleLimit=5)
        company = self.new_company()
        response = self.post(f"/api/admin/companies/{company.id}/coupon", {
            "code": "demo30", "vehicles": self.vehicles("D1", "D2", "D3", "D4"),
        })
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["effect"], "temporary_access")
        trial = Trial.objects.get(company_id=company.id)
        self.assertEqual(trial.source, Trial.Source.COUPON)
        self.assertEqual(trial.status, Trial.Status.ACTIVE)
        self.assertEqual(trial.vehicle_limit, 5)
        self.assertAlmostEqual(
            (trial.ends_at - timezone.now()).total_seconds(), 30 * 86400, delta=60
        )
        self.assertEqual(
            License.objects.filter(company_id=company.id, status=License.Status.TRIAL).count(), 4
        )
        window = access.company_window(company.id)
        self.assertTrue(window.ok)
        self.assertEqual(window.reason, "trial")

    def test_a_coupon_is_used_once_per_company(self):
        self.create_coupon(code="EN-GANG")
        company = self.new_company()
        path = f"/api/admin/companies/{company.id}/coupon"
        self.post(path, {"code": "EN-GANG", "vehicles": self.vehicles("E1")})
        response = self.post(path, {"code": "EN-GANG", "vehicles": self.vehicles("E2")})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(CouponRedemption.objects.count(), 1)

    def test_max_redemptions_counts_across_companies(self):
        self.create_coupon(code="TVA-GANGER", maxRedemptions=1)
        first = self.new_company()
        second = self.new_company(org=ORG_2, name="Borås Taxi AB")
        self.assertEqual(self.post(f"/api/admin/companies/{first.id}/coupon",
                                   {"code": "TVA-GANGER", "vehicles": self.vehicles("F1")}).status_code, 200)
        response = self.post(f"/api/admin/companies/{second.id}/coupon",
                             {"code": "TVA-GANGER", "vehicles": self.vehicles("F2")})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["reason"], "coupon_used_up")

    def test_expired_and_deactivated_coupons_are_refused(self):
        company = self.new_company()
        coupon = self.create_coupon(code="GAMMAL")
        Coupon.objects.filter(id=coupon["id"]).update(valid_until=timezone.now() - timedelta(days=1))
        response = self.post(f"/api/admin/companies/{company.id}/coupon",
                             {"code": "GAMMAL", "vehicles": self.vehicles("G1")})
        self.assertEqual(response.json()["reason"], "coupon_expired")

        other = self.create_coupon(code="AVSTANGD")
        self.post(f"/api/admin/coupons/{other['id']}/deactivate", user=self.admin_id)
        response = self.post(f"/api/admin/companies/{company.id}/coupon",
                             {"code": "AVSTANGD", "vehicles": self.vehicles("G1")})
        self.assertEqual(response.json()["reason"], "invalid_coupon")

    def test_a_coupon_extends_a_period_paid_outside_stripe(self):
        self.create_coupon(code="FORLANG", days=10)
        data = self.full_setup()
        before = data["subscription"].current_period_end
        response = self.post(f"/api/admin/companies/{data['company'].id}/coupon", {"code": "FORLANG"})
        self.assertEqual(response.json()["effect"], "period_extended", response.content)
        data["subscription"].refresh_from_db()
        self.assertEqual(data["subscription"].current_period_end, before + timedelta(days=10))

    def test_a_coupon_moves_the_next_stripe_charge(self):
        self.create_coupon(code="GRATIS14", days=14)
        data = self.full_setup()
        Subscription.objects.filter(id=data["subscription"].id).update(
            stripe_customer_id="cus_fake", stripe_subscription_id="sub_live"
        )
        fake = FakeStripe()
        with stripe_connected(fake):
            response = self.post(
                f"/api/admin/companies/{data['company'].id}/coupon", {"code": "GRATIS14"}
            )
        self.assertEqual(response.json()["effect"], "billing_deferred", response.content)
        modify = [c for c in fake.calls if c[0] == "Subscription.modify"][0]
        self.assertEqual(modify[2]["proration_behavior"], "none")
        self.assertIn("trial_end", modify[2])
        # Stripe står nu som `trialing` -- åtkomsten ska hålla ändå.
        webhook_events.handle("customer.subscription.updated", {
            "object": "subscription", "id": "sub_live", "customer": "cus_fake",
            "status": "trialing", "current_period_end": modify[2]["trial_end"],
            "metadata": {"company_id": str(data["company"].id)},
        })
        window = access.company_window(data["company"].id)
        self.assertTrue(window.ok, window)
        self.assertEqual(window.reason, "billing_deferred")

    def test_without_stripe_a_stripe_customer_cannot_get_free_days(self):
        self.create_coupon(code="INGEN")
        data = self.full_setup()
        Subscription.objects.filter(id=data["subscription"].id).update(
            stripe_subscription_id="sub_live"
        )
        response = self.post(f"/api/admin/companies/{data['company'].id}/coupon", {"code": "INGEN"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(CouponRedemption.objects.count(), 0)
        self.assertEqual(Coupon.objects.get(code="INGEN").redemption_count, 0)


# ---------------------------------------------------------------------------
# Beställning och betalning
# ---------------------------------------------------------------------------


class OrderTests(SalesTestCase):
    def order(self, company, *, payment="stripe_card", accepted=True, vehicles=None, user=None):
        return self.post(f"/api/admin/companies/{company.id}/orders", {
            "addVehicles": vehicles or self.vehicles("H1", "H2", county="14", extras=["13"]),
            "accepted": accepted, "payment": payment,
        }, user=user)

    def test_the_quote_uses_the_pricing_engine(self):
        company = self.new_company()
        body = self.post(f"/api/admin/companies/{company.id}/quote", {
            "addVehicles": self.vehicles("Q1", "Q2", county="14", extras=["13"]),
        }).json()
        # Två bilar à 799 kr och två extra län à 199 kr, en hel månad i förskott.
        self.assertEqual(body["now"]["amountOre"], 2 * 79900 + 2 * 19900)
        self.assertEqual(body["now"]["vatOre"], (2 * 79900 + 2 * 19900) // 4)

    def test_the_customer_must_have_accepted(self):
        company = self.new_company()
        response = self.order(company, accepted=False)
        self.assertEqual(response.json()["reason"], "acceptance_required")

    def test_without_stripe_the_order_waits_and_nothing_is_granted(self):
        company = self.new_company()
        body = self.order(company).json()
        self.assertEqual(body["order"]["status"], "pending_payment")
        self.assertEqual(body["payment"]["stripeError"]["reason"], "stripe_unavailable")
        self.assertFalse(License.objects.filter(company_id=company.id).exists())

    def test_the_first_order_creates_the_subscription_and_a_payment_link(self):
        company = self.new_company()
        fake = FakeStripe()
        with stripe_connected(fake):
            body = self.order(company).json()
        self.assertTrue(body["payment"]["requested"], body)
        self.assertTrue(body["payment"]["paymentUrl"].startswith("https://invoice.stripe.test/"))
        create = [c for c in fake.calls if c[0] == "Subscription.create"][0][1]
        self.assertEqual(create["items"][0]["price_data"]["unit_amount"], 2 * 79900 + 2 * 19900)
        self.assertEqual(create["collection_method"], "charge_automatically")
        customer = [c for c in fake.calls if c[0] == "Customer.create"][0][1]
        self.assertEqual(customer["email"], "faktura@gbgtaxi.test")
        self.assertEqual(customer["address"]["city"], "Göteborg")
        subscription = Subscription.objects.get(company_id=company.id)
        self.assertTrue(subscription.stripe_subscription_id.startswith("sub_"))
        # Ingen licens förrän Stripe säger att fakturan är betald.
        self.assertFalse(License.objects.filter(company_id=company.id).exists())

    def test_a_paid_first_invoice_activates_the_package_for_a_full_month(self):
        company = self.new_company()
        fake = FakeStripe()
        with stripe_connected(fake):
            order_id = self.order(company).json()["order"]["id"]
            order = Order.objects.get(id=order_id)
            invoice = fake.pay(order.stripe_invoice_id)
            webhook_events.handle("invoice.paid", invoice.to_dict())
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.APPLIED)
        self.assertEqual(
            License.objects.filter(company_id=company.id, status=License.Status.ACTIVE).count(), 2
        )
        subscription = Subscription.objects.get(company_id=company.id)
        self.assertEqual(subscription.status, SubscriptionStatus.ACTIVE)
        # Perioden kommer från abonnemangsraden, inte från fakturans egna fält
        # (som på första fakturan är samma tidpunkt).
        self.assertGreater(subscription.current_period_end, timezone.now() + timedelta(days=29))
        self.assertTrue(access.company_window(company.id).ok)
        # Månadsbeloppet i Stripe följer det som nu är aktivt.
        self.assertIn("Subscription.modify", fake.names())

    def test_the_payment_can_be_checked_against_stripe_without_a_webhook(self):
        company = self.new_company()
        fake = FakeStripe()
        with stripe_connected(fake):
            order_id = self.order(company).json()["order"]["id"]
            order = Order.objects.get(id=order_id)
            unpaid = self.post(f"/api/admin/orders/{order_id}/refresh").json()
            self.assertEqual(unpaid["orderStatus"], "pending_payment")
            fake.pay(order.stripe_invoice_id)
            paid = self.post(f"/api/admin/orders/{order_id}/refresh").json()
        self.assertEqual(paid["invoiceStatus"], "paid")
        self.assertEqual(paid["orderStatus"], "applied")

    def test_an_invoice_customer_gets_an_emailed_invoice(self):
        company = self.new_company()
        fake = FakeStripe()
        with stripe_connected(fake):
            body = self.order(company, payment="stripe_invoice").json()
        create = [c for c in fake.calls if c[0] == "Subscription.create"][0][1]
        self.assertEqual(create["collection_method"], "send_invoice")
        self.assertEqual(create["days_until_due"], 14)
        self.assertIn("Invoice.send_invoice", fake.names())
        self.assertTrue(body["payment"]["paymentUrl"])

    def test_an_upgrade_is_charged_separately_and_the_monthly_amount_waits_for_payment(self):
        data = self.full_setup()
        Subscription.objects.filter(id=data["subscription"].id).update(
            stripe_customer_id="cus_fake", stripe_subscription_id="sub_live"
        )
        fake = FakeStripe()
        with stripe_connected(fake):
            body = self.order(data["company"], vehicles=self.vehicles("UP1", county="12")).json()
        self.assertEqual(body["order"]["status"], "pending_payment")
        self.assertIn("InvoiceItem.create", fake.names())
        self.assertNotIn("Subscription.create", fake.names())
        self.assertNotIn("Subscription.modify", fake.names())

    def test_marking_paid_outside_stripe_needs_an_admin_and_a_note(self):
        company = self.new_company()
        order_id = self.order(company, payment="later").json()["order"]["id"]
        path = f"/api/admin/orders/{order_id}/mark-paid"
        self.assertEqual(self.post(path, {"note": "Fortnox 1001"}).status_code, 403)
        self.assertEqual(
            self.post(path, {"note": " "}, user=self.admin_id).json()["reason"], "note_required"
        )
        response = self.post(path, {"note": "Fortnox 1001"}, user=self.admin_id)
        self.assertEqual(response.json()["order"]["status"], "applied", response.content)
        subscription = Subscription.objects.get(company_id=company.id)
        self.assertEqual(subscription.status, SubscriptionStatus.ACTIVE)
        self.assertGreater(subscription.current_period_end, timezone.now() + timedelta(days=27))
        self.assertTrue(AuditEvent.objects.filter(
            action="order_marked_paid_manually", company_id=company.id
        ).exists())

    def test_an_order_with_a_stripe_invoice_cannot_be_marked_paid_by_hand(self):
        company = self.new_company()
        fake = FakeStripe()
        with stripe_connected(fake):
            order_id = self.order(company).json()["order"]["id"]
        response = self.post(
            f"/api/admin/orders/{order_id}/mark-paid", {"note": "x"}, user=self.admin_id
        )
        self.assertEqual(response.json()["reason"], "stripe_invoice_open")

    def test_canceling_an_unpaid_first_order_voids_the_invoice_and_the_subscription(self):
        company = self.new_company()
        fake = FakeStripe()
        with stripe_connected(fake):
            order_id = self.order(company).json()["order"]["id"]
            response = self.post(f"/api/admin/orders/{order_id}/cancel", {"reason": "Ångrade sig"})
        self.assertEqual(response.json()["order"]["status"], "canceled", response.content)
        self.assertIn("Invoice.void_invoice", fake.names())
        self.assertIn("Subscription.cancel", fake.names())
        self.assertEqual(Subscription.objects.get(company_id=company.id).stripe_subscription_id, "")

    def test_the_customer_portal_gets_the_same_payment_link(self):
        data = self.full_setup()
        fake = FakeStripe()
        with stripe_connected(fake):
            response = self.client.post(
                "/api/fleet/orders",
                data=json.dumps({
                    "addVehicles": self.vehicles("P1", county="12"), "accepted": True,
                }),
                content_type="application/json",
                headers={"authorization": f"Bearer {jwt(str(data['owner'].user_id))}"},
            )
        body = response.json()
        self.assertEqual(body["status"], "pending_payment", body)
        self.assertTrue(body["paymentUrl"].startswith("https://invoice.stripe.test/"))


# ---------------------------------------------------------------------------
# Uppsägning
# ---------------------------------------------------------------------------


class CancellationTests(SalesTestCase):
    def test_sales_cancels_to_the_period_end_in_stripe_too(self):
        data = self.full_setup()
        Subscription.objects.filter(id=data["subscription"].id).update(stripe_subscription_id="sub_live")
        fake = FakeStripe()
        with stripe_connected(fake):
            body = self.post(
                f"/api/admin/companies/{data['company'].id}/cancel", {"reason": "Säljer bilarna"}
            ).json()
        self.assertTrue(body["stripe"]["synced"], body)
        modify = [c for c in fake.calls if c[0] == "Subscription.modify"][0]
        self.assertTrue(modify[2]["cancel_at_period_end"])
        subscription = Subscription.objects.get(id=data["subscription"].id)
        self.assertTrue(subscription.cancel_at_period_end)
        self.assertTrue(access.company_window(data["company"].id).ok)

    def test_a_cancellation_is_kept_even_when_stripe_cannot_be_reached(self):
        data = self.full_setup()
        Subscription.objects.filter(id=data["subscription"].id).update(stripe_subscription_id="sub_live")
        body = self.post(f"/api/admin/companies/{data['company'].id}/cancel", {}).json()
        self.assertFalse(body["stripe"]["synced"])
        self.assertEqual(body["stripe"]["reason"], "stripe_unavailable")
        self.assertTrue(Subscription.objects.get(id=data["subscription"].id).cancel_at_period_end)
        self.assertTrue(AuditEvent.objects.filter(action="stripe_not_updated").exists())

    def test_a_cancellation_can_be_undone(self):
        data = self.full_setup()
        company_id = data["company"].id
        self.post(f"/api/admin/companies/{company_id}/cancel", {})
        body = self.post(f"/api/admin/companies/{company_id}/undo-cancel").json()
        self.assertTrue(body["ok"], body)
        self.assertFalse(Subscription.objects.get(company_id=company_id).cancel_at_period_end)

    def test_terminating_now_ends_access_licences_and_sessions(self):
        data = self.full_setup()
        sessions.start_session(device_id=data["device"].id, license_id=data["license"].id)
        path = f"/api/admin/companies/{data['company'].id}/cancel"
        self.assertEqual(
            self.post(path, {"immediate": True}, user=self.admin_id).json()["reason"],
            "reason_required",
        )
        body = self.post(path, {"immediate": True, "reason": "Avtalsbrott"}, user=self.admin_id).json()
        self.assertTrue(body["ok"], body)
        self.assertFalse(access.company_window(data["company"].id).ok)
        data["license"].refresh_from_db()
        self.assertEqual(data["license"].status, License.Status.CANCELED)
        self.assertFalse(VehicleSession.objects.filter(ended_at__isnull=True).exists())


# ---------------------------------------------------------------------------
# Kundens administratör
# ---------------------------------------------------------------------------


class OwnerInviteTests(SalesTestCase):
    def claim(self, user_id, email):
        return self.client.post(
            "/api/fleet/claim-invite", data="{}", content_type="application/json",
            headers={"authorization": f"Bearer {jwt_with_email(user_id, email)}"},
        )

    def test_the_invited_address_becomes_the_owner_at_first_login(self):
        company = self.new_company()
        response = self.post(
            f"/api/admin/companies/{company.id}/owner-invite", {"email": "Anna@GbgTaxi.test"}
        )
        self.assertEqual(response.json()["email"], "anna@gbgtaxi.test")
        user_id = str(uuid.uuid4())
        body = self.claim(user_id, "anna@gbgtaxi.test").json()
        self.assertTrue(body["ok"], body)
        member = CompanyMember.objects.get(user_id=user_id)
        self.assertEqual((str(member.company_id), member.role), (str(company.id), "company_owner"))
        self.assertEqual(OwnerInvite.objects.get(company_id=company.id).status, "consumed")
        # Kundportalen fungerar nu för kontot.
        overview = self.client.get(
            "/api/fleet/company", headers={"authorization": f"Bearer {jwt(user_id)}"}
        )
        self.assertEqual(overview.status_code, 200, overview.content)

    def test_another_address_gets_nothing(self):
        company = self.new_company()
        self.post(f"/api/admin/companies/{company.id}/owner-invite", {"email": "anna@gbgtaxi.test"})
        response = self.claim(str(uuid.uuid4()), "mallory@evil.test")
        self.assertEqual(response.status_code, 404)
        self.assertFalse(CompanyMember.objects.filter(company_id=company.id).exists())

    def test_an_invite_is_used_once(self):
        company = self.new_company()
        self.post(f"/api/admin/companies/{company.id}/owner-invite", {"email": "anna@gbgtaxi.test"})
        self.assertEqual(self.claim(str(uuid.uuid4()), "anna@gbgtaxi.test").status_code, 200)
        self.assertEqual(self.claim(str(uuid.uuid4()), "anna@gbgtaxi.test").status_code, 404)

    def test_the_company_detail_shows_the_sales_state_without_secrets(self):
        company = self.new_company()
        self.post(f"/api/admin/companies/{company.id}/owner-invite", {"email": "anna@gbgtaxi.test"})
        self.post(f"/api/admin/companies/{company.id}/trial", {"vehicles": self.vehicles("S1")})
        body = self.get(f"/api/admin/companies/{company.id}").json()
        self.assertEqual(body["profile"]["contactName"], "Anna Andersson")
        self.assertEqual(body["ownerInvites"][0]["email"], "anna@gbgtaxi.test")
        self.assertEqual(body["trial"]["vehicles"], 1)
        text = json.dumps(body)
        self.assertNotIn("code_hash", text)
        self.assertNotIn("token_hash", text)
