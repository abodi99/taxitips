"""
Adminwebbens webbstatistik: bara personal, att GA4:s svar blir vyns form, och
att ett fel i källan visas i stället för att fälla sidan (core/web_analytics.py). Inga riktiga anrop:
requests ersätts.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest import mock

from django.core.cache import cache
from django.test import Client, override_settings

from core import web_analytics
from fleet.models import StaffRole
from fleet.tests.base import FleetTestCase
from fleet.tests.test_admin import SECRET, jwt

PATH = "/api/admin/web-analytics"
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=web_analytics.TZ)


class _Resp:
    def __init__(self, data, status=200):
        self._data, self.status_code = data, status

    def json(self):
        return self._data


def _rows(*rows):
    return {"rows": [
        {"dimensionValues": [{"value": v} for v in dims], "metricValues": [{"value": str(m)} for m in mets]}
        for dims, mets in rows
    ]}


def _ga4_post(url, json=None, **_):
    if url.endswith(":runRealtimeReport"):
        return _Resp(_rows(([], [3])))
    names = [r["dimensions"][0]["name"] if r["dimensions"] else "" for r in json["requests"]]
    reports = {
        "": _rows((["date_range_0"], [120, 150, 400, 0.4, 95]), (["date_range_1"], [100, 130, 350, 0.5, 80])),
        "date": _rows((["20261029"], [20, 25, 60])),
        "dayOfWeek": _rows((["0", "19"], [7]), (["2", "8"], [4])),
        "unifiedPagePathScreen": _rows((["/"], [300])),
        "sessionSource": _rows((["google"], [90])),
        "country": _rows((["Sweden"], [110])),
        "deviceCategory": _rows((["mobile"], [80])),
        "eventName": _rows((["contact_submit"], [5])),
        "platform": _rows((["web"], [120])),
    }
    return _Resp({"reports": [reports[n] for n in names]})


@override_settings(SUPABASE_JWT_SECRET=SECRET)
class AdminWebAnalyticsTests(FleetTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.client = Client()
        self.data = self.full_setup()
        self.support_id = str(uuid.uuid4())
        StaffRole.objects.create(user_id=self.support_id, role=StaffRole.Role.SUPPORT)

    def get(self, user_id, qs=""):
        return self.client.get(PATH + qs, headers={"authorization": f"Bearer {jwt(user_id)}"})

    def test_only_staff_get_in(self):
        self.assertEqual(self.client.get(PATH).status_code, 401)
        response = self.get(str(self.data["owner"].user_id))
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["reason"], "not_staff")

    @mock.patch.dict("os.environ", {"GA4_PROPERTY_ID": ""})
    def test_unconfigured_source_says_so_instead_of_failing(self):
        response = self.get(self.support_id, "?days=7")
        self.assertEqual(response.status_code, 200, response.content)
        body = response.json()
        self.assertEqual(body["days"], 7)
        self.assertEqual(body["sources"]["ga4"]["state"], "not_configured")
        self.assertEqual(list(body["sources"]), ["ga4"])

    def test_ga4_is_normalised(self):
        with mock.patch.dict("os.environ", {"GA4_PROPERTY_ID": "123"}), \
             mock.patch.object(web_analytics, "_ga4_token", return_value="t"), \
             mock.patch.object(web_analytics.requests, "post", side_effect=_ga4_post) as post:
            ga = web_analytics.fetch_ga4(7, "web", NOW)
        self.assertEqual(ga["totals"]["visitors"], 120)
        self.assertEqual(ga["previous"]["visitors"], 100)
        self.assertEqual(ga["totals"]["bounceRate"], 40.0)
        self.assertEqual(len(ga["daily"]), 7)
        self.assertEqual(ga["daily"][-1], {"date": "2026-10-29", "visitors": 20, "sessions": 25, "pageviews": 60})
        # GA4:s söndag (0) kl 19 hamnar sist i veckan; tisdag (2) blir index 1.
        self.assertEqual(ga["heat"][6][19], 7)
        self.assertEqual(ga["heat"][1][8], 4)
        self.assertEqual(ga["events"], [{"name": "contact_submit", "count": 5}])
        self.assertEqual(ga["activeNow"], 3)
        # Webb-läget filtrerar bort appen.
        first_batch = post.call_args_list[0].kwargs["json"]["requests"][0]
        self.assertEqual(first_batch["dimensionFilter"]["filter"]["fieldName"], "platform")

    def test_a_failing_source_is_reported_not_raised(self):
        with mock.patch.dict("os.environ", {"GA4_PROPERTY_ID": "123"}), \
             mock.patch.object(web_analytics, "_ga4_token", return_value="t"), \
             mock.patch.object(web_analytics.requests, "post", return_value=_Resp({}, 403)):
            response = self.get(self.support_id, "?days=7&fresh=1")
        self.assertEqual(response.status_code, 200, response.content)
        ga4 = response.json()["sources"]["ga4"]
        self.assertEqual(ga4["state"], "error")
        self.assertIn("Läsare", ga4["message"])
