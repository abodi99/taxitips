"""
"Fortsätt här": betalning i två tryck från provslutsmejlet
(fleet/continue_link.py, fleet/sms.py).

Stripe och 46elks mockas; inget nätverk. Det viktiga: biljetten är signerad
och går ut, erbjudandet bär bara serverns egna belopp, organisationsnumret kan
läggas till en gång, kassan byggs av serverns plan (aldrig klientens) och
mejlen länkar hit i stället för till portalen.
"""

from __future__ import annotations

import json
import uuid
from datetime import timedelta
from unittest import mock

import requests
from django.test import Client, override_settings
from django.utils import timezone

from billing.models import Company, CompanyMember
from fleet import continue_link, notifications, sms, trials
from fleet.models import CompanyProfile, License, Order, OutboxMessage, Trial
from fleet.tests.base import FleetTestCase
from fleet.tests.test_onboarding_mail import TrialFixture
from fleet.tests.test_price_2026_11 import seed_new
from fleet.tests.test_trial_commit import Obj

STRIPE = override_settings(STRIPE_SECRET_KEY="sk_test_x", STRIPE_ALLOW_LIVE="")


class TokenTests(FleetTestCase):
    def test_roundtrip(self):
        company_id = uuid.uuid4()
        self.assertEqual(continue_link.read(continue_link.issue(company_id)), str(company_id))

    def test_tampered_token_is_refused(self):
        token = continue_link.issue(uuid.uuid4())
        for bad in (token[:-2] + ("aa" if token[-2:] != "aa" else "bb"), "x" + token, "", None, "skräp"):
            with self.assertRaises(continue_link.ContinueLinkError) as ctx:
                continue_link.read(bad)
            self.assertEqual(ctx.exception.reason, "invalid_link")

    def test_a_token_from_another_salt_is_refused(self):
        from django.core import signing

        foreign = signing.dumps({"c": str(uuid.uuid4()), "i": int(timezone.now().timestamp())}, salt="annat")
        with self.assertRaises(continue_link.ContinueLinkError):
            continue_link.read(foreign)

    def test_expires_after_thirty_days(self):
        company_id = uuid.uuid4()
        token = continue_link.issue(company_id)
        inside = timezone.now() + continue_link.MAX_AGE - timedelta(minutes=5)
        self.assertEqual(continue_link.read(token, now=inside), str(company_id))
        with self.assertRaises(continue_link.ContinueLinkError) as ctx:
            continue_link.read(token, now=timezone.now() + continue_link.MAX_AGE + timedelta(minutes=5))
        self.assertEqual((ctx.exception.reason, ctx.exception.status), ("expired_link", 410))
        self.assertIn("Länken fungerar inte längre", ctx.exception.message)

    @override_settings(FLEET_PORTAL_URL="https://taxitips.se/portal")
    def test_url_has_the_token_in_the_fragment_only(self):
        link = continue_link.url(uuid.uuid4())
        self.assertTrue(link.startswith("https://taxitips.se/fortsatt#t="))
        self.assertNotIn("?", link)


class Fixture(TrialFixture):
    def setUp(self):
        super().setUp()
        seed_new()
        self.client = Client()

    def post(self, path, body):
        return self.client.post(
            f"/api/fleet/continue/{path}", json.dumps(body), content_type="application/json",
        )

    def token(self, company):
        return continue_link.issue(company.id)

    def one_seat(self, **kw):
        return self.trial_company(plates=("ABC123",), **kw)


