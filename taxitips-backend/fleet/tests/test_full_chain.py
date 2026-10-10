"""
Kedjetestet: hela kundlivscykeln i den ordning en riktig kund går igenom den,
genom de riktiga vägarna -- HTTP-vyerna, signerade Stripe-webhooks mot
`/billing/stripe/webhook`, utkorgen för mejlen och notiscykeln
(`core.notify.run_push_cycle` med en låtsassändare och `fleet/push_gate.py`).

    registrera i appen -> logga in -> provets notiser -> provet tar slut ->
    fortsätt med provets plats i portalen och betala -> köp bilar och bjud in
    förare -> ge en plats till en ny e-post -> betalningen faller, paus och
    uppsägning

Varje steg har egna, noggrannare tester. Det här finns för att fånga när
stegen var för sig fungerar men inte längre hänger ihop -- det kunden märker
först och en enhetstest sist. Inget nät: Bolagsverket, Supabase Auths
admin-API, Stripes API och FCM är utbytta mot attrapper; allt annat är den
riktiga koden.

**Vad som inte går att pröva här** (och var det prövas i stället):

* Bekräftelsemejlet vid registreringen (`taxitips.se/bekraftad`) och mejlet
  "Glömt lösenord" skickas av Supabase Auth (GoTrue), inte av backenden.
  Länken bestäms av appen (`ApiClient._confirmedPage`, `_passwordPage`) och
  GoTrues tillåtelselista (docs/release-checklist.md §7). Att återställningen
  är implicit flow (ingen PKCE `code_challenge`) är en egenskap hos
  `GoTrueClient(flowType: implicit)` i appen -- det enda backenden ser är
  adminens "Skapa lösenordslänk", som prövas nedan.
* Riktiga Stripe-anrop (kund, abonnemang, faktura) -- `stripe_sync` är utbytt;
  händelserna som Stripe skickar tillbaka är riktiga, signerade payloads.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import timedelta
from io import StringIO
from unittest import mock

from django.core.management import call_command
from django.db import connection
from django.test import Client, override_settings
from django.utils import timezone

from billing import tasks as billing_tasks
from billing.models import Device, ProcessedWebhookEvent
from core import notify
from core.models import PushDelivery, SeverityTier
from core.test_notify import opportunity
from fleet import access, auth_admin, bolagsverket, push_gate
from fleet.models import (
    DriverInvite,
    License,
    Order,
    OutboxMessage,
    StaffRole,
    Subscription,
    SubscriptionStatus,
    Trial,
)
from fleet.tests.base import FleetTestCase
from fleet.tests.test_support import SECRET

REAL_INVITE_LINK = auth_admin.invite_link

WHSEC = "whsec_kedjetest"
CUSTOMER = "cus_kedjetest"
STRIPE_SUB = "sub_kedjetest"
ORG = "5560360793"
OWNER_EMAIL = "agare@kedjetaxi.test"
PORTAL_CONTINUE = "https://taxitips.se/portal#fortsatt"
DRIVER_PAGE = "https://taxitips.se/forare"


def token(sub, email="", *, verified=True) -> str:
    """En Supabase-JWT som efter en bekräftad e-post (HS256, samma hemlighet som vyerna)."""

    def seg(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")

    head = seg({"alg": "HS256", "typ": "JWT"})
    claims = {
        "sub": str(sub), "exp": int(time.time()) + 3600, "aal": "aal1", "role": "authenticated",
        "user_metadata": {"email_verified": verified},
    }
    if email:
        claims["email"] = email
    body = seg(claims)
    sig = hmac.new(SECRET.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{base64.urlsafe_b64encode(sig).decode().rstrip('=')}"


def registry_hit(org_number, **_):
    return bolagsverket.CompanyInfo(
        org_number=org_number, found=True, name="Kedjetaxi AB", legal_form="Aktiebolag",
        legal_form_code="AB", status="active", status_text="Aktivt",
        address={"street": "Storgatan 1", "postalCode": "211 22", "city": "Malmö"},
        sni=[{"code": "49320", "text": "Taxitrafik"}],
    )


@override_settings(
    SUPABASE_JWT_SECRET=SECRET, SUPABASE_SERVICE_ROLE_KEY="test-service-role",
    SUPABASE_URL="https://api.taxitips.se",
    STRIPE_SECRET_KEY="", STRIPE_WEBHOOK_SECRET=WHSEC, FIREBASE_SERVICE_ACCOUNT_JSON="",
    FLEET_PORTAL_URL="https://taxitips.se/portal", FLEET_DRIVER_INVITE_REDIRECT=DRIVER_PAGE,
    FLEET_OUTBOX_SENDER="",
)
class ChainBase(FleetTestCase):
    """Attrapperna för nätet och hjälparna för HTTP, webhooks och notiser."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Webhookens idempotenstabell ägs av Supabase, som companies/devices.
        with connection.schema_editor() as editor:
            editor.create_model(ProcessedWebhookEvent)

    @classmethod
    def tearDownClass(cls):
        with connection.schema_editor() as editor:
            editor.delete_model(ProcessedWebhookEvent)
        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.client = Client()
        self.sent_pushes: list[dict] = []
        self.billing_pushes: list[dict] = []
        self.auth_links: list[dict] = []
        self.event_clock = int(time.time()) - 3600
        self._patch("fleet.bolagsverket.try_lookup", side_effect=registry_hit)
        self._patch("fleet.auth_admin.invite_link", side_effect=self._fake_link)
        # Stripe: vår sida räknar och verkställer, Stripes API är utbytt.
        self._patch("fleet.stripe_sync.available", return_value=True)
        self._patch("fleet.stripe_sync.collect_order", side_effect=self._fake_collect)
        self._patch("fleet.stripe_sync.sync_company_amount", return_value=None)
        # Webhooken köar en Celery-task; här körs den direkt, oavsett
        # CELERY_TASK_ALWAYS_EAGER, så att testet inte beror på miljön.
        self._patch.object(
            billing_tasks.process_stripe_event, "delay",
            side_effect=lambda *a, **k: billing_tasks.process_stripe_event(*a, **k),
        )
        self._patch.object(
            billing_tasks.send_billing_push, "delay",
            side_effect=lambda *a, **k: billing_tasks.send_billing_push(*a, **k),
        )
        self._patch("billing.tasks.load_service_account", return_value={"project_id": "kedja"})
        self._patch("billing.tasks.get_access_token", return_value="fcm-access")
        self._patch("billing.tasks.send_push", side_effect=self._fake_billing_push)

    # --- attrapper ---------------------------------------------------------

    class _Patcher:
        def __init__(self, case):
            self.case = case

        def __call__(self, target, **kwargs):
            patcher = mock.patch(target, **kwargs)
            started = patcher.start()
            self.case.addCleanup(patcher.stop)
            return started

        def object(self, obj, attr, **kwargs):
            patcher = mock.patch.object(obj, attr, **kwargs)
            started = patcher.start()
            self.case.addCleanup(patcher.stop)
            return started

    @property
    def _patch(self):
        return self._Patcher(self)

    def _fake_link(self, email, redirect_to):
        user_id = str(uuid.uuid4())
        self.auth_links.append({"email": email, "redirect_to": redirect_to, "user_id": user_id})
        url = (
            "https://api.taxitips.se/auth/v1/verify?token=t-" + user_id[:8]
            + "&type=invite&redirect_to=" + redirect_to
        )
        return auth_admin.AuthLink(url=url, user_id=user_id, kind="invite")

    def _fake_collect(self, order, *, collection_method="charge_automatically", days_until_due=14):
        """Det `stripe_sync.collect_order` skapar i Stripe: kund, abonnemang, faktura."""
        invoice = f"in_kedja_{uuid.uuid4().hex[:10]}"
        Subscription.objects.filter(company_id=order.company_id).update(
            stripe_customer_id=CUSTOMER, stripe_subscription_id=STRIPE_SUB,
        )
        url = f"https://invoice.stripe.com/i/{invoice}"
        Order.objects.filter(id=order.id).update(stripe_invoice_id=invoice, stripe_payment_url=url)
        return url

    def _fake_billing_push(self, *_args, **kwargs):
        self.billing_pushes.append(kwargs)
        return {"ok": True}

    def push_sender(self, *, token, title, body, data, **_):
        self.sent_pushes.append({"token": token, "title": title, "data": data})
        return {"ok": True}

    # --- HTTP --------------------------------------------------------------

    def call(self, method, path, body=None, *, user=None, email="", device=None, query=None):
        headers = {}
        if user:
            headers["authorization"] = f"Bearer {token(user, email)}"
        if device:
            headers["x-device-token"] = device
        if method == "get":
            return self.client.get(path, query or {}, headers=headers)
        return self.client.post(
            path, data=json.dumps(body or {}), content_type="application/json", headers=headers,
        )

    def ok(self, response, status=200):
        self.assertEqual(response.status_code, status, response.content)
        return response.json()

    def webhook(self, event_type, obj, *, event_id=None):
        """En signerad Stripe-händelse, som Stripe skickar den."""
        self.event_clock += 10
        event = {
            "id": event_id or f"evt_kedja_{uuid.uuid4().hex[:16]}", "object": "event",
            "api_version": "2024-12-18.acacia", "created": self.event_clock,
            "type": event_type, "livemode": False, "data": {"object": obj},
        }
        payload = json.dumps(event, separators=(",", ":"))
        stamp = int(time.time())
        digest = hmac.new(WHSEC.encode(), f"{stamp}.{payload}".encode(), hashlib.sha256).hexdigest()
        response = self.client.post(
            "/billing/stripe/webhook", data=payload, content_type="application/json",
            HTTP_STRIPE_SIGNATURE=f"t={stamp},v1={digest}",
        )
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    # --- notiser -----------------------------------------------------------

    def tip(self, county, *, kind="transit", mode="train", **extra):
        return opportunity(
            kind=kind, mode=mode, severity_tier=SeverityTier.LINE_PAUSED, demand_score=85,
            area_codes=[county], county_code=county, region=None,
            title=f"{kind} i {county}", **extra,
        )

    def push_cycle(self, now=None):
        self.sent_pushes.clear()
        return notify.run_push_cycle(sender=self.push_sender, now=now)

    def pushed(self, device) -> set[str]:
        """Tipsen (id) som nådde telefonen i senaste cykeln."""
        device.refresh_from_db()
        return {
            p["data"]["opportunity_id"] for p in self.sent_pushes if p["token"] == device.push_token
        }

    def outbox(self, category, **filters):
        return list(OutboxMessage.objects.filter(category=category, **filters).order_by("created_at"))


