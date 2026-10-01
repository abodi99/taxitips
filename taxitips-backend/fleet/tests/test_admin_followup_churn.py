"""Uppföljning: churn, uppsägning och friska betalande kunder."""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from unittest import mock

from django.test import Client
from django.utils import timezone

from fleet import orders
from fleet.models import SalesFollowUp, StaffRole, Subscription, SubscriptionStatus
from fleet.tests.base import FleetTestCase


class FollowUpChurnTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.staff_user = uuid.uuid4()
        StaffRole.objects.create(user_id=self.staff_user, role=StaffRole.Role.SALES)

    def as_staff(self):
        return mock.patch("fleet.admin_followup._staff", return_value=mock.Mock(user_id=self.staff_user))

    def test_healthy_paying_customer_is_not_in_followups(self):
        company = self.make_company(name="Betalar AB", org_number="5566001122")
        self.make_subscription(company)
        with self.as_staff():
            body = self.client.get("/api/admin/followups").json()
        ids = [r["companyId"] for r in body["followUps"]]
        self.assertNotIn(str(company.id), ids)

    def test_pending_cancel_shows_with_stated_reason(self):
        company = self.make_company(name="Lämnar AB", org_number="5566002233")
        sub = self.make_subscription(company)
        now = timezone.now()
        Subscription.objects.filter(id=sub.id).update(
            cancel_at_period_end=True,
            canceled_at=now,
            access_until=now + timedelta(days=12),
        )
        orders.cancel_subscription(
            company.id, actor_user_id=self.staff_user, reason="För dyrt just nu",
        )
        with self.as_staff():
            body = self.client.get("/api/admin/followups").json()
        row = next(r for r in body["followUps"] if r["companyId"] == str(company.id))
        self.assertEqual(row["segment"], "pending_cancel")
        self.assertEqual(row["statedCancelReason"], "För dyrt just nu")

    def test_churned_customer_and_churn_reason_saved(self):
        company = self.make_company(name="Churn AB", org_number="5566003344")
        sub = self.make_subscription(company)
        now = timezone.now()
        Subscription.objects.filter(id=sub.id).update(
            status=SubscriptionStatus.CANCELED,
            had_successful_payment=True,
            canceled_at=now - timedelta(days=3),
            access_until=now - timedelta(days=1),
            stripe_subscription_id="sub_test",
        )
        with self.as_staff():
            listed = self.client.get("/api/admin/followups").json()
        row = next(r for r in listed["followUps"] if r["companyId"] == str(company.id))
        self.assertEqual(row["segment"], "churn")

        with self.as_staff():
            response = self.client.post(
                f"/api/admin/followups/{company.id}",
                json.dumps({
                    "outcome": "not_interested",
                    "churnReason": "price",
                    "note": "Byter till konkurrent",
                    "contacted": True,
                }),
                content_type="application/json",
            )
        self.assertEqual(response.status_code, 200, response.content)
        follow = SalesFollowUp.objects.get(company_id=company.id)
        self.assertEqual((follow.churn_reason, follow.outcome), ("price", "not_interested"))

    def test_past_due_is_prioritized_segment(self):
        company = self.make_company(name="Obetald AB", org_number="5566004455")
        sub = self.make_subscription(company)
        Subscription.objects.filter(id=sub.id).update(status=SubscriptionStatus.PAST_DUE)
        with self.as_staff():
            body = self.client.get("/api/admin/followups").json()
        row = next(r for r in body["followUps"] if r["companyId"] == str(company.id))
        self.assertEqual(row["segment"], "past_due")
        self.assertEqual(row["stage"], "payment_failed")