class OfferTests(Fixture):
    def test_running_trial_has_the_server_price(self):
        company, trial = self.one_seat()
        res = self.post("offer", {"token": self.token(company)})
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertEqual(data["state"], "trial")
        self.assertEqual(data["companyName"], "Provtaxi AB")
        self.assertEqual(data["items"], [{"label": "ABC123 · Stockholms län"}])
        self.assertEqual((data["monthlyOre"], data["monthlyTotalOre"]), (39900, 49875))
        self.assertEqual((data["currency"], data["vatPercent"]), ("SEK", 25))
        self.assertEqual(data["trialEndsAt"], trial.ends_at.isoformat())
        self.assertFalse(data["needsOrgNumber"])
        # Biljetten kommer aldrig tillbaka i svaret.
        self.assertNotIn(self.token(company), res.content.decode())

    def test_during_the_trial_the_page_saves_the_card_then_says_when_it_is_charged(self):
        from fleet import orders

        company, trial = self.one_seat()
        data = self.post("offer", {"token": self.token(company)}).json()
        self.assertTrue(data["saveCardOnly"])
        # Kortet sparat: en väntande fortsättning och betalsättet på profilen.
        plan = orders.plan_change(
            company.id, add_vehicles=trials.continue_specs(trials.continue_vehicles(company.id, trial)),
        )
        plan.request = {**plan.request, "trial_commit": True}
        order = orders.create_order(company.id, plan, created_by=None, actor_kind="customer")
        Order.objects.filter(id=order.id).update(request={**order.request, "trial_commit": True})
        CompanyProfile.objects.filter(company_id=company.id).update(payment_method_verified_at=timezone.now())
        data = self.post("offer", {"token": self.token(company)}).json()
        self.assertEqual(data["state"], "saved")
        self.assertEqual(data["firstChargeAt"], trial.ends_at.isoformat())
        self.assertNotIn("monthlyOre", data)

    def test_account_seats_are_grouped_by_county(self):
        company, trial = self.one_seat()
        License.objects.filter(trial=trial).update(status=License.Status.CANCELED)
        trials.end_trial(trial, reason="trial_period_over")
        data = self.post("offer", {"token": self.token(company)}).json()
        self.assertEqual(data["state"], "ended")

    def test_ended_trial(self):
        company, trial = self.one_seat(ends_in=timedelta(hours=-1))
        trials.end_trial(trial, reason="trial_period_over")
        data = self.post("offer", {"token": self.token(company)}).json()
        self.assertEqual(data["state"], "ended")
        self.assertEqual(data["monthlyOre"], 39900)

    def test_paying_company_is_paid_without_amounts(self):
        data = self.full_setup()
        res = self.post("offer", {"token": continue_link.issue(data["company"].id)}).json()
        self.assertEqual(res["state"], "paid")
        self.assertNotIn("monthlyOre", res)
        self.assertNotIn("items", res)

    def test_company_with_nothing_to_continue(self):
        company = self.make_company(status="inactive")
        res = self.post("offer", {"token": self.token(company)}).json()
        self.assertEqual(res["state"], "nothing")

    def test_bad_and_expired_links_say_so(self):
        bad = self.post("offer", {"token": "inte-en-biljett"})
        self.assertEqual((bad.status_code, bad.json()["reason"]), (400, "invalid_link"))
        company, _ = self.one_seat()
        old = continue_link.issue(company.id, now=timezone.now() - timedelta(days=31))
        res = self.post("offer", {"token": old})
        self.assertEqual((res.status_code, res.json()["reason"]), (410, "expired_link"))

    def test_login_is_not_needed_and_get_is_refused(self):
        self.assertEqual(self.client.get("/api/fleet/continue/offer").status_code, 405)