class FullCustomerChainTests(ChainBase):
    def test_the_whole_customer_lifecycle(self):
        owner = str(uuid.uuid4())

        # ------------------------------------------------------------------
        # 1. Registrering i appen
        # ------------------------------------------------------------------
        check = self.ok(self.call("post", "/api/fleet/register/check", {
            "orgNumber": ORG, "contactPhone": "070-812 34 91", "email": OWNER_EMAIL,
        }))
        self.assertTrue(check["registryAvailable"])
        reg = self.ok(self.call("post", "/api/fleet/register", {
            "orgNumber": ORG, "companyName": "", "contactName": "Ali Ägare",
            "contactPhone": "070-812 34 91",
        }, user=owner, email=OWNER_EMAIL), status=201)
        company_id = reg["companyId"]
        # Namnet kom från Bolagsverket, inte från formuläret.
        self.assertEqual(reg["companyName"], "Kedjetaxi AB")
        trial = Trial.objects.get(company_id=company_id)
        self.assertEqual(trial.status, Trial.Status.ACTIVE)
        self.assertEqual(trial.vehicle_limit, 1)
        self.assertAlmostEqual(
            (trial.ends_at - trial.started_at).total_seconds(), timedelta(days=7).total_seconds(), delta=5,
        )
        # Välkomstmejlet med vägen till portalen.
        welcome = self.outbox("trial_started")
        self.assertEqual(len(welcome), 1, "provets välkomstmejl köades inte")
        self.assertEqual(welcome[0].to_address, OWNER_EMAIL)
        self.assertIn(PORTAL_CONTINUE, welcome[0].body)

        # Appens steg efter registreringen: välj län och ta platsen.
        seat = self.ok(self.call(
            "post", "/api/fleet/memberships/trial", {"baseCounty": "12"}, user=owner, email=OWNER_EMAIL,
        ))["membership"]
        self.assertEqual(seat["counties"], ["12"])
        self.assertTrue(seat["trial"])
        overview = self.ok(self.call("get", "/api/fleet/company", user=owner, email=OWNER_EMAIL))
        self.assertEqual(overview["features"]["plan"], "trial")
        self.assertEqual(overview["features"]["categories"], ["transit"])
        self.assertNotIn("betal", overview["features"]["lockedMessage"].lower())

        # ------------------------------------------------------------------
        # 2. Inloggning: JWT-vägen och telefonens enhetsnyckel
        # ------------------------------------------------------------------
        owner_phone = self.ok(self.call("post", "/api/device/session", {
            "installation_id": "install-owner-0001", "platform": "android",
            "push_token": "fcm-owner", "label": "Alis telefon",
        }, user=owner, email=OWNER_EMAIL))
        owner_device = Device.objects.get(id=owner_phone["device_id"])
        self.ok(self.call("post", "/api/fleet/membership-session", {
            "licenseId": seat["licenseId"], "deviceId": str(owner_device.id),
        }, user=owner, email=OWNER_EMAIL))

        feed = self.ok(self.call("get", "/api/alerts", user=owner, email=OWNER_EMAIL))
        self.assertTrue(feed["entitled"], feed)
        self.assertEqual(feed["features"]["plan"], "trial")
        me = self.ok(self.call("get", "/api/fleet/me", device=owner_phone["device_token"]))
        self.assertTrue(me["entitled"], me)
        self.assertEqual(me["counties"], ["12"])
        # Utan JWT och utan nyckel: ingenting.
        self.assertFalse(self.ok(self.call("get", "/api/alerts"))["entitled"])

        # ------------------------------------------------------------------
        # 4. Notiser under provet: länet, inget utanför, bara tåg och buss
        # ------------------------------------------------------------------
        skane = self.tip("12")
        self.tip("01")  # Stockholm: utanför platsens län
        self.tip("12", kind="ferry", mode="ferry")
        self.tip("12", kind="flight", mode="flight")
        self.push_cycle()
        self.assertEqual(self.pushed(owner_device), {str(skane.id)})
        locked = PushDelivery.objects.filter(
            device_id=owner_device.id, status=PushDelivery.Status.SUPPRESSED,
        ).values_list("error", flat=True)
        self.assertTrue(any("trial_category_locked:ferry" in e for e in locked), list(locked))
        self.assertTrue(any("trial_category_locked:flight" in e for e in locked), list(locked))

        # ------------------------------------------------------------------
        # 5. Provet tar slut
        # ------------------------------------------------------------------
        now = timezone.now()
        Trial.objects.filter(id=trial.id).update(ends_at=now + timedelta(days=2, hours=12))
        for _ in range(2):
            call_command("fleet_tick", stdout=StringIO())
        Trial.objects.filter(id=trial.id).update(ends_at=now + timedelta(hours=10))
        for _ in range(2):
            call_command("fleet_tick", stdout=StringIO())
        reminders = self.outbox("trial_ending")
        self.assertEqual(
            sorted(r.payload["stage"] for r in reminders), ["card_missing_1d", "card_missing_3d"],
        )
        for row in reminders:
            self.assertEqual(row.to_address, OWNER_EMAIL)
            self.assertIn(PORTAL_CONTINUE, row.body)
            # Platsen från appen har ingen bil, men mejlet har ändå ett pris
            # (förut: trial_offer None och mejl utan pris).
            self.assertIn("i månaden exkl. moms", row.body)
            self.assertIn("Skåne län", row.body)
            self.assertGreater(row.payload["offer"]["monthly_ore"], 0)
        last_day = next(r for r in reminders if r.payload["stage"] == "card_missing_1d")
        self.assertIn("inom ett dygn", last_day.body)
        self.assertNotEqual(last_day.subject, reminders[0].subject)

        # Klockan, inte cron-jobbet: slut i samma sekund som ends_at passerat.
        Trial.objects.filter(id=trial.id).update(ends_at=timezone.now() - timedelta(minutes=1))
        self.assertEqual(access.company_window(company_id).reason, "trial_ended")
        feed = self.ok(self.call("get", "/api/alerts", user=owner, email=OWNER_EMAIL))
        self.assertFalse(feed["entitled"])
        self.assertEqual(feed["reason"], "trial_ended")
        transit = self.tip("12")
        detail = self.call("get", f"/api/opportunities/{transit.id}", user=owner, email=OWNER_EMAIL)
        self.assertEqual(detail.status_code, 403)
        self.assertFalse(self.ok(self.call("get", "/api/ferries", user=owner, email=OWNER_EMAIL))["entitled"])
        self.assertFalse(self.ok(self.call("get", "/api/events", user=owner, email=OWNER_EMAIL))["entitled"])
        self.assertFalse(self.ok(self.call("get", "/api/fleet/me", device=owner_phone["device_token"]))["entitled"])
        self.push_cycle()
        self.assertEqual(self.sent_pushes, [])
        self.assertFalse(push_gate.can_receive(owner_device, {"kind": "transit", "area_codes": ["12"]}).ok)
        # Inte heller en faktureringsnotis.
        result = billing_tasks.send_billing_push(company_id, "invoice.payment_failed")
        self.assertEqual(result.get("skipped"), "company_trial_ended")
        self.assertEqual(self.billing_pushes, [])

        for _ in range(2):
            call_command("fleet_tick", stdout=StringIO())
        ended = self.outbox("trial_ended")
        self.assertEqual(len(ended), 1)
        self.assertEqual(ended[0].to_address, OWNER_EMAIL)
        self.assertIn(PORTAL_CONTINUE, ended[0].body)
        self.assertIn("i månaden exkl. moms", ended[0].body)

        # ------------------------------------------------------------------
        # 6. Betalning i portalen: beställ, betala, allt öppnas
        # ------------------------------------------------------------------
        # Kortet "Fortsätt med provet" (portal#fortsatt, dit mejlen länkar):
        # provets plats från appen, utan bil, med länet och priset.
        overview = self.ok(self.call("get", "/api/fleet/company", user=owner, email=OWNER_EMAIL))
        self.assertEqual(overview["continueVehicles"], [{
            "kind": "membership", "plate": "", "baseCounty": "12",
            "licenseId": seat["licenseId"], "assigneeEmail": "", "assigned": True,
        }])
        offer = overview["continueOffer"]
        self.assertEqual(offer["monthlyTotalOre"], ended[0].payload["offer"]["monthly_total_ore"])
        # Samma ändring som portalens continueChange() skickar.
        change = {"addVehicles": [{
            "plate": "", "baseCounty": "12", "label": "", "extraCounties": [],
            "continueLicenseId": seat["licenseId"],
        }]}
        quote = self.ok(self.call("post", "/api/fleet/quote", change, user=owner, email=OWNER_EMAIL))
        self.assertGreater(quote["now"]["totalOre"], 0)
        # Kortet, mejlet och offerten visar samma månadsbelopp (fleet/pricing.py).
        self.assertEqual(quote["nextPeriod"]["totalOre"], offer["monthlyTotalOre"])
        placed = self.ok(self.call(
            "post", "/api/fleet/orders", {**change, "accepted": True}, user=owner, email=OWNER_EMAIL,
        ))
        self.assertEqual(placed["status"], Order.Status.PENDING_PAYMENT)
        self.assertTrue(placed["paymentUrl"].startswith("https://invoice.stripe.com/"))
        order = Order.objects.get(id=placed["orderId"])
        # Beställd men obetald: ingenting öppnas av en betallänk.
        self.assertEqual(access.company_window(company_id).reason, "trial_ended")
        confirmed = self.outbox("order_confirmed")
        self.assertEqual(len(confirmed), 1)
        self.assertEqual(confirmed[0].to_address, OWNER_EMAIL, "orderbekräftelsen saknar mottagare")

        period_start = int(time.time())
        period_end = period_start + 30 * 86400
        self.webhook("checkout.session.completed", {
            "id": "cs_kedja_1", "object": "checkout.session", "customer": CUSTOMER,
            "subscription": STRIPE_SUB, "payment_status": "paid", "mode": "subscription",
            "metadata": {"company_id": company_id, "order_id": str(order.id)},
        })
        paid_invoice = {
            "id": order.stripe_invoice_id if order.stripe_invoice_id else "in_x",
            "object": "invoice", "customer": CUSTOMER, "subscription": STRIPE_SUB,
            "status": "paid", "amount_paid": quote["now"]["totalOre"],
            "billing_reason": "subscription_create",
            "period_start": period_start, "period_end": period_start,
            "lines": {"data": [{
                "type": "subscription", "subscription": STRIPE_SUB,
                "period": {"start": period_start, "end": period_end},
            }]},
        }
        order.refresh_from_db()
        paid_invoice["id"] = order.stripe_invoice_id
        self.webhook("invoice.paid", paid_invoice, event_id="evt_kedja_first_invoice")
        # Stripe levererar samma händelse igen: ingenting händer två gånger.
        self.assertTrue(self.webhook("invoice.paid", paid_invoice, event_id="evt_kedja_first_invoice")["duplicate"])
        self.webhook("customer.subscription.updated", {
            "id": STRIPE_SUB, "object": "subscription", "customer": CUSTOMER, "status": "active",
            "current_period_start": period_start, "current_period_end": period_end,
            "cancel_at_period_end": False, "items": {"data": [{"quantity": 1}]},
            "metadata": {"company_id": company_id},
        })
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.APPLIED)
        window = access.company_window(company_id)
        self.assertEqual(window.reason, "paid_period")
        overview = self.ok(self.call("get", "/api/fleet/company", user=owner, email=OWNER_EMAIL))
        self.assertEqual(overview["features"]["plan"], "full")
        self.assertEqual(overview["features"]["locked"], [])

        # Den betalda platsen tog över provets: samma konto, samma län. Provet
        # var slut, så provplatsen var avslutad och den betalda är en ny rad
        # med samma innehavare -- appen tar den.
        paid_seat = License.objects.get(company_id=company_id, status=License.Status.ACTIVE)
        self.assertNotEqual(str(paid_seat.id), seat["licenseId"])
        self.assertEqual(str(paid_seat.assignee_user_id), owner)
        self.assertEqual(access.license_counties(paid_seat.id), ("12",))
        self.assertEqual(overview["continueVehicles"], [])
        self.assertIsNone(overview["continueOffer"])
        self.ok(self.call("post", "/api/fleet/membership-session", {
            "licenseId": str(paid_seat.id), "deviceId": str(owner_device.id),
        }, user=owner, email=OWNER_EMAIL))
        feed = self.ok(self.call("get", "/api/alerts", user=owner, email=OWNER_EMAIL))
        self.assertTrue(feed["entitled"])
        self.assertEqual(feed["features"]["plan"], "full")
        me = self.ok(self.call("get", "/api/fleet/me", device=owner_phone["device_token"]))
        self.assertEqual(me["counties"], ["12"])

        ferry = self.tip("12", kind="ferry", mode="ferry")
        flight = self.tip("12", kind="flight", mode="flight")
        self.tip("14")  # Västra Götaland: inte platsens län
        self.tip("01")
        self.push_cycle()
        # Tipset från när provet var slut ligger kvar omarkerat (ingen telefon
        # fick väckas då) och når ägaren nu, medan det fortfarande gäller.
        self.assertEqual(
            self.pushed(owner_device),
            {str(ferry.id), str(flight.id), str(transit.id)},
        )

        # ------------------------------------------------------------------
        # 7. Två bilar och en plats till, två förare inbjudna med e-post
        # ------------------------------------------------------------------
        cars = {"addVehicles": [
            {"plate": "KED111", "baseCounty": "12", "label": "Bil 1", "extraCounties": []},
            {"plate": "KED222", "baseCounty": "12", "label": "Bil 2", "extraCounties": ["14"]},
            # "Lägg till medlemskap" utan tilldelning: ges bort i steg 7b.
            {"plate": "", "baseCounty": "14", "label": "", "extraCounties": []},
        ]}
        upgrade = self.ok(self.call(
            "post", "/api/fleet/orders", {**cars, "accepted": True}, user=owner, email=OWNER_EMAIL,
        ))
        self.assertEqual(upgrade["status"], Order.Status.PENDING_PAYMENT)
        # Obetald uppgradering: bilarna finns inte än.
        overview = self.ok(self.call("get", "/api/fleet/company", user=owner, email=OWNER_EMAIL))
        self.assertNotIn("KED111", [r["vehicle"] for r in overview["licenses"]])
        upgrade_order = Order.objects.get(id=upgrade["orderId"])
        self.webhook("invoice.paid", {
            "id": upgrade_order.stripe_invoice_id, "object": "invoice", "customer": CUSTOMER,
            "subscription": None, "status": "paid", "amount_paid": upgrade["totalNowOre"],
            "metadata": {"order_id": str(upgrade_order.id), "company_id": company_id},
            "period_start": int(time.time()), "period_end": int(time.time()),
            "lines": {"data": [{"type": "invoiceitem", "period": {
                "start": int(time.time()), "end": int(time.time())}}]},
        })
        self.webhook("customer.subscription.updated", {
            "id": STRIPE_SUB, "object": "subscription", "customer": CUSTOMER, "status": "active",
            "current_period_start": period_start, "current_period_end": period_end,
            "items": {"data": [{"quantity": 3}]}, "metadata": {"company_id": company_id},
        })
        upgrade_order.refresh_from_db()
        self.assertEqual(upgrade_order.status, Order.Status.APPLIED)
        overview = self.ok(self.call("get", "/api/fleet/company", user=owner, email=OWNER_EMAIL))
        car1 = next(r for r in overview["licenses"] if r["vehicle"] == "KED111")
        car2 = next(r for r in overview["licenses"] if r["vehicle"] == "KED222")

        drivers = {}
        for name, email, car in (
            ("Anna", "anna@forare.test", car1), ("Bo", "bo@forare.test", car2),
        ):
            self.ok(self.call("post", "/api/fleet/driver-invites", {
                "email": email, "licenseId": car["licenseId"], "label": name,
            }, user=owner, email=OWNER_EMAIL))
            mail = self.outbox("driver_invite", to_address=email)
            self.assertEqual(len(mail), 1)
            link = self.auth_links[-1]
            self.assertEqual(link["redirect_to"], DRIVER_PAGE)
            self.assertIn(f"redirect_to={DRIVER_PAGE}", mail[0].body)
            self.assertEqual(mail[0].payload["button"]["label"], "Välj lösenord")
            drivers[email] = DriverInvite.objects.get(email=email).auth_user_id

        phones = {}
        for n, (email, user_id) in enumerate(drivers.items()):
            paired = self.ok(self.call("post", "/api/fleet/driver-invites/claim", {
                "installation_id": f"install-driver-000{n}", "platform": "ios",
                "push_token": f"fcm-driver-{n}",
            }, user=user_id, email=email))
            secret = paired["deviceToken"]
            if not paired.get("sessionStarted"):
                self.ok(self.call("post", "/api/fleet/session", {
                    "license_id": paired.get("licenseId") or (car1 if n == 0 else car2)["licenseId"],
                }, device=secret))
            me = self.ok(self.call("get", "/api/fleet/me", device=secret))
            self.assertTrue(me["entitled"], me)
            phones[email] = (secret, Device.objects.get(id=me["deviceId"]), me["counties"])
            self.assertEqual(DriverInvite.objects.get(email=email).status, DriverInvite.Status.CONSUMED)
        self.assertEqual(phones["anna@forare.test"][2], ["12"])
        self.assertEqual(phones["bo@forare.test"][2], ["12", "14"])

        # En tredje, oinbjuden person får ingenting.
        stranger = str(uuid.uuid4())
        refused = self.call("post", "/api/fleet/driver-invites/claim", {
            "installation_id": "install-stranger-01", "platform": "android",
        }, user=stranger, email="okand@forare.test")
        self.assertEqual(refused.status_code, 404, refused.content)
        self.assertFalse(self.ok(self.call("get", "/api/alerts", user=stranger, email="okand@forare.test"))["entitled"])

        anna_phone, bo_phone = phones["anna@forare.test"][1], phones["bo@forare.test"][1]
        skane_tip = self.tip("12", kind="flight", mode="flight")
        vgr_tip = self.tip("14")
        self.push_cycle()
        self.assertEqual(self.pushed(anna_phone), {str(skane_tip.id)})
        self.assertEqual(self.pushed(bo_phone), {str(skane_tip.id), str(vgr_tip.id)})
        self.assertEqual(self.pushed(owner_device), {str(skane_tip.id)})

        # ------------------------------------------------------------------
        # 7b. Ägaren ger en plats till en ny e-post (portalens "Bjud in ett konto")
        # ------------------------------------------------------------------
        newcomer = "cecilia@forare.test"
        free_seat = License.objects.get(
            company_id=company_id, status=License.Status.ACTIVE, base_county="14",
            assignee_user_id__isnull=True, assignee_email="",
        )
        self.ok(self.call("post", f"/api/fleet/memberships/{free_seat.id}/assign", {
            "mode": "email", "email": newcomer,
        }, user=owner, email=OWNER_EMAIL))
        invitation = self.outbox("membership_invite", to_address=newcomer)
        self.assertEqual(len(invitation), 1, "ingen fick veta att platsen väntade")
        link = self.auth_links[-1]
        self.assertEqual(link["email"], newcomer)
        self.assertEqual(link["redirect_to"], DRIVER_PAGE)
        self.assertIn(f"redirect_to={DRIVER_PAGE}", invitation[0].body)
        self.assertEqual(invitation[0].payload["button"]["label"], "Välj lösenord")
        self.assertIn("Västra Götalands län", invitation[0].body)
        # Mejlet går till en förare: inga priser, inga köplänkar (§9c).
        for word in ("moms", "kr i månaden", "portal", "stripe", "betal", "pris"):
            self.assertNotIn(word, invitation[0].body.lower())
        # "Skicka igen": ett nytt mejl med en ny länk.
        self.ok(self.call(
            "post", f"/api/fleet/memberships/{free_seat.id}/resend-invite", {}, user=owner, email=OWNER_EMAIL,
        ))
        self.assertEqual(len(self.outbox("membership_invite", to_address=newcomer)), 2)
        self.assertEqual(self.auth_links[-1]["email"], newcomer)
        cecilia = self.auth_links[-1]["user_id"]
        # Innan hen loggat in: ingenting.
        self.assertFalse(self.ok(self.call("get", "/api/alerts", user=cecilia, email=newcomer))["entitled"])
        # Hen har valt lösenord via länken och loggar in i appen: listan löser
        # in platsen (claim_for_email), sedan tar appen den.
        mine = self.ok(self.call("get", "/api/fleet/memberships", user=cecilia, email=newcomer))
        self.assertEqual([m["licenseId"] for m in mine["memberships"]], [str(free_seat.id)])
        self.assertEqual(mine["memberships"][0]["counties"], ["14"])
        cecilia_phone = self.ok(self.call("post", "/api/device/session", {
            "installation_id": "install-cecilia-01", "platform": "android",
            "push_token": "fcm-cecilia", "label": "Cecilias telefon",
        }, user=cecilia, email=newcomer))
        cecilia_device = Device.objects.get(id=cecilia_phone["device_id"])
        self.ok(self.call("post", "/api/fleet/membership-session", {
            "licenseId": str(free_seat.id), "deviceId": str(cecilia_device.id),
        }, user=cecilia, email=newcomer))
        feed = self.ok(self.call("get", "/api/alerts", user=cecilia, email=newcomer))
        self.assertTrue(feed["entitled"], feed)
        self.assertEqual(feed["features"]["plan"], "full")
        vgr_only = self.tip("14")
        skane_only = self.tip("12", kind="flight", mode="flight")
        self.push_cycle()
        self.assertEqual(self.pushed(cecilia_device), {str(vgr_only.id)})
        self.assertIn(str(skane_only.id), self.pushed(owner_device))

        # ------------------------------------------------------------------
        # 8. Paus, betalningsfel och uppsägning
        # ------------------------------------------------------------------
        staff = str(uuid.uuid4())
        StaffRole.objects.create(user_id=staff, role=StaffRole.Role.PLATFORM_ADMIN)
        self.ok(self.call(
            "post", f"/api/admin/companies/{company_id}/pause", {"reason": "Obetald faktura"}, user=staff,
        ))
        self.assertEqual(self.ok(self.call("get", "/api/fleet/me", device=phones["anna@forare.test"][0]))["reason"], "company_paused")
        self.assertFalse(self.ok(self.call("get", "/api/alerts", user=owner, email=OWNER_EMAIL))["entitled"])
        self.tip("12")
        self.push_cycle()
        self.assertEqual(self.sent_pushes, [])
        self.ok(self.call(
            "post", f"/api/admin/companies/{company_id}/resume", {"note": "Betald"}, user=staff,
        ))
        self.assertTrue(self.ok(self.call("get", "/api/fleet/me", device=phones["anna@forare.test"][0]))["entitled"])
        resumed = self.tip("12")
        self.push_cycle()
        self.assertIn(str(resumed.id), self.pushed(anna_phone))

        # Förnyelsen misslyckas vid periodens slut: frist i sju dagar från
        # ursprunglig förfallotid, sedan inget.
        self.webhook("invoice.payment_failed", {
            "id": "in_kedja_renewal", "object": "invoice", "customer": CUSTOMER,
            "subscription": STRIPE_SUB, "billing_reason": "subscription_cycle",
            "period_start": period_start, "period_end": period_end, "attempt_count": 1,
        })
        self.webhook("customer.subscription.updated", {
            "id": STRIPE_SUB, "object": "subscription", "customer": CUSTOMER, "status": "past_due",
            "current_period_start": period_start, "current_period_end": period_end,
            "items": {"data": [{"quantity": 3}]}, "metadata": {"company_id": company_id},
        })
        failed = self.outbox("payment_failed")
        self.assertEqual(len(failed), 1)
        self.assertEqual(failed[0].to_address, OWNER_EMAIL, "betalningsfelet saknar mottagare")
        due = Subscription.objects.get(company_id=company_id).current_period_end
        snapshot = {"kind": "transit", "area_codes": ["12"]}
        in_grace = due + timedelta(days=3)
        after_grace = due + timedelta(days=7, minutes=1)
        self.assertEqual(access.company_window(company_id, in_grace).reason, "grace")
        self.assertTrue(push_gate.can_receive(anna_phone, snapshot, now=in_grace).ok)
        self.assertFalse(access.company_window(company_id, after_grace).ok)
        self.assertFalse(push_gate.can_receive(anna_phone, snapshot, now=after_grace).ok)
        # Ett andra försök förlänger inte fristen.
        self.webhook("invoice.payment_failed", {
            "id": "in_kedja_renewal", "object": "invoice", "customer": CUSTOMER,
            "subscription": STRIPE_SUB, "billing_reason": "subscription_cycle",
            "period_start": period_start, "period_end": period_end, "attempt_count": 2,
        })
        self.assertFalse(access.company_window(company_id, after_grace).ok)

        # Kunden betalar till slut, och säger sedan upp: åtkomsten gäller
        # perioden ut, inte en sekund längre.
        self.webhook("invoice.paid", {**paid_invoice, "id": "in_kedja_renewal"})
        self.webhook("customer.subscription.updated", {
            "id": STRIPE_SUB, "object": "subscription", "customer": CUSTOMER, "status": "active",
            "current_period_start": period_start, "current_period_end": period_end,
            "items": {"data": [{"quantity": 3}]}, "metadata": {"company_id": company_id},
        })
        self.assertEqual(access.company_window(company_id).reason, "paid_period")
        self.webhook("customer.subscription.deleted", {
            "id": STRIPE_SUB, "object": "subscription", "customer": CUSTOMER, "status": "canceled",
            "current_period_start": period_start, "current_period_end": period_end,
            "items": {"data": [{"quantity": 3}]}, "metadata": {"company_id": company_id},
        })
        subscription = Subscription.objects.get(company_id=company_id)
        self.assertEqual(subscription.status, SubscriptionStatus.CANCELED)
        self.assertEqual(access.company_window(company_id).reason, "canceled_paid_period")
        self.assertTrue(push_gate.can_receive(anna_phone, snapshot).ok)
        after_end = subscription.access_until + timedelta(minutes=1)
        self.assertFalse(access.company_window(company_id, after_end).ok)
        self.assertFalse(push_gate.can_receive(anna_phone, snapshot, now=after_end).ok)
        self.assertFalse(push_gate.can_receive(owner_device, snapshot, now=after_end).ok)
        # Fakturorna går fortfarande att läsa.
        self.assertTrue(self.ok(self.call("get", "/api/fleet/orders/list", user=owner, email=OWNER_EMAIL))["orders"])


