"""
Medlemskapets län når telefonen direkt (2026-10-09).

Felet ägaren såg: admin gav medlemskapet tre län, men appen visade bara ett.
Tre saker samverkade:

* ett beviljande skriver länen som EXTRA-rader utan BASE-rad (avsiktligt,
  fleet/grants.py) -- läsarna måste ta unionen,
* länändringen synkade bara telefoner med `DeviceApproval` (bilmodellen), inte
  kontots telefon i det kontobaserade medlemskapet,
* `/api/fleet/me` skickas utan JWT, och gav då bolagets alla län i stället för
  platsens.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid

from django.test import Client, override_settings
from django.utils import timezone

from billing.models import Device
from fleet import access, device_prefs, grants, licensing
from fleet.device_prefs import ENTITLED_KEY
from fleet.models import LicenseCounty
from fleet.tests.base import FleetTestCase
from fleet.tests.test_access import STOCKHOLM, tip

SECRET = "membership-counties-secret-at-least-32-chars!"

# Linköping (05) och Kalmar (08): två län långt från Stockholm.
LINKOPING = {"lat": 58.4108, "lon": 15.6214}


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
class MembershipCountiesReachThePhoneTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        self.client = Client()
        # Bolaget har en bil i Kronoberg (07) -- den ingår INTE i medlemskapet.
        self.data = self.full_setup(county="07")
        self.company = self.data["company"]
        self.user_id = self.data["owner"].user_id
        self.phone = Device.objects.create(
            id=uuid.uuid4(), company_id=self.company.id, token=f"install-{uuid.uuid4().hex}",
            label="App (android)", kind="owner_app", created_at=timezone.now(),
            user_id=self.user_id,
            notify_prefs={"counties": ["01"], ENTITLED_KEY: ["01"]},
        )

    def jwt_headers(self) -> dict:
        return {"authorization": f"Bearer {_jwt(self.user_id, 'agare@taxi.test')}"}

    def app_headers(self) -> dict:
        return {**self.jwt_headers(), "x-device-token": self.phone.token}

    def take_membership(self, license):
        r = self.client.post(
            "/api/fleet/membership-session",
            data=json.dumps({"licenseId": str(license.id)}),
            content_type="application/json", headers=self.jwt_headers(),
        )
        self.assertEqual(r.status_code, 200, r.content)

    def grant(self, counties):
        return grants.grant_membership(
            company_id=self.company.id, user_id=self.user_id, reason="goodwill",
            all_counties=False, counties=counties, actor_user_id=uuid.uuid4(),
        )

    def prefs(self) -> dict:
        self.phone.refresh_from_db()
        return self.phone.notify_prefs

    # --- representationen ------------------------------------------------

    def test_a_granted_seat_has_only_extra_rows_and_every_reader_sees_all_of_them(self):
        grant = self.grant(["01", "05"])
        kinds = set(
            LicenseCounty.objects.filter(license=grant.license, active_to__isnull=True)
            .values_list("kind", flat=True)
        )
        self.assertEqual(kinds, {LicenseCounty.Kind.EXTRA})
        self.assertEqual(access.license_counties(grant.license_id), ("01", "05"))

    # --- admin ändrar länen -> telefonen ---------------------------------

    def test_taking_the_granted_seat_gives_the_phone_both_counties(self):
        grant = self.grant(["01", "05"])
        self.take_membership(grant.license)
        self.assertEqual(self.prefs()["counties"], ["01", "05"])
        self.assertEqual(self.prefs()[ENTITLED_KEY], ["01", "05"])

    def test_admin_adding_a_county_reaches_the_phone_without_a_request(self):
        grant = self.grant(["01", "05"])
        self.take_membership(grant.license)

        grants.update_grant(grant, all_counties=False, counties=["01", "05", "08"])

        self.assertEqual(self.prefs()["counties"], ["01", "05", "08"])

    def test_the_drivers_deselection_survives_an_admin_change(self):
        grant = self.grant(["01", "05", "08"])
        self.take_membership(grant.license)
        Device.objects.filter(id=self.phone.id).update(
            notify_prefs={"counties": ["01", "08"], ENTITLED_KEY: ["01", "05", "08"]}
        )

        grants.update_grant(grant, all_counties=False, counties=["01", "05", "08", "12"])
        self.assertEqual(self.prefs()["counties"], ["01", "08", "12"])

        grants.update_grant(grant, all_counties=False, counties=["05", "08"])
        self.assertEqual(self.prefs()["counties"], ["08"])

    def test_a_paid_extra_county_reaches_the_account_phone(self):
        grant = self.grant(["01"])
        self.take_membership(grant.license)
        licensing.activate_extra_county(license=grant.license, county_code="05")
        self.assertEqual(self.prefs()["counties"], ["01", "05"])

    def test_a_phone_whose_account_runs_another_seat_is_left_alone(self):
        first = self.grant(["01"])
        self.take_membership(first.license)
        _, other = self.make_license(self.company, plate="OTH123", county="14")
        other.assignee_user_id = self.user_id
        other.save(update_fields=["assignee_user_id"])

        self.assertEqual(device_prefs.account_device_ids(other), [])
        licensing.activate_extra_county(license=other, county_code="06")
        self.assertEqual(self.prefs()["counties"], ["01"])

    # --- läsarna ---------------------------------------------------------

    def test_fleet_me_without_a_jwt_gives_the_seats_counties_not_the_companys(self):
        grant = self.grant(["01", "05", "08"])
        self.take_membership(grant.license)

        r = self.client.get("/api/fleet/me", headers={"x-device-token": self.phone.token})

        self.assertEqual(r.status_code, 200, r.content)
        body = r.json()
        self.assertTrue(body["entitled"], body)
        self.assertEqual(body["counties"], ["01", "05", "08"])
        self.assertNotIn("07", body["counties"])

    def test_fleet_me_without_a_session_still_gets_the_owner_view(self):
        r = self.client.get("/api/fleet/me", headers={"x-device-token": self.phone.token})
        body = r.json()
        self.assertEqual(body["kind"], "member")
        self.assertEqual(body["counties"], ["07"])

    def test_notify_settings_list_every_licensed_county(self):
        grant = self.grant(["01", "05"])
        self.take_membership(grant.license)
        body = self.client.get("/api/notify-prefs", headers=self.app_headers()).json()
        self.assertEqual(body["licensedCounties"], ["01", "05"])
        self.assertEqual(body["prefs"]["counties"], ["01", "05"])

    def test_the_feed_shows_tips_from_both_counties(self):
        grant = self.grant(["01", "05"])
        self.take_membership(grant.license)
        tip(title="Stopp i Stockholm", area_codes=["01"], region="sl",
            lat=STOCKHOLM["lat"], lon=STOCKHOLM["lon"])
        tip(title="Stopp i Linköping", area_codes=["05"], region="otraf",
            lat=LINKOPING["lat"], lon=LINKOPING["lon"])
        tip(title="Stopp i Kronoberg", area_codes=["07"], region="krono",
            lat=56.8777, lon=14.8091)

        for params in ({}, {"counties": "01,05"}):
            with self.subTest(**params):
                body = self.client.get("/api/alerts", params, headers=self.app_headers()).json()
                self.assertEqual(body.get("counties"), ["01", "05"], body)
                titles = {a["title"] for a in body.get("alerts", [])}
                self.assertEqual(titles, {"Stopp i Stockholm", "Stopp i Linköping"})