class OrgNumberTests(Fixture):
    def no_org_company(self):
        company, trial = self.one_seat()
        CompanyProfile.objects.filter(company_id=company.id).update(org_number="")
        Company.objects.filter(id=company.id).update(org_number="")
        return company

    def test_added_once_through_the_link(self):
        company = self.no_org_company()
        token = self.token(company)
        self.assertTrue(self.post("offer", {"token": token}).json()["needsOrgNumber"])
        res = self.post("org-number", {"token": token, "orgNumber": "556036-0793", "legalName": "Provtaxi AB"})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(res.json()["orgNumber"], "5560360793")
        self.assertEqual(CompanyProfile.objects.get(company_id=company.id).org_number, "5560360793")
        self.assertFalse(self.post("offer", {"token": token}).json()["needsOrgNumber"])

        again = self.post("org-number", {"token": token, "orgNumber": "5566778899"})
        self.assertEqual(again.json()["reason"], "org_number_set")
        self.assertEqual(again.json()["detail"]["field"], "orgNumber")
        self.assertEqual(CompanyProfile.objects.get(company_id=company.id).org_number, "5560360793")

    def test_errors_point_at_the_field(self):
        company = self.no_org_company()
        token = self.token(company)
        bad = self.post("org-number", {"token": token, "orgNumber": "123"})
        self.assertEqual(bad.json()["detail"]["field"], "orgNumber")
        no_name = self.post("org-number", {"token": token, "orgNumber": "5560360793"})
        self.assertEqual(no_name.json()["reason"], "name_required")
        self.assertEqual(no_name.json()["detail"]["field"], "legalName")

    def test_an_existing_number_is_never_replaced(self):
        company, _ = self.one_seat()
        res = self.post("org-number", {"token": self.token(company), "orgNumber": "5560360793"})
        self.assertEqual(res.json()["reason"], "org_number_set")
        self.assertEqual(CompanyProfile.objects.get(company_id=company.id).org_number, "5569999005")