class ChainFocusedTests(ChainBase):
    """Felen kedjetestet hittade, vart och ett för sig."""

    def register(self, owner, email=OWNER_EMAIL):
        reg = self.ok(self.call("post", "/api/fleet/register", {
            "orgNumber": ORG, "contactName": "Ali", "contactPhone": "070-812 34 91",
        }, user=owner, email=email), status=201)
        return reg["companyId"]

    def test_self_registration_sends_the_welcome_mail_once(self):
        owner = str(uuid.uuid4())
        company_id = self.register(owner)
        # Appen som tappade svaret försöker igen: samma företag, inget andra mejl.
        self.ok(self.call("post", "/api/fleet/register", {
            "orgNumber": ORG, "contactName": "Ali", "contactPhone": "070-812 34 91",
        }, user=owner, email=OWNER_EMAIL))
        rows = self.outbox("trial_started")
        self.assertEqual(len(rows), 1)
        self.assertEqual(str(rows[0].company_id), company_id)
        self.assertEqual(rows[0].to_address, OWNER_EMAIL)
        self.assertIn(PORTAL_CONTINUE, rows[0].body)

    def test_company_mail_without_an_address_goes_to_the_billing_email(self):
        from fleet import notifications
        from fleet.models import CompanyProfile

        data = self.full_setup()
        CompanyProfile.objects.filter(company_id=data["company"].id).update(
            billing_email="faktura@demotaxi.test", contact_email="kontakt@demotaxi.test",
        )
        row = notifications.payment_failed(data["subscription"])
        self.assertEqual(row.to_address, "faktura@demotaxi.test")
        CompanyProfile.objects.filter(company_id=data["company"].id).update(billing_email="")
        row = notifications.device_blocked(data["company"].id, data["approval"])
        self.assertEqual(row.to_address, "kontakt@demotaxi.test")
        # En uttrycklig mottagare ändras aldrig.
        row = notifications.trial_started(data["company"].id, "annan@demotaxi.test", Trial(
            id=uuid.uuid4(), ends_at=timezone.now(), vehicle_limit=1,
        ))
        self.assertEqual(row.to_address, "annan@demotaxi.test")

    def test_the_last_day_without_a_card_is_its_own_mail(self):
        from fleet import notifications

        owner = str(uuid.uuid4())
        company_id = self.register(owner)
        trial = Trial.objects.get(company_id=company_id)
        three = notifications.trial_ending(company_id, OWNER_EMAIL, trial, stage="card_missing_3d")
        last = notifications.trial_ending(company_id, OWNER_EMAIL, trial, stage="card_missing_1d")
        self.assertNotEqual(three.subject, last.subject)
        self.assertIn("Sista dygnet", last.subject)
        self.assertIn("inom ett dygn", last.body)
        for row in (three, last):
            self.assertIn(PORTAL_CONTINUE, row.body)

    def test_a_trial_seat_cannot_add_counties_or_skip_the_monthly_limit(self):
        """§7 och §8: självregistrerat prov = ett län; två byten per månad, även i appen."""
        owner = str(uuid.uuid4())
        self.register(owner)
        seat = self.ok(self.call(
            "post", "/api/fleet/memberships/trial", {"baseCounty": "12"}, user=owner, email=OWNER_EMAIL,
        ))["membership"]
        path = f"/api/fleet/memberships/{seat['licenseId']}/county"
        wider = self.call("post", path, {"base": "12", "extras": ["01", "14"]}, user=owner, email=OWNER_EMAIL)
        self.assertEqual(wider.status_code, 400, wider.content)
        self.assertEqual(wider.json()["reason"], "trial_extra_county")
        self.assertEqual(access.license_counties(seat["licenseId"]), ("12",))
        # Det första valet räknas inte; två byten går, det tredje inte.
        for county in ("01", "14"):
            self.ok(self.call("post", path, {"base": county}, user=owner, email=OWNER_EMAIL))
        third = self.call(
            "post", "/api/fleet/memberships/trial", {"baseCounty": "03"}, user=owner, email=OWNER_EMAIL,
        )
        self.assertEqual(third.json()["reason"], "county_change_limit", third.content)
        self.assertEqual(access.license_counties(seat["licenseId"]), ("14",))

    def test_an_ended_trial_seat_gives_no_access_after_payment(self):
        """
        Provplatsen avslutas när provet tar slut. Appens öppna session på den
        får inte fortsätta ge platsens län när bolaget sedan betalar för en
        annan plats -- samma svar som notisgrinden.
        """
        from django.test import RequestFactory

        from fleet import trials

        driver = str(uuid.uuid4())
        owner = str(uuid.uuid4())
        company_id = self.register(owner)
        seat = self.ok(self.call(
            "post", "/api/fleet/memberships/trial", {"baseCounty": "12"}, user=owner, email=OWNER_EMAIL,
        ))["membership"]
        # Platsen ges till en förare (inte medlem i bolaget), som tar den i appen.
        self.ok(self.call("post", f"/api/fleet/memberships/{seat['licenseId']}/assign", {
            "mode": "email", "email": "forare@kedjetaxi.test",
        }, user=owner, email=OWNER_EMAIL))
        # Som appen: listan först (den löser in tilldelningen), sedan platsen.
        self.ok(self.call("get", "/api/fleet/memberships", user=driver, email="forare@kedjetaxi.test"))
        self.ok(self.call("post", "/api/fleet/membership-session", {
            "licenseId": seat["licenseId"],
        }, user=driver, email="forare@kedjetaxi.test"))
        trials.end_trial(Trial.objects.get(company_id=company_id), reason="trial_period_over")
        # Bolaget betalar för en annan plats.
        self.make_subscription(type("C", (), {"id": company_id})())
        self.assertTrue(access.company_window(company_id).ok)

        request = RequestFactory().get(
            "/api/alerts", headers={"authorization": f"Bearer {token(driver, 'forare@kedjetaxi.test')}"},
        )
        result = access.resolve(request)
        self.assertFalse(result.ok, result)
        self.assertEqual(
            License.objects.get(id=seat["licenseId"]).status, License.Status.CANCELED,
        )

    def test_the_admin_password_link_is_a_recovery_link_to_an_allowed_page(self):
        """
        Steg 3, den del som går att pröva på servern: adminens "Skapa
        lösenordslänk" ber Supabase om en recovery-länk (kontot finns redan)
        med en sida som GoTrues tillåtelselista godtar. Appens "Glömt
        lösenord" (implicit flow, redirect taxitips.se/forare) går direkt till
        GoTrue och syns aldrig här.
        """
        from fleet.models import KnownAccount

        # Den riktiga invite_link (setUp byter ut den), med bara requests utbytt.
        self._patch("fleet.auth_admin.invite_link", new=REAL_INVITE_LINK)
        user = uuid.uuid4()
        KnownAccount.objects.create(user_id=user, email="anna@forare.test", last_seen_at=timezone.now())
        staff = str(uuid.uuid4())
        StaffRole.objects.create(user_id=staff, role=StaffRole.Role.PLATFORM_ADMIN)

        calls = []

        def post(url, json=None, headers=None, timeout=None):
            calls.append(json)
            response = mock.Mock()
            if json["type"] == "invite":
                response.status_code, response.text = 422, '{"error_code":"email_exists"}'
                return response
            response.status_code, response.text = 200, "{}"
            response.json.return_value = {
                "action_link": (
                    "https://api.taxitips.se/auth/v1/verify?token=x&type=recovery"
                    f"&redirect_to={json['redirect_to']}"
                ),
                "id": str(user),
            }
            return response

        with mock.patch("fleet.auth_admin.requests.post", side_effect=post):
            body = self.ok(self.call(
                "post", f"/api/admin/accounts/{user}/recovery", {"redirectTo": DRIVER_PAGE}, user=staff,
            ))
            default = self.ok(self.call("post", f"/api/admin/accounts/{user}/recovery", {}, user=staff))
        self.assertEqual(body["kind"], "recovery")
        self.assertEqual([c["type"] for c in calls], ["invite", "recovery", "invite", "recovery"])
        self.assertEqual(calls[1]["redirect_to"], DRIVER_PAGE)
        self.assertIn("type=recovery", body["url"])
        # Utan val: portalen, som också är en godkänd sida.
        self.assertEqual(calls[3]["redirect_to"], "https://taxitips.se/portal")
        self.assertEqual(default["kind"], "recovery")


