"""
Webbstatistik för adminwebben: besök på taxitips.se (och appen) ur Google
Analytics 4, dit Firebase Analytics skickar sina händelser.

Nycklarna stannar här på servern. Webbläsaren ser bara siffrorna, och bara
personal med ADMIN_VIEW (fleet/admin_web_analytics.py).

En källa som saknar inställningar eller inte svarar ger
`state: "not_configured"` eller `"error"` med skälet, aldrig ett fel för hela
sidan. Umami är bortkopplat (servern är nere); formen `sources` gör det enkelt
att lägga till en källa igen.

Miljövariabler:
  GA4_PROPERTY_ID              valfri; standard är taxitips-se (561506602)
  GA4_SERVICE_ACCOUNT_JSON     valfri; annars FIREBASE_SERVICE_ACCOUNT_JSON.
                               Kontot måste vara "Läsare" på egenskapen.

Formen per källa:
  totals / previous   visitors, sessions, pageviews, bounceRate, avgSessionSec
  daily               [{date, visitors, sessions, pageviews}]
  heat                7 x 24 besökare, måndag först, svensk tid
  pages, referrers, countries, devices, events, platforms  [{name, count}]
  activeNow           besökare senaste 30 minuterna
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from django.conf import settings
from django.core.cache import cache

log = logging.getLogger(__name__)

TZ = ZoneInfo("Europe/Stockholm")
TIMEOUT = 15
CACHE_SECONDS = 300
ALLOWED_DAYS = (1, 7, 30, 90)
LIST_LIMIT = 10

GA4_SCOPE = "https://www.googleapis.com/auth/analytics.readonly"
GA4_API = "https://analyticsdata.googleapis.com/v1beta"
# Egenskapen "taxitips-se", kopplad till Firebase-projektet 2026-10-29 (konto
# 324115452). Inte en hemlighet. GA4_PROPERTY_ID="" stänger av källan.
DEFAULT_GA4_PROPERTY = "561506602"


class SourceError(Exception):
    """En källa svarade fel. Meddelandet visas för personalen."""


def _env(name: str) -> str:
    return (os.environ.get(name) or getattr(settings, name, "") or "").strip()


def _empty_heat() -> list[list[int]]:
    return [[0] * 24 for _ in range(7)]


def _window(days: int, now: datetime) -> tuple[date, date, date, date]:
    """Perioden slutar i dag (svensk tid); föregående period är lika lång, direkt före."""
    end = now.astimezone(TZ).date()
    start = end - timedelta(days=days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    return start, end, prev_start, prev_end


# --- Google Analytics 4 -------------------------------------------------------


def _ga4_token() -> str:
    from google.auth.transport.requests import Request
    from google.oauth2 import service_account

    from billing.fcm import load_service_account

    raw = _env("GA4_SERVICE_ACCOUNT_JSON") or _env("FIREBASE_SERVICE_ACCOUNT_JSON")
    info = load_service_account(raw)
    if not info:
        raise SourceError("Inget tjänstekonto (GA4_SERVICE_ACCOUNT_JSON eller FIREBASE_SERVICE_ACCOUNT_JSON).")
    cached = cache.get("web_analytics:ga4_token")
    if cached:
        return cached
    creds = service_account.Credentials.from_service_account_info(info, scopes=[GA4_SCOPE])
    creds.refresh(Request())
    cache.set("web_analytics:ga4_token", creds.token, 45 * 60)
    return creds.token


def _ga4_post(path: str, body: dict) -> dict:
    token = _ga4_token()
    try:
        r = requests.post(
            f"{GA4_API}/{path}", json=body, timeout=TIMEOUT,
            headers={"Authorization": f"Bearer {token}"},
        )
    except requests.RequestException as exc:
        raise SourceError(f"Google Analytics svarar inte ({exc.__class__.__name__}).") from exc
    if r.status_code == 403:
        raise SourceError(
            "Tjänstekontot får inte läsa egenskapen. Lägg till det som Läsare under "
            "Analytics > Admin > Egenskapsåtkomst, och slå på Google Analytics Data API."
        )
    if r.status_code >= 400:
        try:
            message = r.json().get("error", {}).get("message", "")
        except ValueError:
            message = ""
        raise SourceError(f"Google Analytics svarade {r.status_code}. {message}".strip())
    return r.json()


def _ga4_rows(report: dict) -> list[tuple[list[str], list[float]]]:
    out = []
    for row in report.get("rows", []) or []:
        dims = [d.get("value", "") for d in row.get("dimensionValues", [])]
        mets = [float(m.get("value") or 0) for m in row.get("metricValues", [])]
        out.append((dims, mets))
    return out


_GA4_TOTALS = ["activeUsers", "sessions", "screenPageViews", "bounceRate", "averageSessionDuration"]


def _ga4_totals(mets: list[float]) -> dict:
    users, sessions, views, bounce, avg = (mets + [0] * 5)[:5]
    return {
        "visitors": int(users), "sessions": int(sessions), "pageviews": int(views),
        "bounceRate": round(bounce * 100, 1) if sessions else None,
        "avgSessionSec": round(avg) if sessions else None,
    }


def _ga4_list(report: dict) -> list[dict]:
    return [{"name": d[0] or "(okänd)", "count": int(m[0])} for d, m in _ga4_rows(report)]


def fetch_ga4(days: int, scope: str, now: datetime) -> dict:
    prop = _env("GA4_PROPERTY_ID").removeprefix("properties/") if "GA4_PROPERTY_ID" in os.environ \
        else DEFAULT_GA4_PROPERTY
    if not prop:
        raise LookupError("GA4_PROPERTY_ID saknas.")
    start, end, prev_start, prev_end = _window(days, now)
    rng = {"startDate": start.isoformat(), "endDate": end.isoformat()}
    prev = {"startDate": prev_start.isoformat(), "endDate": prev_end.isoformat()}
    # Webb = bara taxitips.se. Alla = också appen (iOS/Android) i samma egenskap.
    flt = (
        {"filter": {"fieldName": "platform", "stringFilter": {"value": "web", "caseSensitive": False}}}
        if scope == "web" else None
    )

    def req(dims, metrics, *, ranges=None, limit=None, order_metric=True):
        body = {
            "dateRanges": ranges or [rng],
            "dimensions": [{"name": d} for d in dims],
            "metrics": [{"name": m} for m in metrics],
        }
        if flt:
            body["dimensionFilter"] = flt
        if limit:
            body["limit"] = limit
        if order_metric and dims:
            body["orderBys"] = [{"metric": {"metricName": metrics[0]}, "desc": True}]
        return body

    first = _ga4_post(f"properties/{prop}:batchRunReports", {"requests": [
        req([], _GA4_TOTALS, ranges=[rng, prev]),
        req(["date"], ["activeUsers", "sessions", "screenPageViews"], order_metric=False),
        req(["dayOfWeek", "hour"], ["activeUsers"], order_metric=False),
        req(["unifiedPagePathScreen"], ["screenPageViews"], limit=LIST_LIMIT),
        req(["sessionSource"], ["sessions"], limit=LIST_LIMIT),
    ]})["reports"]
    second = _ga4_post(f"properties/{prop}:batchRunReports", {"requests": [
        req(["country"], ["activeUsers"], limit=LIST_LIMIT),
        req(["deviceCategory"], ["activeUsers"], limit=LIST_LIMIT),
        req(["eventName"], ["eventCount"], limit=25),
        req(["platform"], ["activeUsers"], limit=LIST_LIMIT),
    ]})["reports"]

    # Med två datumintervall får varje rad en extra dimension "dateRange".
    totals = previous = _ga4_totals([])
    for dims, mets in _ga4_rows(first[0]):
        if dims and dims[-1] == "date_range_1":
            previous = _ga4_totals(mets)
        else:
            totals = _ga4_totals(mets)

    by_day = {
        d[0]: {"visitors": int(m[0]), "sessions": int(m[1]), "pageviews": int(m[2])}
        for d, m in _ga4_rows(first[1])
    }
    daily = []
    for i in range(days):
        day = start + timedelta(days=i)
        daily.append({"date": day.isoformat(),
                      **by_day.get(day.strftime("%Y%m%d"), {"visitors": 0, "sessions": 0, "pageviews": 0})})

    heat = _empty_heat()
    for dims, mets in _ga4_rows(first[2]):
        # GA4: 0 = söndag. Här: 0 = måndag.
        wd, hour = (int(dims[0]) + 6) % 7, int(dims[1])
        heat[wd][hour] += int(mets[0])

    active_now = None
    try:
        rt_body = {"metrics": [{"name": "activeUsers"}]}
        if flt:
            rt_body["dimensionFilter"] = flt
        rt = _ga4_post(f"properties/{prop}:runRealtimeReport", rt_body)
        rows = _ga4_rows(rt)
        active_now = int(rows[0][1][0]) if rows else 0
    except SourceError:
        pass  # realtid är en bonus; perioden visas ändå

    return {
        "totals": totals, "previous": previous, "daily": daily, "heat": heat,
        "pages": _ga4_list(first[3]), "referrers": _ga4_list(first[4]),
        "countries": _ga4_list(second[0]), "devices": _ga4_list(second[1]),
        "events": _ga4_list(second[2]), "platforms": _ga4_list(second[3]),
        "activeNow": active_now, "activeWindow": "30 min",
        "dashboardUrl": f"https://analytics.google.com/analytics/web/#/p{prop}/reports/intelligenthome",
    }


# --- Ingången ----------------------------------------------------------------


def _run(name: str, fn) -> dict:
    try:
        return {"state": "ok", **fn()}
    except LookupError as exc:
        return {"state": "not_configured", "message": str(exc)}
    except SourceError as exc:
        return {"state": "error", "message": str(exc)}
    except Exception:  # en trasig källa får aldrig fälla sidan
        log.exception("webbstatistik: %s misslyckades", name)
        return {"state": "error", "message": "Oväntat fel när källan lästes. Se serverloggen."}


def report(days: int, scope: str = "web", *, now: datetime | None = None, fresh: bool = False) -> dict:
    days = days if days in ALLOWED_DAYS else 30
    scope = scope if scope in ("web", "all") else "web"
    now = now or datetime.now(TZ)
    key = f"web_analytics:report:{days}:{scope}"
    if not fresh:
        hit = cache.get(key)
        if hit:
            return hit
    result = {
        "days": days, "scope": scope, "generatedAt": now.isoformat(),
        "sources": {
            "ga4": _run("ga4", lambda: fetch_ga4(days, scope, now)),
        },
    }
    cache.set(key, result, CACHE_SECONDS)
    return result