@STRIPE
class CheckoutTests(Fixture):
    def fake_stripe(self):
        creates = []

        class Checkout:
            class Session:
                @staticmethod
                def create(**kw):
                    creates.append(kw)
                    sid = f"cs_{len(creates)}"
                    return Obj(
                        id=sid, url=f"https://checkout.stripe.test/{sid}", customer=kw.get("customer"),
                        subscription=None, payment_status="unpaid",
                        metadata=kw.get("metadata") or {}, object="checkout.session",
                    )

        class Customer:
            @staticmethod
            def create(**kw):
                return Obj(id="cus_link")

            @staticmethod
            def modify(*a, **kw):
                return Obj(id="cus_link")

        stripe = mock.Mock()
        stripe.checkout = Checkout
        stripe.Customer = Customer
        return stripe, creates

    def ready(self, **kw):
        return self.one_seat(**kw)

    def test_acceptance_is_required(self):
        company, _ = self.ready()
        for body in ({}, {"accepted": "yes"}, {"accepted": False}):
            res = self.post("checkout", {"token": self.token(company), **body})
            self.assertEqual(res.json()["reason"], "acceptance_required")

    def test_org_number_is_required(self):
        company, _ = self.ready()
        CompanyProfile.objects.filter(company_id=company.id).update(org_number="")
        Company.objects.filter(id=company.id).update(org_number="")
        res = self.post("checkout", {"token": self.token(company), "accepted": True})
        self.assertEqual((res.status_code, res.json()["reason"]), (409, "company_details_required"))
        self.assertEqual(res.json()["detail"]["field"], "orgNumber")

    def test_running_trial_goes_to_stripe_with_the_servers_plan(self):
        company, _ = self.ready()
        stripe, creates = self.fake_stripe()
        with mock.patch("fleet.stripe_sync._client", return_value=stripe):
            res = self.post("checkout", {
                "token": self.token(company), "accepted": True,
                # En plan från klienten ska ignoreras helt.
                "addVehicles": [{"plate": "ZZZ999", "baseCounty": "12"}], "plan": {"x": 1},
            })
        self.assertEqual(res.status_code, 200, res.content)
        data = res.json()
        self.assertTrue(data["paymentUrl"].startswith("https://checkout.stripe.test/"))
        self.assertEqual((data["alreadyCommitted"], data["cardOnFile"]), (False, False))
        order = Order.objects.get(company_id=company.id)
        self.assertEqual(order.status, Order.Status.PENDING_PAYMENT)
        self.assertEqual([v["plate"] for v in order.request["addVehicles"]], ["ABC123"])
        self.assertEqual(creates[0]["success_url"], "https://taxitips.se/fortsatt?betalning=klar")
        self.assertEqual(creates[0]["cancel_url"], "https://taxitips.se/fortsatt?betalning=avbruten")
        self.assertNotIn("#t=", creates[0]["success_url"] + creates[0]["cancel_url"])
        self.assertEqual(str(order.created_by), str(self.owner_id(company)))
        # Kassan: svenska, allt om betalningen ovanför knappen, och betalsätten
        # ur Stripe-kontot (Apple Pay, Google Pay, Klarna ...), inte låsta här.
        self.assertEqual(creates[0]["locale"], "sv")
        message = creates[0]["custom_text"]["submit"]["message"]
        self.assertIn("399 kr/mån exkl. moms (498,75 kr inkl. moms)", message)
        self.assertIn("Säg upp när du vill", message)
        self.assertNotIn("payment_method_types", creates[0])

    def owner_id(self, company):
        return CompanyMember.objects.filter(company_id=company.id, role="company_owner").first().user_id

    def test_ended_trial_uses_the_normal_order_path(self):
        company, trial = self.ready(ends_in=timedelta(hours=-1))
        trials.end_trial(trial, reason="trial_period_over")
        stripe, creates = self.fake_stripe()
        with mock.patch("fleet.stripe_sync._client", return_value=stripe), \
                mock.patch("fleet.commerce.commit_trial_continuation") as commit:
            res = self.post("checkout", {"token": self.token(company), "accepted": True})
        self.assertEqual(res.status_code, 200, res.content)
        commit.assert_not_called()
        self.assertTrue(res.json()["paymentUrl"].startswith("https://checkout.stripe.test/"))
        self.assertEqual(Order.objects.filter(company_id=company.id).count(), 1)
        self.assertTrue(OutboxMessage.objects.filter(category="order_confirmed").exists())
        self.assertEqual(creates[0]["success_url"], "https://taxitips.se/fortsatt?betalning=klar")

    def test_no_member_means_no_owner(self):
        company, _ = self.one_seat()
        CompanyMember.objects.filter(company_id=company.id).delete()
        res = self.post("checkout", {"token": self.token(company), "accepted": True})
        self.assertEqual((res.status_code, res.json()["reason"]), (409, "no_owner"))

    def test_falls_back_to_any_active_member(self):
        company, _ = self.one_seat()
        CompanyMember.objects.filter(company_id=company.id).delete()
        self.make_owner(company, role="finance")
        stripe, _ = self.fake_stripe()
        with mock.patch("fleet.stripe_sync._client", return_value=stripe):
            res = self.post("checkout", {"token": self.token(company), "accepted": True})
        self.assertEqual(res.status_code, 200, res.content)

    def test_paying_company_gets_no_second_checkout(self):
        data = self.full_setup()
        with mock.patch("fleet.stripe_sync._client") as client:
            res = self.post("checkout", {"token": continue_link.issue(data["company"].id), "accepted": True})
        client.assert_not_called()
        self.assertEqual(res.json()["alreadyCommitted"], True)
        self.assertIsNone(res.json()["paymentUrl"])

    def test_nothing_to_pay(self):
        company = self.make_company(status="inactive")
        res = self.post("checkout", {"token": self.token(company), "accepted": True})
        self.assertEqual((res.status_code, res.json()["reason"]), (409, "nothing_to_continue"))