class TrialSeatContinuationTests(ChainBase):
    """
    "Fortsätt med provet" för en kund som registrerat sig i appen: provplatsen
    har ingen bil (§14). Förut var `continueVehicles` tom för den, kortet i
    portalen visade ingenting och mejlen saknade pris.
    """

    def start_app_trial(self, owner):
        reg = self.ok(self.call("post", "/api/fleet/register", {
            "orgNumber": ORG, "contactName": "Ali", "contactPhone": "070-812 34 91",
        }, user=owner, email=OWNER_EMAIL), status=201)
        seat = self.ok(self.call(
            "post", "/api/fleet/memberships/trial", {"baseCounty": "12"}, user=owner, email=OWNER_EMAIL,
        ))["membership"]
        self.ok(self.call("post", "/api/fleet/membership-session", {
            "licenseId": seat["licenseId"],
        }, user=owner, email=OWNER_EMAIL))
        return reg["companyId"], seat

    def test_card_and_mail_show_the_seat_and_the_same_price(self):
        from fleet import notifications

        owner = str(uuid.uuid4())
        company_id, seat = self.start_app_trial(owner)
        overview = self.ok(self.call("get", "/api/fleet/company", user=owner, email=OWNER_EMAIL))
        self.assertEqual(len(overview["continueVehicles"]), 1)
        row = overview["continueVehicles"][0]
        self.assertEqual((row["kind"], row["licenseId"], row["baseCounty"]), ("membership", seat["licenseId"], "12"))
        offer = overview["continueOffer"]
        self.assertGreater(offer["monthlyOre"], 0)
        mail = notifications.trial_ending(
            company_id, OWNER_EMAIL, Trial.objects.get(company_id=company_id), stage="3d",
        )
        self.assertEqual(mail.payload["offer"]["monthly_ore"], offer["monthlyOre"])
        self.assertIn("er plats (Skåne län)", mail.body)

    def test_commit_during_the_trial_keeps_the_same_seat_for_the_same_person(self):
        from fleet import orders
        from fleet.models import MembershipSession

        def collect(order, *, trial_end, success_url, cancel_url):
            url = f"https://checkout.stripe.com/c/{order.id}"
            Order.objects.filter(id=order.id).update(stripe_payment_url=url)
            return url

        self._patch("fleet.stripe_sync.collect_trial_commit", side_effect=collect)
        owner = str(uuid.uuid4())
        company_id, seat = self.start_app_trial(owner)
        change = {"addVehicles": [{
            "plate": "", "baseCounty": "12", "label": "", "extraCounties": [],
            "continueLicenseId": seat["licenseId"],
        }]}
        committed = self.ok(self.call(
            "post", "/api/fleet/trial/commit", {**change, "accepted": True}, user=owner, email=OWNER_EMAIL,
        ))
        self.assertTrue(committed["paymentUrl"].startswith("https://checkout.stripe.com/"))
        order = Order.objects.get(id=committed["orderId"])
        self.assertTrue(order.request["trial_commit"])
        self.assertEqual(order.request["addVehicles"][0]["continueLicenseId"], seat["licenseId"])

        # Stripe drar vid provslut: beställningen verkställs.
        orders.mark_order_paid(order)
        license = License.objects.get(id=seat["licenseId"])
        self.assertEqual(license.status, License.Status.ACTIVE)
        self.assertEqual(str(license.assignee_user_id), owner)
        self.assertEqual(access.license_counties(license.id), ("12",))
        self.assertEqual(License.objects.filter(company_id=company_id).count(), 1, "en andra plats skapades")
        # Appens öppna session på platsen gäller fortfarande: personen märker inget.
        self.assertTrue(MembershipSession.objects.filter(
            license_id=license.id, user_id=owner, ended_at__isnull=True,
        ).exists())
        self.assertEqual(Trial.objects.get(company_id=company_id).status, Trial.Status.CONVERTED)

    def test_only_the_companys_own_trial_seat_can_be_continued(self):
        owner = str(uuid.uuid4())
        self.start_app_trial(owner)
        other = self.full_setup()
        for bogus in (str(other["license"].id), "inte-ett-id", str(uuid.uuid4())):
            response = self.call("post", "/api/fleet/quote", {"addVehicles": [{
                "plate": "", "baseCounty": "12", "continueLicenseId": bogus,
            }]}, user=owner, email=OWNER_EMAIL)
            self.assertEqual(response.status_code, 404, response.content)
            self.assertEqual(response.json()["reason"], "unknown_trial_seat")


