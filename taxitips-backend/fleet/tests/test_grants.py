"""
Manuellt beviljande: fullt medlemskap utan kostnad (fleet/grants.py).

Testernas tyngdpunkt ligger på det som går sönder tyst:

* att beviljandet faktiskt öppnar åtkomsten (fönster, kategorier, län),
* att det INTE rör pengar -- ingen order, ingen faktura, ingen Stripe-rörelse,
  och platsen räknas bort från nästa fakturas belopp,
* att återkallelsen stänger fönstret och återgår till den vanliga prövningen,
* och att beslutet lämnar spår (aktör, skäl) i revisionsloggen.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import timedelta

from django.test import Client, RequestFactory, override_settings
from django.utils import timezone

from core import areas
from fleet import access, grants, licensing, sessions
from fleet.models import (
    AuditEvent,
    License,
    MembershipGrant,
    MembershipSession,
    Order,
    Subscription,
    SubscriptionStatus,
    Vehicle,
)
from fleet.tests.base import FleetTestCase

SECRET = "grants-test-secret-at-least-32-characters!"


def _jwt(sub, email="") -> str:
    def seg(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    head = seg({"alg": "HS256", "typ": "JWT"})
    claims = {"sub": str(sub), "exp": int(time.time()) + 3600, "aal": "aal1"}
    if email:
        claims["email"] = email
    body = seg(claims)
    sig = hmac.new(SECRET.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class GrantTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        self.data = self.full_setup(county="12")
        self.company = self.data["company"]
        self.actor = uuid.uuid4()

    def grant(self, *, user_id=None, email="", reason="Goda kundrelationer", **kwargs):
        return grants.grant_membership(
            company_id=self.company.id, user_id=user_id, email=email,
            reason=reason, actor_user_id=self.actor, **kwargs,
        )

    # --- beviljandet i sig ------------------------------------------------

    def test_grant_creates_a_seat_for_a_person_without_a_vehicle(self):
        person = uuid.uuid4()
        grant = self.grant(user_id=person)

        self.assertTrue(grant.license_created)
        license = grant.license
        self.assertEqual(license.status, License.Status.ACTIVE)
        self.assertTrue(license.is_assigned_to(person))
        # Platsen är personbaserad: ingen NY bil skapas för beviljandet.
        self.assertEqual(Vehicle.objects.filter(company_id=self.company.id).count(), 1)

    def test_grant_opens_the_company_window_as_free_grant(self):
        self.make_subscription(self.company, days_left=-5, status=SubscriptionStatus.PAST_DUE)
        self.assertFalse(access.company_window(self.company.id).ok)

        self.grant(user_id=uuid.uuid4())
        window = access.company_window(self.company.id)
        self.assertTrue(window.ok)
        self.assertEqual(window.reason, "free_grant")

    def test_grant_gives_all_counties_and_full_features(self):
        from fleet import features

        person = uuid.uuid4()
        grant = self.grant(user_id=person)
        self.assertTrue(grant.all_counties)
        self.assertEqual(
            set(access.license_counties(grant.license_id)),
            {code for code, _name in areas.COUNTIES},
        )
        self.assertTrue(features.for_company(self.company.id).full)

    def test_grant_with_chosen_counties_only(self):
        grant = self.grant(user_id=uuid.uuid4(), all_counties=False, counties=["12", "14"])
        self.assertFalse(grant.all_counties)
        self.assertEqual(access.license_counties(grant.license_id), ("12", "14"))

    def test_grant_never_reuses_an_existing_unassigned_seat(self):
        # En köpt plats som väntar på tilldelning är betald och bär sina köpta
        # län: beviljandet får inte ta den och skriva över länen.
        orphan = licensing.create_membership_license(company_id=self.company.id, base_county="14")
        grant = self.grant(user_id=uuid.uuid4())
        self.assertNotEqual(grant.license_id, orphan.id)
        self.assertTrue(grant.license_created)
        orphan.refresh_from_db()
        self.assertEqual(orphan.base_county, "14")
        self.assertEqual(access.license_counties(orphan.id), ("14",))

    def test_grant_requires_a_reason(self):
        with self.assertRaises(grants.GrantError) as caught:
            self.grant(user_id=uuid.uuid4(), reason="  ")
        self.assertEqual(caught.exception.reason, "reason_required")

    def test_second_open_grant_for_the_same_person_is_refused(self):
        person = uuid.uuid4()
        self.grant(user_id=person)
        with self.assertRaises(grants.GrantError) as caught:
            self.grant(user_id=person)
        self.assertEqual(caught.exception.reason, "grant_exists")
        self.assertEqual(MembershipGrant.objects.count(), 1)

    # --- inga pengar -------------------------------------------------------

    def test_grant_creates_no_order_and_no_invoice(self):
        # Fixturen är ett betalande bolag: beviljandet får inte röra dess
        # betalningsläge, och inga nya pengarsposter får skapas.
        sub = Subscription.objects.filter(company_id=self.company.id).first()
        before = (
            sub.status, sub.current_period_end, sub.had_successful_payment,
            sub.stripe_subscription_id, sub.grace_until, sub.access_until,
        )

        self.grant(user_id=uuid.uuid4())

        self.assertEqual(Order.objects.filter(company_id=self.company.id).count(), 0)
        sub.refresh_from_db()
        after = (
            sub.status, sub.current_period_end, sub.had_successful_payment,
            sub.stripe_subscription_id, sub.grace_until, sub.access_until,
        )
        self.assertEqual(before, after)

    def test_granted_seat_is_not_counted_toward_the_next_invoice(self):
        before_licenses = licensing.billable_license_count(self.company.id)
        before_extras = licensing.extra_county_count(self.company.id)

        grant = self.grant(user_id=uuid.uuid4())

        # Platsen och dess 21 län finns, men räknas inte mot fakturan.
        self.assertEqual(licensing.billable_license_count(self.company.id), before_licenses)
        self.assertEqual(licensing.extra_county_count(self.company.id), before_extras)

        grants.revoke(grant, reason="Prov avslutat", actor_user_id=self.actor)
        # Platsen är avslutad, så räknen är oförändrad även efteråt.
        self.assertEqual(licensing.billable_license_count(self.company.id), before_licenses)

    # --- revisionsloggen ---------------------------------------------------

    def test_grant_and_revoke_leave_an_audit_trail(self):
        person = uuid.uuid4()
        grant = self.grant(user_id=person)
        granted = AuditEvent.objects.filter(
            action="membership_granted", company_id=self.company.id
        ).first()
        self.assertIsNotNone(granted)
        self.assertEqual(str(granted.actor_user_id), str(self.actor))
        self.assertEqual(granted.detail["reason"], "Goda kundrelationer")
        self.assertEqual(granted.detail["license_id"], str(grant.license_id))

        grants.revoke(grant, reason="Kunden sade upp", actor_user_id=self.actor)
        revoked = AuditEvent.objects.filter(
            action="membership_grant_revoked", company_id=self.company.id
        ).first()
        self.assertIsNotNone(revoked)
        self.assertEqual(revoked.detail["reason"], "Kunden sade upp")
        self.assertEqual(str(revoked.actor_user_id), str(self.actor))

    # --- återkallelse ------------------------------------------------------

    def test_revoke_restores_the_normal_window_evaluation(self):
        self.make_subscription(self.company, days_left=-5, status=SubscriptionStatus.PAST_DUE)
        grant = self.grant(user_id=uuid.uuid4())
        self.assertTrue(access.company_window(self.company.id).ok)

        grants.revoke(grant, reason="Tvisten är löst", actor_user_id=self.actor)
        window = access.company_window(self.company.id)
        self.assertFalse(window.ok)
        self.assertEqual(window.reason, "past_due")

    def test_revoke_cancels_the_seat_it_created_and_closes_the_session(self):
        person = uuid.uuid4()
        grant = self.grant(user_id=person)
        license = grant.license
        sessions.start_membership_session(
            user_id=person, license_id=license.id, device_id=uuid.uuid4(),
        )

        grants.revoke(grant, reason="Beviljandet drogs tillbaka", actor_user_id=self.actor)

        license.refresh_from_db()
        self.assertEqual(license.status, License.Status.CANCELED)
        self.assertIsNone(license.assignee_user_id)
        self.assertEqual(
            MembershipSession.objects.filter(license=license, ended_at__isnull=True).count(), 0
        )
        self.assertFalse(access.license_counties(license.id))

    def test_revoke_never_touches_a_paid_seat(self):
        # Företagets riktiga, köpta plats (med bil) finns kvar; beviljandet
        # skapar en EGEN plats, och återkallelsen avslutar bara den.
        paid = self.data["license"]
        grant = self.grant(user_id=uuid.uuid4())
        self.assertNotEqual(grant.license_id, paid.id)

        grants.revoke(grant, reason="Klar", actor_user_id=self.actor)
        paid.refresh_from_db()
        self.assertEqual(paid.status, License.Status.ACTIVE)

    def test_revoke_requires_a_reason_and_is_idempotent(self):
        grant = self.grant(user_id=uuid.uuid4())
        with self.assertRaises(grants.GrantError):
            grants.revoke(grant, reason="", actor_user_id=self.actor)
        grants.revoke(grant, reason="Första", actor_user_id=self.actor)
        again = grants.revoke(grant, reason="Andra", actor_user_id=self.actor)
        self.assertEqual(again.revoke_reason, "Första")

    # --- e-post före konto -------------------------------------------------

    def test_email_grant_is_claimed_when_the_account_logs_in(self):
        grant = self.grant(email="Forare@Taxi.Test")
        self.assertIsNone(grant.user_id)
        self.assertEqual(grant.email, "forare@taxi.test")
        license = grant.license
        self.assertEqual(license.assignee_email, "forare@taxi.test")
        self.assertIsNone(license.assignee_user_id)

        person = uuid.uuid4()
        headers = {"authorization": f"Bearer {_jwt(person, 'forare@taxi.test')}"}
        # Ett anrop med den verifierade token löser in både raden och platsen.
        access.resolve(RequestFactory().get("/api/alerts", headers=headers))

        grant.refresh_from_db()
        self.assertEqual(str(grant.user_id), str(person))
        self.assertEqual(grant.email, "")
        license.refresh_from_db()
        self.assertEqual(str(license.assignee_user_id), str(person))

    # --- åtkomst hela vägen ------------------------------------------------

    def test_granted_account_gets_driver_access_with_all_counties(self):
        person = uuid.uuid4()
        self.grant(user_id=person)
        headers = {"authorization": f"Bearer {_jwt(person)}"}
        r = self.client.post(
            "/api/fleet/membership-session", data=json.dumps({}),
            content_type="application/json", headers=headers,
        )
        self.assertEqual(r.status_code, 200, r.content)

        result = access.resolve(RequestFactory().get("/api/alerts", headers=headers))
        self.assertTrue(result.ok)
        self.assertEqual(result.reason, "membership")
        self.assertEqual(result.period, "free_grant")
        self.assertEqual(set(result.counties), {code for code, _name in areas.COUNTIES})

    def test_expired_grant_closes_the_window_again(self):
        self.make_subscription(self.company, days_left=-5, status=SubscriptionStatus.PAST_DUE)
        grant = self.grant(user_id=uuid.uuid4(), ends_at=timezone.now() + timedelta(days=7))
        self.assertTrue(access.company_window(self.company.id).ok)

        later = timezone.now() + timedelta(days=8)
        window = access.company_window(self.company.id, later)
        self.assertFalse(window.ok)
        self.assertEqual(window.reason, "past_due")
        self.assertFalse(grants._is_active(grant, later))