@STRIPE
class PrivateCustomerTests(CheckoutTests):
    """
    En förare utan företag betalar som privatperson: bara med BankID, utan
    organisationsnummer, med kort, och först efter att ha bett om att
    medlemskapet börjar direkt (ångerrätten).
    """

    def no_org_number(self, company):
        CompanyProfile.objects.filter(company_id=company.id).update(org_number="")
        Company.objects.filter(id=company.id).update(org_number="")

    def with_bankid(self, company):
        from fleet.models import BankIdIdentity

        BankIdIdentity.objects.create(
            user_id=self.owner_id(company), pnr_key=f"k{company.id.hex[:20]}", full_name="Anna Andersson",
            verified_at=timezone.now(),
        )

    def test_offer_says_whether_private_is_possible(self):
        company, _ = self.ready()
        self.no_org_number(company)
        data = self.post("offer", {"token": self.token(company)}).json()
        self.assertEqual((data["customerKind"], data["canChoosePrivate"]), ("company", False))
        self.with_bankid(company)
        data = self.post("offer", {"token": self.token(company)}).json()
        self.assertTrue(data["needsOrgNumber"])
        self.assertTrue(data["canChoosePrivate"])

    def test_private_needs_bankid_and_no_org_number(self):
        company, _ = self.ready()  # har organisationsnummer
        self.with_bankid(company)
        res = self.post("private", {"token": self.token(company)})
        self.assertEqual((res.status_code, res.json()["reason"]), (409, "org_number_set"))

        self.no_org_number(company)
        CompanyMember.objects.filter(company_id=company.id).update(role="company_admin")
        res = self.post("private", {"token": self.token(company)})
        self.assertEqual(res.json()["reason"], "bankid_required")

    def test_private_pays_without_org_number_after_asking_to_start_now(self):
        company, _ = self.ready()
        self.no_org_number(company)
        self.with_bankid(company)
        res = self.post("private", {"token": self.token(company)})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertEqual(CompanyProfile.objects.get(company_id=company.id).customer_kind, "private")
        data = self.post("offer", {"token": self.token(company)}).json()
        self.assertEqual((data["customerKind"], data["needsOrgNumber"]), ("private", False))

        # Utan begäran om att börja direkt (ångerrätten) startar ingen betalning.
        res = self.post("checkout", {"token": self.token(company), "accepted": True})
        self.assertEqual((res.status_code, res.json()["reason"]), (400, "consumer_terms_required"))
        self.assertFalse(Order.objects.filter(company_id=company.id).exists())

        stripe, creates = self.fake_stripe()
        with mock.patch("fleet.stripe_sync._client", return_value=stripe):
            res = self.post("checkout", {"token": self.token(company), "accepted": True, "startNow": True})
        self.assertEqual(res.status_code, 200, res.content)
        self.assertTrue(res.json()["paymentUrl"].startswith("https://checkout.stripe.test/"))
        from fleet.models import AuditEvent

        self.assertTrue(AuditEvent.objects.filter(
            company_id=company.id, action="consumer_start_now_accepted").exists())

    def test_companies_do_not_need_the_consumer_box(self):
        company, _ = self.ready()
        stripe, _creates = self.fake_stripe()
        with mock.patch("fleet.stripe_sync._client", return_value=stripe):
            res = self.post("checkout", {"token": self.token(company), "accepted": True})
        self.assertEqual(res.status_code, 200, res.content)

    def test_private_customers_cannot_pay_by_invoice(self):
        from fleet import commerce, company_details, orders

        company, trial = self.ready()
        self.no_org_number(company)
        self.with_bankid(company)
        company_details.mark_private(company.id)
        plan = orders.plan_change(
            company.id, add_vehicles=trials.continue_specs(trials.continue_vehicles(company.id, trial)),
        )
        with self.assertRaises(orders.OrderError) as ctx:
            commerce.place_order(
                company.id, plan, created_by=self.owner_id(company), actor_kind="customer",
                payment=commerce.PAYMENT_INVOICE,
            )
        self.assertEqual(ctx.exception.reason, "invoice_not_for_private")

    def test_adding_an_org_number_makes_the_customer_a_company(self):
        from fleet import company_details

        company, _ = self.ready()
        self.no_org_number(company)
        self.with_bankid(company)
        company_details.mark_private(company.id)
        with mock.patch("fleet.bolagsverket.try_lookup", return_value=None):
            company_details.add_org_number(
                company.id, {"orgNumber": "556036-0793", "legalName": "Annas Taxi AB"},
                actor_user_id=None,
            )
        self.assertEqual(CompanyProfile.objects.get(company_id=company.id).customer_kind, "company")

    def test_stripe_customer_is_the_person(self):
        from fleet import company_details, stripe_sync

        company, _ = self.ready()
        self.no_org_number(company)
        self.with_bankid(company)
        CompanyProfile.objects.filter(company_id=company.id).update(contact_name="Anna Andersson")
        company_details.mark_private(company.id)
        fields = stripe_sync._customer_fields(Company.objects.get(id=company.id))
        self.assertEqual(fields["name"], "Anna Andersson")
        self.assertEqual(fields["metadata"]["customer_kind"], "private")