class MembershipInvitationTests(ChainBase):
    """En plats som tilldelas en e-post ger ett mejl med lösenordslänk (som förarinbjudan)."""

    def paid_seat(self):
        data = self.full_setup()
        from fleet import licensing

        seat = licensing.create_membership_license(company_id=data["company"].id, base_county="01")
        return data, seat

    def test_a_known_account_is_bound_and_still_told(self):
        from fleet.models import KnownAccount

        data, seat = self.paid_seat()
        known = uuid.uuid4()
        KnownAccount.objects.create(user_id=known, email="kalle@forare.test", last_seen_at=timezone.now())
        self.ok(self.call("post", f"/api/fleet/memberships/{seat.id}/assign", {
            "mode": "email", "email": "Kalle@Forare.test",
        }, user=str(data["owner"].user_id)))
        seat.refresh_from_db()
        self.assertEqual(seat.assignee_user_id, known)
        mail = self.outbox("membership_invite", to_address="kalle@forare.test")
        self.assertEqual(len(mail), 1)
        self.assertIn("Stockholms län", mail[0].body)
        self.assertEqual(self.auth_links[-1]["redirect_to"], DRIVER_PAGE)
        # Bunden direkt: inget kvar att skicka igen.
        again = self.call(
            "post", f"/api/fleet/memberships/{seat.id}/resend-invite", {}, user=str(data["owner"].user_id),
        )
        self.assertEqual(again.status_code, 409, again.content)

    def test_reassigning_revokes_the_first_address(self):
        data, seat = self.paid_seat()
        owner = str(data["owner"].user_id)
        for email in ("forst@forare.test", "sedan@forare.test"):
            self.ok(self.call("post", f"/api/fleet/memberships/{seat.id}/assign", {
                "mode": "email", "email": email,
            }, user=owner))
            self.assertEqual(len(self.outbox("membership_invite", to_address=email)), 1)
        first = str(uuid.uuid4())
        mine = self.ok(self.call("get", "/api/fleet/memberships", user=first, email="forst@forare.test"))
        self.assertEqual(mine["memberships"], [])
        # Borttagen tilldelning: inget att skicka igen.
        self.ok(self.call("post", f"/api/fleet/memberships/{seat.id}/unassign", {}, user=owner))
        again = self.call("post", f"/api/fleet/memberships/{seat.id}/resend-invite", {}, user=owner)
        self.assertEqual(again.status_code, 409, again.content)

    def test_a_blocked_address_is_not_invited(self):
        from fleet.models import AccountBlock

        data, seat = self.paid_seat()
        AccountBlock.objects.create(kind=AccountBlock.Kind.EMAIL, value="sparrad@forare.test", reason="test")
        refused = self.call("post", f"/api/fleet/memberships/{seat.id}/assign", {
            "mode": "email", "email": "sparrad@forare.test",
        }, user=str(data["owner"].user_id))
        self.assertEqual(refused.status_code, 403, refused.content)
        self.assertEqual(self.outbox("membership_invite"), [])

    def test_staff_assignment_in_admin_sends_the_same_mail(self):
        data, seat = self.paid_seat()
        staff = str(uuid.uuid4())
        StaffRole.objects.create(user_id=staff, role=StaffRole.Role.PLATFORM_ADMIN)
        self.ok(self.call("post", f"/api/admin/licenses/{seat.id}/assign", {
            "email": "ny@forare.test",
        }, user=staff))
        mail = self.outbox("membership_invite", to_address="ny@forare.test")
        self.assertEqual(len(mail), 1)
        self.assertIn(f"redirect_to={DRIVER_PAGE}", mail[0].body)
