"""
Provslut, "Avsluta provet" och "Pausa tipsen".

* Ett prov vars slut passerat stänger åtkomsten och notiserna DIREKT -- även
  innan nattens fleet_tick har stängt raden (klockan avgör, inte cron-jobbet).
* Personalen kan avsluta ett prov nu (POST .../trial/end): skäl krävs,
  idempotent, revisionslogg, ett betalt abonnemang rörs inte.
* Personalen kan pausa tipsen för ett företag eller ett konto som inte betalar,
  och återuppta: eget neutralt skäl (`company_paused`/`account_paused`), inga
  notiser, inte samma sak som en spärr.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from unittest import mock

from django.test import Client
from django.utils import timezone

from billing.models import Device
from fleet import access, accounts, membership, orders, sessions, trials
from fleet.models import AccountBlock, AuditEvent, DeviceApproval, License, Subscription, Trial
from fleet.push_gate import can_receive
from fleet.tests.test_access import MALMO, tip
from fleet.tests.test_admin import jwt
from fleet.tests.test_sales import SalesTestCase


class _TrialCompany(SalesTestCase):
    """Ett provföretag med en förartelefon i tjänst och en notistoken."""

    def setUp(self):
        super().setUp()
        self.company = self.make_company(name="Prov AB", org_number="5566778899", status="inactive")
        self.trial = trials.create_trial(
            company_id=self.company.id, country="SE", org_number="5566778899",
            source=Trial.Source.SELF_SIGNUP, requires_payment_method=False,
        )
        now = timezone.now()
        Trial.objects.filter(id=self.trial.id).update(
            status=Trial.Status.ACTIVE, started_at=now - timedelta(days=2),
            ends_at=now + timedelta(days=5),
        )
        orders.get_or_create_subscription(self.company.id)
        self.vehicle, self.license = self.make_license(self.company, plate="PRV123", county="12")
        License.objects.filter(id=self.license.id).update(status=License.Status.TRIAL, trial=self.trial)
        self.device = self.make_device(self.company, push_token="fcm-token")
        Device.objects.filter(id=self.device.id).update(notify_prefs={"weak": True})
        self.device.refresh_from_db()
        _approval, self.secret = self.approve(self.company, self.license, self.vehicle, self.device)
        sessions.start_session(device_id=self.device.id, license_id=self.license.id)
        self.train = tip(title="Inställt tåg")
        self.phone = Client()

    def driver_get(self, path, **params):
        return self.phone.get(path, params, headers={"x-device-token": self.secret})

    def assert_everything_refused(self, reason):
        from core import notify

        # Flödet, detaljvyn, färjorna och evenemangen bär skälet.
        body = self.driver_get("/api/alerts", **MALMO).json()
        self.assertEqual(body["alerts"], [])
        self.assertEqual(body["reason"], reason)
        detail = self.driver_get(f"/api/opportunities/{self.train.id}")
        self.assertEqual(detail.status_code, 403)
        self.assertEqual(detail.json()["reason"], reason)
        for path in ("/api/ferries", "/api/events"):
            self.assertEqual(self.driver_get(path, **MALMO).json()["reason"], reason, path)
        # Notiserna: urvalet (även svaga) och sändgrinden.
        self.assertNotIn(self.device.id, [d.id for d in notify._devices()])
        self.assertNotIn(self.device.id, [d.id for d in notify._devices(weak_only=True)])
        verdict = can_receive(self.device, notify.snapshot_of(self.train))
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.reason, f"company_{reason}")

    def assert_open(self):
        from core import notify

        self.assertTrue(access.company_window(self.company.id).ok)
        self.assertIn(self.device.id, [d.id for d in notify._devices()])
        self.assertTrue(can_receive(self.device, notify.snapshot_of(self.train)).ok)
        self.assertEqual(
            [a["title"] for a in self.driver_get("/api/alerts", **MALMO).json()["alerts"]],
            ["Inställt tåg"],
        )


class TrialEndedTests(_TrialCompany):
    def test_the_trial_is_open_before_it_ends(self):
        self.assert_open()

    def test_an_expired_trial_closes_before_fleet_tick_has_run(self):
        Trial.objects.filter(id=self.trial.id).update(ends_at=timezone.now() - timedelta(minutes=1))
        # Raden är fortfarande `active`: ingen tick har gått.
        self.assertEqual(Trial.objects.get(id=self.trial.id).status, Trial.Status.ACTIVE)
        window = access.company_window(self.company.id)
        self.assertFalse(window.ok)
        self.assertEqual(window.reason, "trial_ended")
        self.assert_everything_refused("trial_ended")

    def test_an_ended_trial_row_is_refused_the_same_way(self):
        trials.end_trial(self.trial, reason="trial_period_over")
        self.assert_everything_refused("trial_ended")

    def test_billing_pushes_stop_too(self):
        from billing import tasks

        trials.end_trial(self.trial, reason="trial_period_over")
        with mock.patch.object(tasks, "load_service_account", return_value={"project_id": "p"}), \
                mock.patch.object(tasks, "get_access_token", return_value="at"), \
                mock.patch.object(tasks, "send_push") as send:
            result = tasks.send_billing_push(str(self.company.id), "customer.subscription.updated")
        send.assert_not_called()
        self.assertEqual(result["skipped"], "company_trial_ended")

    def test_the_server_text_points_to_the_web_without_a_link(self):
        for reason in ("trial_ended", "company_paused", "account_paused"):
            text = access._window_message(reason)
            self.assertIn("administratör hanterar medlemskapet på webben", text, reason)
            for banned in ("http", "www", ".se", "kr", "betala", "köp", "pris"):
                self.assertNotIn(banned, text.lower(), (reason, banned))
        self.assertTrue(access._window_message("trial_ended").startswith("Provperioden är slut."))
        self.assertTrue(access._window_message("company_paused").startswith("Medlemskapet är pausat."))


class AdminEndTrialTests(_TrialCompany):
    def url(self):
        return f"/api/admin/companies/{self.company.id}/trial/end"

    def test_sales_ends_the_trial_now(self):
        self.assert_open()
        before = timezone.now()
        response = self.post(self.url(), {"reason": "Kunden ville avsluta"}, user=self.sales_id)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["changed"])
        trial = Trial.objects.get(id=self.trial.id)
        self.assertEqual(trial.status, Trial.Status.ENDED)
        self.assertGreaterEqual(trial.ends_at, before)
        self.assertLessEqual(trial.ends_at, timezone.now())
        self.assertEqual(License.objects.get(id=self.license.id).status, License.Status.CANCELED)
        self.assertEqual(access.company_window(self.company.id).reason, "trial_ended")
        # Telefonen tappar sin bil när licensen avslutas; notisvägen är stängd oavsett.
        from core import notify

        self.assertNotIn(self.device.id, [d.id for d in notify._devices()])
        self.assertFalse(can_receive(self.device, notify.snapshot_of(self.train)).ok)
        event = AuditEvent.objects.get(action="trial_ended_by_staff", company_id=self.company.id)
        self.assertEqual(str(event.actor_user_id), self.sales_id)
        self.assertEqual(event.detail["reason"], "Kunden ville avsluta")
        self.assertEqual(event.detail["before"]["status"], "active")

    def test_it_is_idempotent(self):
        self.post(self.url(), {"reason": "Första"}, user=self.sales_id)
        ended_at = Trial.objects.get(id=self.trial.id).ends_at
        again = self.post(self.url(), {"reason": "Andra"}, user=self.admin_id)
        self.assertEqual(again.status_code, 200, again.content)
        self.assertFalse(again.json()["changed"])
        self.assertEqual(Trial.objects.get(id=self.trial.id).ends_at, ended_at)
        self.assertEqual(
            AuditEvent.objects.filter(action="trial_ended_by_staff", company_id=self.company.id).count(), 1,
        )

    def test_a_pending_trial_can_be_ended_too(self):
        Trial.objects.filter(id=self.trial.id).update(status=Trial.Status.PENDING, ends_at=None, started_at=None)
        response = self.post(self.url(), {"reason": "Fel kund"}, user=self.admin_id)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(Trial.objects.get(id=self.trial.id).status, Trial.Status.ENDED)
        self.assertEqual(access.company_window(self.company.id).reason, "trial_ended")

    def test_a_reason_is_required(self):
        response = self.post(self.url(), {"reason": "  "}, user=self.sales_id)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["reason"], "reason_required")
        self.assertEqual(Trial.objects.get(id=self.trial.id).status, Trial.Status.ACTIVE)

    def test_support_and_customers_cannot_end_a_trial(self):
        self.assertEqual(self.post(self.url(), {"reason": "x"}, user=self.support_id).status_code, 403)
        owner = self.make_owner(self.company)
        self.assertEqual(self.post(self.url(), {"reason": "x"}, user=str(owner.user_id)).status_code, 403)
        self.assertEqual(Trial.objects.get(id=self.trial.id).status, Trial.Status.ACTIVE)

    def test_a_company_without_a_trial_is_404(self):
        Trial.objects.filter(id=self.trial.id).delete()
        response = self.post(self.url(), {"reason": "x"}, user=self.sales_id)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["reason"], "no_trial")

    def test_a_trial_with_a_saved_card_is_left_to_the_subscription(self):
        from fleet import commerce

        with mock.patch.object(commerce, "has_active_trial_commit", return_value=True):
            response = self.post(self.url(), {"reason": "x"}, user=self.sales_id)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["reason"], "trial_committed")
        self.assertEqual(Trial.objects.get(id=self.trial.id).status, Trial.Status.ACTIVE)

    def test_a_paid_subscription_is_not_touched(self):
        subscription = self.make_subscription(self.company)
        before = Subscription.objects.get(id=subscription.id)
        response = self.post(self.url(), {"reason": "Betalar redan"}, user=self.sales_id)
        self.assertEqual(response.status_code, 200, response.content)
        after = Subscription.objects.get(id=subscription.id)
        self.assertEqual(
            (after.status, after.current_period_end, after.stripe_subscription_id),
            (before.status, before.current_period_end, before.stripe_subscription_id),
        )
        window = access.company_window(self.company.id)
        self.assertTrue(window.ok)
        self.assertEqual(window.reason, "paid_period")


class CompanyPauseTests(_TrialCompany):
    def pause(self, reason="Fakturan är obetald", user=None):
        return self.post(
            f"/api/admin/companies/{self.company.id}/pause", {"reason": reason}, user=user or self.sales_id,
        )

    def resume(self, user=None):
        return self.post(
            f"/api/admin/companies/{self.company.id}/resume", {"note": "Betalt"}, user=user or self.sales_id,
        )

    def test_pause_stops_tips_and_pushes_and_resume_restores_them(self):
        response = self.pause()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["changed"])
        self.assertEqual(access.company_window(self.company.id).reason, "company_paused")
        self.assert_everything_refused("company_paused")
        # Inte en spärr: ägaren når portalen och kan ordna medlemskapet där.
        self.assertIsNone(accounts.company_block(self.company.id))
        owner = self.make_owner(self.company)
        portal = self.get("/api/fleet/company", user=str(owner.user_id))
        self.assertEqual(portal.status_code, 200, portal.content)
        self.assertEqual(portal.json()["access"]["reason"], "company_paused")

        response = self.resume()
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["changed"])
        self.assert_open()

        actions = list(
            AuditEvent.objects.filter(company_id=self.company.id, action__startswith="company_tips_")
            .order_by("created_at").values_list("action", "actor_user_id")
        )
        self.assertEqual(
            [(a, str(u)) for a, u in actions],
            [("company_tips_paused", self.sales_id), ("company_tips_resumed", self.sales_id)],
        )
        paused = AuditEvent.objects.get(action="company_tips_paused", company_id=self.company.id)
        self.assertEqual(paused.detail["reason"], "Fakturan är obetald")

    def test_pause_wins_over_a_free_grant_and_a_paid_period(self):
        self.make_subscription(self.company)
        self.assertTrue(access.company_window(self.company.id).ok)
        self.pause()
        self.assertEqual(access.company_window(self.company.id).reason, "company_paused")

    def test_pause_and_resume_are_idempotent(self):
        self.pause()
        again = self.pause(reason="Igen")
        self.assertEqual(again.status_code, 200, again.content)
        self.assertFalse(again.json()["changed"])
        self.assertEqual(
            AccountBlock.objects.filter(kind=AccountBlock.Kind.PAUSE, lifted_at__isnull=True).count(), 1,
        )
        self.resume()
        again = self.resume()
        self.assertEqual(again.status_code, 200, again.content)
        self.assertFalse(again.json()["changed"])

    def test_a_reason_is_required(self):
        response = self.pause(reason=" ")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["reason"], "reason_required")
        self.assertTrue(access.company_window(self.company.id).ok)

    def test_roles(self):
        self.assertEqual(self.pause(user=self.support_id).status_code, 403)
        owner = self.make_owner(self.company)
        self.assertEqual(self.pause(user=str(owner.user_id)).status_code, 403)
        self.assertEqual(self.pause(user=self.admin_id).status_code, 200)
        self.assertEqual(self.resume(user=self.support_id).status_code, 403)
        self.assertEqual(self.resume(user=self.admin_id).status_code, 200)

    def test_the_customer_page_shows_the_pause(self):
        self.pause()
        body = self.get(f"/api/admin/companies/{self.company.id}").json()
        self.assertEqual(body["pause"]["reason"], "Fakturan är obetald")
        self.assertIsNone(body["suspension"])
        self.assertEqual(body["access"]["reason"], "company_paused")


class AccountPauseTests(SalesTestCase):
    """En persons plats: kontot får inga tips och inga notiser, men behåller portalen."""

    def setUp(self):
        super().setUp()
        data = self.full_setup(county="12")
        self.company = data["company"]
        self.device, self.license = data["device"], data["license"]
        self.user_id = data["owner"].user_id
        DeviceApproval.objects.filter(device_id=self.device.id).delete()
        Device.objects.filter(id=self.device.id).update(user_id=self.user_id, push_token="fcm")
        membership.assign_to_self(license=self.license, user_id=self.user_id)
        sessions.start_membership_session(
            user_id=self.user_id, license_id=self.license.id, device_id=self.device.id,
        )
        self.device = Device.objects.get(id=self.device.id)
        self.app = Client()

    def feed(self):
        return self.app.get(
            "/api/alerts", MALMO, headers={"authorization": f"Bearer {jwt(str(self.user_id))}"},
        ).json()

    def url(self, verb):
        return f"/api/admin/accounts/{self.user_id}/{verb}"

    def test_pause_and_resume_one_account(self):
        tip(title="Inställt tåg")
        self.assertTrue(can_receive(self.device, {"area_codes": ["12"]}).ok)
        self.assertEqual(len(self.feed()["alerts"]), 1)

        response = self.post(
            self.url("pause"), {"reason": "Platsen är inte betald", "companyId": str(self.company.id)},
        )
        self.assertEqual(response.status_code, 200, response.content)
        verdict = can_receive(self.device, {"area_codes": ["12"]})
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.reason, "account_paused")
        body = self.feed()
        self.assertEqual(body["alerts"], [])
        self.assertEqual(body["reason"], "account_paused")
        # Företaget i övrigt har kvar sin åtkomst.
        self.assertTrue(access.company_window(self.company.id).ok)
        # Kunden kan fortfarande ordna medlemskapet i portalen.
        portal = self.get("/api/fleet/company", user=str(self.user_id))
        self.assertEqual(portal.status_code, 200, portal.content)
        event = AuditEvent.objects.get(action="user_tips_paused")
        self.assertEqual(str(event.company_id), str(self.company.id))

        response = self.post(self.url("resume"), {"companyId": str(self.company.id)})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(can_receive(self.device, {"area_codes": ["12"]}).ok)
        self.assertEqual(len(self.feed()["alerts"]), 1)
        self.assertTrue(AuditEvent.objects.filter(action="user_tips_resumed").exists())

    def test_a_reason_and_a_selling_role_are_required(self):
        self.assertEqual(self.post(self.url("pause"), {"reason": ""}).status_code, 400)
        self.assertEqual(
            self.post(self.url("pause"), {"reason": "x"}, user=self.support_id).status_code, 403,
        )
        self.assertIsNone(accounts.account_pause(self.user_id))

    def test_the_customer_page_shows_a_paused_member(self):
        self.post(self.url("pause"), {"reason": "Platsen är inte betald"})
        body = self.get(f"/api/admin/companies/{self.company.id}").json()
        member = next(m for m in body["members"] if m["userId"] == str(self.user_id))
        self.assertEqual(member["paused"]["reason"], "Platsen är inte betald")
        self.assertIsNone(member["blocked"])

    def test_an_account_block_also_stops_the_membership_path(self):
        AccountBlock.objects.create(
            kind=AccountBlock.Kind.USER, value=str(self.user_id), reason="Bedrägeri",
            created_by=uuid.uuid4(),
        )
        self.assertEqual(self.feed()["reason"], "account_blocked")
        self.assertEqual(can_receive(self.device, {"area_codes": ["12"]}).reason, "account_blocked")