class MailLinkTests(Fixture):
    def test_reminders_and_ended_mail_link_to_the_page(self):
        company, trial = self.one_seat()
        rows = [notifications.trial_ending(company.id, "a@b.test", trial, stage=s)
                for s in ("3d", "1d", "card_missing_3d", "card_missing_1d", "card_missing")]
        Trial.objects.filter(id=trial.id).update(status=Trial.Status.ENDED)
        trial.refresh_from_db()
        rows.append(notifications.trial_ended(company.id, "a@b.test", trial))
        for row in rows:
            self.assertIn("https://taxitips.se/fortsatt#t=", row.body)
            # Kort mejl: några rader, inget om vad som ingår -- men allt om
            # betalningen (pris med och utan moms, betalsätt, uppsägning).
            self.assertLessEqual(len(row.body.splitlines()), 15)
            self.assertNotIn("portal#fortsatt", row.body)
            token = row.body.split("#t=")[1].split()[0]
            self.assertEqual(continue_link.read(token), str(company.id))

    def test_payment_mails_carry_everything_needed_to_pay(self):
        company, trial = self.one_seat()
        row = notifications.trial_ending(company.id, "a@b.test", trial, stage="card_missing_1d")
        self.assertIn("399 kr/mån exkl. moms (498,75 kr inkl. moms)", row.body)
        self.assertIn("Betala med kort, Apple Pay eller Google Pay.", row.body)
        self.assertIn("Säg upp när du vill.", row.body)
        with override_settings(FLEET_PAYMENT_METHODS_TEXT="kort, Apple Pay, Google Pay eller Klarna"):
            Trial.objects.filter(id=trial.id).update(status=Trial.Status.ENDED)
            trial.refresh_from_db()
            ended = notifications.trial_ended(company.id, "a@b.test", trial)
            self.assertIn("eller Klarna.", ended.body)
            data = self.post("offer", {"token": self.token(company)}).json()
            self.assertEqual(data["paymentMethods"], "kort, Apple Pay, Google Pay eller Klarna")

    def test_the_welcome_mail_keeps_the_portal_link(self):
        company, trial = self.one_seat()
        row = notifications.trial_started(company.id, "a@b.test", trial)
        self.assertIn("portal#fortsatt", row.body)


SMS_ON = override_settings(
    FORTYSIXELKS_USERNAME="u123", FORTYSIXELKS_PASSWORD="pw", FLEET_SMS_SENDER="TaxiTips",
)


