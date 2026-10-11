"""
Kupongen från adminwebben fungerar i Stripe-kassan (ägarens önskan 2026-10-11).

Kupongen läggs upp som kampanjkod med samma namn: 100 % rabatt i lika många
hela månader som gratisdagarna. Avstängd kupong = avstängd kampanjkod.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from unittest import mock

from django.test import Client, override_settings
from django.utils import timezone

from fleet import stripe_sync
from fleet.models import Coupon
from fleet.tests.base import FleetTestCase


class FakeStripe:
    def __init__(self):
        self.coupons = []
        self.promos = []
        self.modified = []
        fake = self

        class CouponAPI:
            @staticmethod
            def create(**kw):
                fake.coupons.append(kw)
                return mock.Mock(id=f"co_{len(fake.coupons)}")

        class PromotionCodeAPI:
            @staticmethod
            def create(**kw):
                row = {"id": f"promo_{len(fake.promos) + 1}", "active": True, **kw}
                fake.promos.append(row)
                return row

            @staticmethod
            def list(code=None, active=None, limit=20):
                rows = [p for p in fake.promos if p["code"] == code
                        and (active is None or p["active"] == active)]
                return {"data": rows}

            @staticmethod
            def modify(promo_id, **kw):
                fake.modified.append((promo_id, kw))
                for p in fake.promos:
                    if p["id"] == promo_id:
                        p.update(kw)
                return {"id": promo_id}

        self.Coupon = CouponAPI
        self.PromotionCode = PromotionCodeAPI


@override_settings(STRIPE_SECRET_KEY="sk_test_x", STRIPE_ALLOW_LIVE="")
class CouponInCheckoutTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.staff = mock.patch(
            "fleet.admin_sales._staff", return_value=mock.Mock(user_id=uuid.uuid4()),
        )
        self.staff.start()
        self.addCleanup(self.staff.stop)
        self.fake = FakeStripe()

    def post(self, path, body):
        with mock.patch("fleet.stripe_sync._client", return_value=self.fake):
            return self.client.post(path, json.dumps(body), content_type="application/json")

    def test_a_new_coupon_becomes_a_promotion_code_with_free_months(self):
        until = (timezone.now() + timedelta(days=40)).date().isoformat()
        response = self.post("/api/admin/coupons/new", {
            "code": "abbe", "days": 30, "vehicleLimit": 3, "maxRedemptions": 5, "validUntil": until,
        })
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["stripe"]["synced"])
        self.assertEqual(len(self.fake.coupons), 1)
        made = self.fake.coupons[0]
        self.assertEqual((made["percent_off"], made["duration"], made["duration_in_months"]), (100, "repeating", 1))
        promo = self.fake.promos[0]
        self.assertEqual((promo["code"], promo["max_redemptions"]), ("ABBE", 5))
        self.assertIn("expires_at", promo)
        coupon = Coupon.objects.get(code="ABBE")
        self.assertEqual(promo["metadata"][stripe_sync.COUPON_META], str(coupon.id))

    def test_ninety_days_are_three_months_and_publishing_twice_does_nothing(self):
        coupon = Coupon.objects.create(code="TRE-MAN", days=90, vehicle_limit=1)
        with mock.patch("fleet.stripe_sync._client", return_value=self.fake):
            stripe_sync.publish_coupon(coupon)
            again = stripe_sync.publish_coupon(coupon)
        self.assertEqual(self.fake.coupons[0]["duration_in_months"], 3)
        self.assertEqual(again["reason"], "exists")
        self.assertEqual(len(self.fake.promos), 1)

    def test_deactivating_closes_the_promotion_code(self):
        self.post("/api/admin/coupons/new", {"code": "SAMIR", "days": 30})
        coupon = Coupon.objects.get(code="SAMIR")
        response = self.post(f"/api/admin/coupons/{coupon.id}/deactivate", {})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["stripe"]["closed"], 1)
        self.assertFalse(self.fake.promos[0]["active"])

    def test_a_stripe_error_keeps_the_coupon_and_says_why(self):
        broken = FakeStripe()
        broken.Coupon.create = staticmethod(mock.Mock(side_effect=RuntimeError("nere")))
        with mock.patch("fleet.stripe_sync._client", return_value=broken):
            response = self.client.post(
                "/api/admin/coupons/new", json.dumps({"code": "NERE", "days": 30}),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(response.json()["stripe"]["synced"])
        self.assertTrue(Coupon.objects.filter(code="NERE").exists())