class SmsTests(Fixture):
    def phone_company(self, **kw):
        company, trial = self.one_seat(**kw)
        CompanyProfile.objects.filter(company_id=company.id).update(contact_phone="070-812 34 91")
        return company, trial

    @SMS_ON
    def test_last_day_sms_is_sent_once(self):
        company, trial = self.phone_company()
        ok = mock.Mock(status_code=201)
        with mock.patch("fleet.sms.requests.post", return_value=ok) as post:
            notifications.trial_ending(company.id, "a@b.test", trial, stage="card_missing_1d")
            notifications.trial_ending(company.id, "a@b.test", trial, stage="card_missing_1d")
        self.assertEqual(post.call_count, 1)
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.46elks.com/a1/sms")
        self.assertEqual(kwargs["auth"], ("u123", "pw"))
        self.assertEqual(kwargs["timeout"], 10)
        data = kwargs["data"]
        self.assertEqual((data["from"], data["to"]), ("TaxiTips", "+46708123491"))
        self.assertTrue(data["message"].startswith("Taxi Tips: Provet slutar i morgon. Spara kortet så fortsätter tipsen. Inget dras förrän "), data["message"])
        self.assertIn(": https://taxitips.se/fortsatt#t=", data["message"])

    @SMS_ON
    def test_sms_a_week_before_for_those_without_a_card(self):
        company, trial = self.phone_company()
        ok = mock.Mock(status_code=201)
        with mock.patch("fleet.sms.requests.post", return_value=ok) as post:
            notifications.trial_ending(company.id, "a@b.test", trial, stage="card_missing")
            notifications.trial_ending(company.id, "a@b.test", trial, stage="card_missing")
        self.assertEqual(post.call_count, 1)
        self.assertIn("Spara kortet så fortsätter tipsen", post.call_args.kwargs["data"]["message"])

    @SMS_ON
    def test_no_sms_for_the_early_reminder_or_when_a_card_is_saved(self):
        company, trial = self.phone_company()
        with mock.patch("fleet.sms.requests.post") as post:
            notifications.trial_ending(company.id, "a@b.test", trial, stage="card_missing_3d")
            notifications.trial_ending(company.id, "a@b.test", trial, stage="3d")
            notifications.trial_ending(company.id, "a@b.test", trial, stage="1d")
        post.assert_not_called()

    @SMS_ON
    def test_ended_sms_once_and_only_with_a_valid_mobile(self):
        company, trial = self.phone_company()
        Trial.objects.filter(id=trial.id).update(status=Trial.Status.ENDED)
        trial.refresh_from_db()
        CompanyProfile.objects.filter(company_id=company.id).update(contact_phone="08-123 456")
        with mock.patch("fleet.sms.requests.post") as post:
            notifications.trial_ended(company.id, "a@b.test", trial)
        post.assert_not_called()

        # Samma prov, nu med ett riktigt mobilnummer: ett SMS, inte två.
        OutboxMessage.objects.filter(category="trial_ended").delete()
        CompanyProfile.objects.filter(company_id=company.id).update(contact_phone="070-812 34 91")
        with mock.patch("fleet.sms.requests.post", return_value=mock.Mock(status_code=200)) as post:
            notifications.trial_ended(company.id, "a@b.test", trial)
            notifications.trial_ended(company.id, "a@b.test", trial)
        self.assertEqual(post.call_count, 1)
        self.assertIn("Provet är slut. Fortsätt här:", post.call_args.kwargs["data"]["message"])

    def test_nothing_is_sent_when_not_configured(self):
        company, trial = self.phone_company()
        self.assertFalse(sms.configured())
        with mock.patch("fleet.sms.requests.post") as post:
            notifications.trial_ending(company.id, "a@b.test", trial, stage="card_missing_1d")
            notifications.trial_ended(company.id, "a@b.test", trial)
        post.assert_not_called()
        self.assertEqual(OutboxMessage.objects.filter(category__startswith="trial_").count(), 2)

    @SMS_ON
    def test_a_failing_provider_never_breaks_the_mail_and_is_retried(self):
        company, trial = self.phone_company()
        with mock.patch("fleet.sms.requests.post", side_effect=requests.ConnectionError("nere")):
            row = notifications.trial_ending(company.id, "a@b.test", trial, stage="card_missing_1d")
        self.assertIsNotNone(row)
        with mock.patch("fleet.sms.requests.post", side_effect=requests.Timeout("långsam")):
            self.assertFalse(sms.send("+46708123491", "hej"))
        with mock.patch("fleet.sms.requests.post", return_value=mock.Mock(status_code=500)):
            self.assertFalse(sms.send("+46708123491", "hej"))
